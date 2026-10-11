import json
import random
from unittest.mock import Mock
import pytest
import requests
from app import create_app
from db import connect
from games import GameError
from test_casino import register
import poker_engine as engine


def post(client,path,body):
    with client.session_transaction() as session:token=session['csrf']
    return client.post('/api/poker/'+path,json=body,headers={'X-CSRF-Token':token})


def table(stacks=(1000,1000,1000)):
    return {'players':[{'name':str(i),'stack':stack,'left':False,'host':i==0} for i,stack in enumerate(stacks)],'stage':'waiting','revision':0,'dealer':-1,'board':[],'turn':None}


def test_hand_ranking():
    assert engine.rank_five([12,0,1,2,3])==(8,5) # A2345 of one suit
    assert engine.rank_five([0,13,26,39,12])==(7,2,14)
    assert engine.best_hand([0,13,26,39,12,11,10])==(7,2,14)


@pytest.mark.parametrize('stacks',[(1000,1000),(1000,1000,1000),(35,70,150),(10,10)])
def test_hands_conserve_coins_and_keep_cards_private(stacks):
    for seed in range(10):
        rng=random.Random(seed);game=table(stacks);engine.start(game,now=0)
        for _ in range(150):
            if game['stage']=='finished':break
            seat=game['turn'];p=game['players'][seat]
            public=engine.public(game,seat)
            assert 'deck' not in public
            assert all(all(c is None for c in other['cards']) for i,other in enumerate(public['players']) if i!=seat)
            action=rng.choice(['fold','call','allin'])
            try:engine.act(game,seat,action,now=0)
            except GameError:engine.act(game,seat,'call',now=0)
        assert game['stage']=='finished'
        assert sum(p['stack'] for p in game['players'])==sum(stacks)


def test_side_pots_and_odd_chip():
    game=table((0,0,0));game.update(stage='river',board=[0,2,5,7,9],dealer=0)
    # All players share the same best flush; split each side pot.
    for i,p in enumerate(game['players']):p.update(in_hand=True,folded=False,total=[25,50,50][i],cards=[13+i,26+i])
    engine.settle(game)
    assert sum(p['stack'] for p in game['players'])==125
    assert game['players'][0]['stack']==25
    assert sorted(p['stack'] for p in game['players'][1:])==[50,50]


def test_deadline_folds_disconnected_player():
    game=table((1000,1000));engine.start(game,now=0);seat=game['turn']
    engine.tick(game,now=61)
    assert game['players'][seat]['folded'] and game['stage']=='finished'
    assert sum(p['stack'] for p in game['players'])==2000


@pytest.fixture
def pair(tmp_path,monkeypatch):
    host_app=create_app({'TESTING':True,'AUTH_MODE':'local','DATA_DIR':str(tmp_path/'host')})
    guest_app=create_app({'TESTING':True,'AUTH_MODE':'local','DATA_DIR':str(tmp_path/'guest')})
    host=register(host_app.test_client(),'Host');guest=register(guest_app.test_client(),'Guest')
    peer=host_app.test_client()
    def send(url,**kwargs):
        assert url=='http://192.168.50.10:8070/api/poker/peer'
        assert kwargs['allow_redirects'] is False
        response=peer.post('/api/poker/peer',json=kwargs['json'])
        return Mock(status_code=response.status_code,is_redirect=False,ok=response.status_code<400,content=response.data,json=lambda:response.json)
    monkeypatch.setattr('poker_service.requests.post',send)
    return host_app,guest_app,host,guest,peer,send


def join(pair):
    _,_,host,guest,_,_=pair
    code=post(host,'create',{}).json['code']
    assert post(host,'connect',{'url':'local','code':code}).status_code==200
    response=post(guest,'connect',{'url':'http://192.168.50.10:8070','code':code})
    assert response.status_code==200
    return code


def test_two_installations_use_own_wallets_and_repeated_cashout(pair):
    _,_,host,guest,peer,_=pair;join(pair)
    assert host.get('/api/state').json['user']['balance']==9000
    assert guest.get('/api/state').json['user']['balance']==9000
    hv=host.get('/api/poker/state').json['view']
    assert len(hv['players'])==2 and hv['host']
    assert post(host,'action',{'op':'start','revision':hv['revision']}).status_code==200
    for _ in range(20):
        view=host.get('/api/poker/state').json['view']
        if view['stage']=='finished':break
        player=host if view['turn']==view['seat'] else guest
        assert post(player,'action',{'op':'action','action':'call','revision':view['revision']}).status_code==200
    assert host.get('/api/poker/state').json['view']['stage']=='finished'
    guest_out=post(guest,'action',{'op':'leave'}).json
    host_out=post(host,'action',{'op':'leave'}).json
    assert guest_out['returned']+host_out['returned']==2000
    assert post(guest,'action',{'op':'leave'}).json=={'connected':False}
    assert host.get('/api/state').json['user']['balance']+guest.get('/api/state').json['user']['balance']==20000
    assert peer.post('/api/poker/peer',json={'op':'view','token':'x'*32}).status_code==400


def test_lost_join_response_is_recovered_without_second_debit(pair,monkeypatch):
    host_app,guest_app,host,guest,peer,send=pair
    code=post(host,'create',{}).json['code'];post(host,'connect',{'url':'local','code':code})
    lost=[False]
    def interrupted(url,**kwargs):
        response=send(url,**kwargs)
        if kwargs['json']['op']=='join' and not lost[0]:lost[0]=True;raise requests.Timeout()
        return response
    monkeypatch.setattr('poker_service.requests.post',interrupted)
    assert post(guest,'connect',{'url':'http://192.168.50.10:8070','code':code}).status_code==400
    assert guest.get('/api/state').json['user']['balance']==9000
    assert guest.get('/api/poker/state').json['connected']
    assert guest.get('/api/state').json['user']['balance']==9000
    assert len(host.get('/api/poker/state').json['view']['players'])==2


