from datetime import datetime, timedelta, timezone
import re
from unittest.mock import Mock

import pytest
from app import create_app


@pytest.mark.parametrize('login_mode',['password','sso'])
@pytest.mark.parametrize('proxied',[False,True])
def test_domain_login_earns_full_quarter_reward(tmp_path,monkeypatch,login_mode,proxied):
    user={'id':7,'username':'DomainPlayer','must_change_password':False}
    def hub_request(method,url,**kwargs):
        data={'ok':True,'user':user} if url.endswith('/authenticate') else (
            {'ok':True,**user} if url.endswith('/sso-verify') else {'ok':True,'items':[user]})
        return Mock(status_code=200,ok=True,json=lambda:data)
    monkeypatch.setattr('app.requests.request',hub_request)
    now=[datetime(2026,10,12,12,tzinfo=timezone.utc)]
    app=create_app({'TESTING':True,'AUTH_MODE':'fjordhub','FJORDHUB_URL':'http://hub.invalid',
        'FJORDHUB_API_KEY':'synthetic-test-key','DATA_DIR':str(tmp_path),'CLOCK':lambda:now[0]})
    client=app.test_client()
    origin='https://casino.example'
    base='http://casino.example' if proxied else origin
    headers={'X-Forwarded-Proto':'https'} if proxied else {}
    def token(html):return re.search(r'name="csrf(?:-token)?" (?:value|content)="([^"]+)"',html).group(1)
    if login_mode=='password':
        page=client.get('/login',base_url=base,headers=headers)
        result=client.post('/login',base_url=base,headers={**headers,'Origin':origin},
            data={'username':'DomainPlayer','password':'synthetic-password','csrf':token(page.text)})
    else:
        result=client.get('/hub-login?token=synthetic',base_url=base,headers=headers)
    assert result.status_code==302
    page=client.get('/',base_url=base,headers=headers)
    csrf=token(page.text)
    for i in range(46):
        result=client.post('/api/presence',base_url=base,
            headers={**headers,'Origin':origin,'X-CSRF-Token':csrf},json={'active':True,'tab_id':'a'*32})
        assert result.status_code==200,result.text
        assert result.json['rewards']['active'] is True
        assert result.json['balance']==(50500 if i==45 else 50000)
        now[0]+=timedelta(seconds=20)
