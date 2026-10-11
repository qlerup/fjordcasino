from datetime import datetime, timezone, timedelta
import json
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest
from app import create_app
from db import connect
import games


@pytest.fixture
def app(tmp_path):
    return create_app({'TESTING':True,'AUTH_MODE':'local','DATA_DIR':str(tmp_path)})


def register(client, name='Player'):
    client.get('/login')
    with client.session_transaction() as session: csrf=session['csrf']
    result=client.post('/login',data={'username':name,'password':'test-password-only','mode':'register','csrf':csrf})
    assert result.status_code==302
    return client


def play(client, game='slots', body=None, ident='test-round-000001'):
    with client.session_transaction() as session: csrf=session['csrf']
    return client.post('/api/play/'+game,json={**(body or {'machine':'duck','bet':30}),'request_id':ident},headers={'X-CSRF-Token':csrf})


def heartbeat(client, active=True, tab='a'*32):
    with client.session_transaction() as session: token=session['csrf']
    return client.post('/api/presence',json={'active':active,'tab_id':tab},headers={'X-CSRF-Token':token})


def test_active_rewards_and_restart(tmp_path):
    now=[datetime(2026,10,10,21,59,tzinfo=timezone.utc)]
    config={'TESTING':True,'AUTH_MODE':'local','DATA_DIR':str(tmp_path),'CLOCK':lambda:now[0]}
    app=create_app(config);client=register(app.test_client())
    assert client.get('/api/state').json['user']['balance']==10000
    heartbeat(client)
    for _ in range(29):
        now[0]+=timedelta(seconds=30);heartbeat(client)
    assert client.get('/api/state').json['user']['balance']==10000
    now[0]+=timedelta(seconds=30)
    assert heartbeat(client).json['balance']==10500
    cookie=client.get_cookie('fjordcasino_session').value
    restarted=create_app(config).test_client();restarted.set_cookie('fjordcasino_session',cookie)
    assert restarted.get('/api/state').json['user']['balance']==10500


def test_offline_time_does_not_count_and_partial_time_is_saved(tmp_path):
    now=[datetime(2026,10,11,tzinfo=timezone.utc)]
    app=create_app({'TESTING':True,'AUTH_MODE':'local','DATA_DIR':str(tmp_path),'CLOCK':lambda:now[0]})
    c=register(app.test_client());heartbeat(c)
    for _ in range(15):now[0]+=timedelta(seconds=30);heartbeat(c)
    heartbeat(c,False)
    now[0]+=timedelta(days=3)
    assert heartbeat(c).json['balance']==10000
    for _ in range(15):now[0]+=timedelta(seconds=30);heartbeat(c)
    assert c.get('/api/state').json['user']['balance']==10500
    now[0]+=timedelta(hours=2)
    assert heartbeat(c).json['balance']==10500


def test_multiple_tabs_do_not_multiply_rewards(tmp_path):
    now=[datetime(2026,10,11,tzinfo=timezone.utc)]
    app=create_app({'TESTING':True,'AUTH_MODE':'local','DATA_DIR':str(tmp_path),'CLOCK':lambda:now[0]})
    c=register(app.test_client());heartbeat(c);heartbeat(c,tab='b'*32)
    for i in range(30):
        now[0]+=timedelta(seconds=30);heartbeat(c);heartbeat(c,tab='b'*32)
        if i==14:heartbeat(c,False)
    assert c.get('/api/state').json['user']['balance']==10500


def test_old_accounts_reset_once_at_login_and_clear_old_round(tmp_path):
    app=create_app({'TESTING':True,'AUTH_MODE':'local','DATA_DIR':str(tmp_path)})
    c=register(app.test_client())
    with connect(app.extensions['db_path']) as db:
        db.execute('DELETE FROM coin_rewards')
        db.execute('UPDATE users SET balance=123')
        db.execute("INSERT INTO blackjack VALUES(1,?)", (json.dumps({'status':'playing'}),))
        db.execute('PRAGMA user_version=1')
    with c.session_transaction() as session:session.pop('wallet_version')
    assert c.get('/api/state').status_code==401
    # Restart/migrate does not reset accounts before their next login.
    app=create_app({'TESTING':True,'AUTH_MODE':'local','DATA_DIR':str(tmp_path)})
    with connect(app.extensions['db_path']) as db:assert db.execute('SELECT balance FROM users').fetchone()[0]==123
    c=app.test_client();c.get('/login')
    with c.session_transaction() as session:token=session['csrf']
    assert c.post('/login',data={'username':'Player','password':'test-password-only','csrf':token}).status_code==302
    data=c.get('/api/state').json
    assert data['user']['balance']==10000 and data['blackjack'] is None and len(data['history'])==1
    with connect(app.extensions['db_path']) as db:db.execute('UPDATE users SET balance=4321')
    with c.session_transaction() as session:token=session['csrf']
    c.post('/api/logout',json={},headers={'X-CSRF-Token':token})
    c.get('/login')
    with c.session_transaction() as session:token=session['csrf']
    c.post('/login',data={'username':'Player','password':'test-password-only','csrf':token})
    assert c.get('/api/state').json['user']['balance']==4321


def test_auth_csrf_and_static(app):
    client=app.test_client()
    assert client.get('/api/state').status_code==401
    register(client)
    assert client.post('/api/play/slots',json={}).status_code==403
    with client.session_transaction() as session: token=session['csrf']
    assert client.post('/api/logout',json={},headers={'X-CSRF-Token':token,'Origin':'https://outside.invalid'}).status_code==403
    assert client.get('/static/casino.js').status_code==200
    assert client.get('/').headers['Cache-Control']=='no-store'


