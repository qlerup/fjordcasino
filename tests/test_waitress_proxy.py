from datetime import datetime, timedelta, timezone
from http.cookies import SimpleCookie
import re
from threading import Thread
from unittest.mock import Mock

import pytest
import requests
from waitress import create_server

from app import create_app
from wsgi import server_options


@pytest.mark.parametrize('configured', [False, True])
def test_https_login_and_reward_through_waitress(tmp_path, monkeypatch, configured):
    user = {'id': 7, 'username': 'DomainPlayer', 'must_change_password': False}
    def hub_request(method, url, **kwargs):
        data = {'ok': True, 'user': user} if url.endswith('/authenticate') else {
            'ok': True, 'items': [user]}
        return Mock(status_code=200, ok=True, json=lambda: data)
    monkeypatch.setattr('app.requests.request', hub_request)
    now = [datetime(2026, 10, 13, 12, tzinfo=timezone.utc)]
    app = create_app({'TESTING': True, 'AUTH_MODE': 'fjordhub',
        'FJORDHUB_URL': 'http://hub.invalid', 'FJORDHUB_API_KEY': 'synthetic',
        'DATA_DIR': str(tmp_path), 'CLOCK': lambda: now[0]})
    server = create_server(app, host='127.0.0.1', port=0,
                           **(server_options(app) if configured else {}))
    thread = Thread(target=server.run, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.effective_port}'
    headers = {'Host': 'casino.example', 'X-Forwarded-Proto': 'https',
               'X-Forwarded-Host': 'outside.invalid', 'X-Forwarded-For': '203.0.113.7'}
    # Explicit cookies simulate the HTTPS browser side of the proxy.
    def update_cookie(response):
        cookie = SimpleCookie(response.headers['Set-Cookie'])
        headers['Cookie'] = 'fjordcasino_session=' + cookie['fjordcasino_session'].value
    try:
        page = requests.get(base + '/login', headers=headers, timeout=5)
        update_cookie(page)
        csrf = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
        headers['Origin'] = 'https://casino.example'
        result = requests.post(base + '/login', headers=headers, timeout=5,
            allow_redirects=False, data={'username': 'DomainPlayer',
                'password': 'synthetic-password', 'csrf': csrf})
        if not configured:
            assert result.status_code == 403
            assert result.json()['error'] == 'Forespørgslen skal komme fra FjordCasino.'
            return
        assert result.status_code == 302, result.text
        assert '; Secure;' in result.headers['Set-Cookie']
        update_cookie(result)
        page = requests.get(base + '/', headers=headers, timeout=5)
        csrf = re.search(r'name="csrf-token" content="([^"]+)"', page.text).group(1)
        headers['X-CSRF-Token'] = csrf
        for i in range(46):
            result = requests.post(base + '/api/presence', headers=headers, timeout=5,
                json={'active': True, 'tab_id': 'a' * 32})
            assert result.status_code == 200, result.text
            assert result.json()['balance'] == (10500 if i == 45 else 10000)
            assert result.json()['rewards']['active'] is True
            now[0] += timedelta(seconds=20)
        headers['Origin'] = 'https://outside.invalid'
        result = requests.post(base + '/api/presence', headers=headers, timeout=5,
            json={'active': True, 'tab_id': 'a' * 32})
        assert result.status_code == 403
    finally:
        server.close()
        server.task_dispatcher.shutdown()
        thread.join(timeout=5)


def test_standalone_does_not_trust_proxy_headers():
    assert server_options(Mock(config={'AUTH_MODE': 'local'})) == {}