def test_bad_invite_and_loopback_never_debit(pair):
    _,_,_,guest,_,_=pair
    assert post(guest,'connect',{'url':'http://192.168.50.10:8070','code':'x'*32}).status_code==400
    assert post(guest,'connect',{'url':'http://127.0.0.1:8070','code':'x'*32}).status_code==400
    assert guest.get('/api/state').json['user']['balance']==10000


def test_restart_preserves_indskud_and_join_token(pair):
    _,guest_app,host,guest,_,_=pair;join(pair)
    cookie=guest.get_cookie('fjordcasino_session').value
    restarted=create_app(guest_app.config).test_client();restarted.set_cookie('fjordcasino_session',cookie)
    assert restarted.get('/api/poker/state').json['connected']
    assert post(restarted,'action',{'op':'leave'}).json['returned']==1000
    assert restarted.get('/api/state').json['user']['balance']==10000


def test_lost_cashout_response_is_credited_once(pair,monkeypatch):
    _,_,host,guest,_,send=pair;join(pair)
    lost=[False]
    def interrupted(url,**kwargs):
        response=send(url,**kwargs)
        if kwargs['json']['op']=='leave' and not lost[0]:lost[0]=True;raise requests.Timeout()
        return response
    monkeypatch.setattr('poker_service.requests.post',interrupted)
    assert post(guest,'action',{'op':'leave'}).status_code==400
    assert guest.get('/api/state').json['user']['balance']==9000
    assert guest.get('/api/poker/state').json['returned']==1000
    assert guest.get('/api/poker/state').json=={'connected':False}
    assert guest.get('/api/state').json['user']['balance']==10000


def test_guest_cannot_start_and_stale_action_does_not_repeat(pair):
    _,_,host,guest,_,_=pair;join(pair)
    view=guest.get('/api/poker/state').json['view']
    assert post(guest,'action',{'op':'start','revision':view['revision']}).status_code==400
    start=post(host,'action',{'op':'start','revision':view['revision']}).json['view']
    player=host if start['turn']==start['seat'] else guest
    body={'op':'action','action':'call','revision':start['revision']}
    response=post(player,'action',body);assert response.status_code==200
    repeated=post(player,'action',body);assert repeated.json['stale']
    assert repeated.json['view']['revision']==response.json['view']['revision']


def test_full_table_refund_survives_lost_join_reply(pair,monkeypatch):
    _,_,host,guest,peer,send=pair
    code=post(host,'create',{}).json['code']
    post(host,'connect',{'url':'local','code':code})
    for i in range(5):
        assert peer.post('/api/poker/peer',json={'op':'join','token':code,'join_id':f'{i:032x}','name':f'Friend{i}','buyin':1000}).status_code==200
    lost=[False]
    def interrupted(url,**kwargs):
        response=send(url,**kwargs)
        if kwargs['json']['op']=='join' and not lost[0]:lost[0]=True;raise requests.Timeout()
        return response
    monkeypatch.setattr('poker_service.requests.post',interrupted)
    assert post(guest,'connect',{'url':'http://192.168.50.10:8070','code':code}).status_code==400
    assert guest.get('/api/state').json['user']['balance']==9000
    assert guest.get('/api/poker/state').json=={'connected':False,'returned':1000}
    assert guest.get('/api/poker/state').json=={'connected':False}
    assert guest.get('/api/state').json['user']['balance']==10000
    assert len(host.get('/api/poker/state').json['view']['players'])==6


def test_upgrade_from_schema_two_does_not_repeat_wallet_reset(tmp_path):
    config={'TESTING':True,'AUTH_MODE':'local','DATA_DIR':str(tmp_path)}
    app=create_app(config);client=register(app.test_client())
    with connect(app.extensions['db_path']) as db:
        db.execute('DROP TABLE poker_escrow')
        db.execute('DROP TABLE poker_members')
        db.execute('DROP TABLE poker_tables')
        db.execute('PRAGMA user_version=2')
        db.execute('UPDATE users SET balance=4321')
    upgraded=create_app(config).test_client()
    upgraded.get('/login')
    with upgraded.session_transaction() as session:token=session['csrf']
    response=upgraded.post('/login',data={'username':'Player','password':'test-password-only','mode':'login','csrf':token})
    assert response.status_code==302
    assert upgraded.get('/api/state').json['user']['balance']==4321
    with connect(app.extensions['db_path']) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0]==3
        assert db.execute('SELECT reset_version FROM coin_rewards').fetchone()[0]==2


def test_leave_pending_join_preserves_retry_after_lost_cashout(pair,monkeypatch):
    _,_,host,guest,_,send=pair
    code=post(host,'create',{}).json['code'];post(host,'connect',{'url':'local','code':code})
    lost={'join':False,'leave':False}
    def interrupted(url,**kwargs):
        response=send(url,**kwargs);op=kwargs['json']['op']
        if op in lost and not lost[op]:lost[op]=True;raise requests.Timeout()
        return response
    monkeypatch.setattr('poker_service.requests.post',interrupted)
    assert post(guest,'connect',{'url':'http://192.168.50.10:8070','code':code}).status_code==400
    assert post(guest,'action',{'op':'leave'}).status_code==400
    assert guest.get('/api/poker/state').json=={'connected':False,'returned':1000}
    assert guest.get('/api/state').json['user']['balance']==10000
