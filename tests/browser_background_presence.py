"""Hidden tabs earn rewards with minute-batched timers and stop on navigation."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import tempfile
import threading

from playwright.sync_api import expect, sync_playwright
from flask import request
from werkzeug.serving import make_server

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app
from db import connect


with tempfile.TemporaryDirectory() as data:
    now = [datetime(2026, 10, 13, 12, tzinfo=timezone.utc)]
    app = create_app({'TESTING': True, 'AUTH_MODE': 'local', 'DATA_DIR': data,
                      'CLOCK': lambda: now[0]})
    stopped = threading.Event()
    @app.after_request
    def record_stop(response):
        if request.endpoint == 'presence' and request.get_json().get('active') is False and response.status_code == 200:
            stopped.set()
        return response
    server = make_server('127.0.0.1', 0, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            for width in (390, 1440):
                page = browser.new_page(viewport={'width': width, 'height': 900})
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.clock.install(time=now[0])
                # Headless Chromium does not reliably hide tabs. Simulate its
                # visibility flags and minute-batched timer execution explicitly.
                page.add_init_script("""Object.defineProperty(document, 'hidden', {get: () => true});
                    Object.defineProperty(document, 'visibilityState', {get: () => 'hidden'});""")
                base = f'http://127.0.0.1:{server.server_port}'
                page.goto(base + '/login')
                page.get_by_label('Brugernavn').fill('Background' + str(width))
                page.get_by_label('Adgangskode').fill('synthetic-password')
                page.get_by_role('button', name='Opret en spiller').click()
                expect(page.locator('#daily-label')).to_contain_text('Næste 500 om')
                page.wait_for_function('!presenceBusy')
                assert page.evaluate('document.hidden') is True
                with page.expect_response(lambda response: '/api/presence' in response.url):
                    page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
                page.wait_for_function('!presenceBusy')
                expect(page.locator('#daily-label')).to_contain_text('Næste 500 om')
                for i in range(15):
                    now[0] += timedelta(seconds=60)
                    with page.expect_response(lambda response: '/api/presence' in response.url) as response:
                        page.clock.fast_forward(60000)
                    assert response.value.status == 200
                    assert response.value.json()['rewards']['active'] is True
                    page.wait_for_function('!presenceBusy')
                expect(page.locator('#balance')).to_have_text('50.500')
                # Chromium can finish keepalive requests after the document is
                # gone, without reporting a response event on the original page.
                stopped.clear()
                page.goto(base + '/login')
                assert stopped.wait(timeout=5), 'Navigation did not end presence'
                with connect(app.extensions['db_path']) as db:
                    assert db.execute('SELECT count(*) FROM coin_presence').fetchone()[0] == 0
                now[0] += timedelta(minutes=15)
                assert page.request.get(base + '/api/state').json()['user']['balance'] == 50500
                assert not errors, errors
                page.close()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
print('PASS: hidden tabs earn 500 per quarter with minute-batched timers; navigation stops earning')
