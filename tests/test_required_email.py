from unittest.mock import Mock
from app import create_app


def test_required_email_blocks_existing_player_and_restores_account(tmp_path,monkeypatch):
    member={'id':7,'username':'Player','role':'user','email_required':False}
    calls=[]
    def request(method,url,**kwargs):
        if url.endswith('/sso-verify'):data=dict(member,ok=True)
        elif url.endswith('/users'):data={'ok':True,'items':[dict(member)]}
        elif url.endswith('/config'):data={'ok':True,'external_url':''}
        else:
            calls.append((url,kwargs['json']));member['email_required']=False
            data={'ok':True,'accepted':True,'user':dict(member)}
        return Mock(status_code=200,ok=True,json=lambda:data)
    monkeypatch.setattr('app.requests.request',request)
    app=create_app({'TESTING':True,'AUTH_MODE':'fjordhub','FJORDHUB_URL':'http://hub.invalid','FJORDHUB_API_KEY':'synthetic-key','DATA_DIR':str(tmp_path)})
    c=app.test_client();assert c.get('/hub-login?token=synthetic').status_code==302
    uid=c.get('/api/state').json['user']['id']
    member['email_required']=True
    blocked=c.get('/api/auth/access')
    assert blocked.status_code==403 and blocked.json['error_code']=='email_update_required'
    assert c.get('/api/state').status_code==403
    assert c.post('/api/auth/email',json={'email':'new@example.test','id':999},headers={'X-CSRF-Token':blocked.json['csrf_token']}).json['accepted'] is True
    assert calls[-1][0].endswith('/users/7/email')
    assert c.get('/api/state').json['user']['id']==uid