def test_idempotency_and_conflict(app):
    client=register(app.test_client());first=play(client)
    assert first.status_code==200
    assert play(client).json==first.json
    assert play(client,body={'machine':'duck','bet':60}).status_code==409
    with connect(app.extensions['db_path']) as db:
        assert db.execute("SELECT count(*) FROM ledger WHERE kind='bet'").fetchone()[0]==1


def test_concurrent_duplicate_is_one_round(app):
    client=register(app.test_client());cookie=client.get_cookie('fjordcasino_session').value
    def attempt(_):
        c=app.test_client();c.set_cookie('fjordcasino_session',cookie);return play(c).json
    with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(attempt,range(2)))
    assert results[0]==results[1]
    with connect(app.extensions['db_path']) as db:
        assert db.execute("SELECT count(*) FROM ledger WHERE kind='bet'").fetchone()[0]==1


@pytest.mark.parametrize('game,body',[('slots',{'machine':[],'bet':30}),('slots',{'machine':'duck','bet':True}),('slots',{'machine':'duck','bet':-30}),('roulette',{'table':'classic','bets':[{'kind':[],'amount':20}]}),('roulette',{'table':'classic','bets':[{'kind':'number','value':37,'amount':20}]}),('blackjack',{'action':'start','bet':True})])
def test_invalid_bets_do_not_change_balance(app,game,body):
    c=register(app.test_client());assert play(c,game,body).status_code==400
    assert c.get('/api/state').json['user']['balance']==10000


def test_insufficient_balance_rolls_back(app):
    c=register(app.test_client())
    with connect(app.extensions['db_path']) as db: db.execute('UPDATE users SET balance=0')
    assert play(c).status_code==400
    with connect(app.extensions['db_path']) as db:
        assert db.execute('SELECT count(*) FROM actions').fetchone()[0]==0
        assert db.execute('SELECT balance FROM users').fetchone()[0]==0


def test_user_isolation(app):
    one=register(app.test_client(),'First');two=register(app.test_client(),'Second')
    play(one)
    assert two.get('/api/state').json['user']['balance']==10000
    assert len(two.get('/api/state').json['history'])==1


@pytest.mark.parametrize('number',[0,1,2,12,13,24,25,36])
def test_roulette_payouts(number):
    bets=[{'kind':'number','value':number,'amount':20},{'kind':'color','value':'red','amount':20},{'kind':'parity','value':'even','amount':20}]
    out=games.roulette_payout(number,bets)
    assert out[0]['payout']==720
    assert out[1]['payout']==(40 if number in games.RED else 0)
    assert out[2]['payout']==(40 if number and number%2==0 else 0)


def test_slot_lines_and_wild():
    lines=games.slot_payout([['duck-yellow','wild','duck-yellow'],['wild']*3,['duck-pink','duck-yellow','duck-pink']],'duck',30)
    assert [line['payout'] for line in lines]==[80,2000]


def test_blackjack_hidden_cards_resume_and_no_double_payment(app,monkeypatch):
    def start(bet):return {'game':'blackjack','deck':[9,4,2],'player':[9,7],'dealer':[8,7],'bet':bet,'status':'playing','payout':0,'result':'','doubled':False,'round_id':'fixture-round'}
    monkeypatch.setattr(games,'start_blackjack',start)
    c=register(app.test_client());result=play(c,'blackjack',{'action':'start','bet':20}).json
    assert result['dealer']==[8,None] and 'deck' not in result
    assert c.get('/api/state').json['blackjack']['round_id']=='fixture-round'
    finish=play(c,'blackjack',{'action':'stand','round_id':'fixture-round'},'test-round-000002')
    assert finish.json['payout']==40
    assert play(c,'blackjack',{'action':'stand','round_id':'fixture-round'},'test-round-000002').json==finish.json
    assert play(c,'blackjack',{'action':'stand','round_id':'fixture-round'},'test-round-000003').status_code==400
    assert c.get('/api/state').json['user']['balance']==10020


def test_blackjack_aces_and_double():
    assert games.hand_value([0,13,9])==(12,False)
    assert games.hand_value([0,5])==(17,True)
    game={'deck':[4,9],'player':[3,5],'dealer':[8,7],'bet':20,'status':'playing','doubled':False}
    result=games.act_blackjack(game,'double')
    assert result['bet']==40 and result['status']=='finished' and result['payout']==80


def test_hub_sso_and_revoked_membership(tmp_path,monkeypatch):
    import app as module
    users=[{'id':7,'username':'HubPlayer','must_change_password':False}]
    def request(method,url,**kwargs):
        data={'ok':True,'id':7} if url.endswith('sso-verify') else {'ok':True,'items':users}
        assert kwargs['allow_redirects'] is False
        return Mock(status_code=200,ok=True,json=lambda:data)
    monkeypatch.setattr(module.requests,'request',request)
    app=create_app({'TESTING':True,'AUTH_MODE':'fjordhub','FJORDHUB_URL':'http://hub.invalid','FJORDHUB_API_KEY':'synthetic-key','DATA_DIR':str(tmp_path)})
    c=app.test_client();assert c.get('/hub-login?token=synthetic').status_code==302
    assert c.get('/api/state').json['user']['balance']==10000
    users.clear()
    with c.session_transaction() as session: session['hub_checked']=0
    assert c.get('/api/state').status_code==401
