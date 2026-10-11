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


def test_hand_hint_matches_shared_ace_pair_and_excludes_unused_kickers():
    game=table((1000,1000));game.update(stage='river',board=[18,10,47,1,51])
    game['players'][0]['cards']=[15,38] # 4 hearts, ace clubs
    game['players'][1]['cards']=[30,12] # 6 clubs, ace spades
    for seat,unused in ((0,15),(1,30)):
        hint=engine.hand_hint(game,seat)
        assert hint['label']=='Ét par' and len(hint['cards'])==2
        assert unused not in hint['cards']
        assert all(c%13+2==14 for c in hint['cards'])
        assert not hint['plays_board']
    assert engine.public(game,0)['hand_hint']['cards']==[38,51]


@pytest.mark.parametrize('cards,label',[
    ([12,10,8,5,14],'Ingen kombination endnu'),([12,25,10,8,5],'Ét par'),
    ([12,25,10,23,5],'To par'),([12,25,38,8,5],'Tre ens'),
    ([12,0,1,2,16],'Straight'),([12,10,8,5,1],'Flush'),
    ([12,25,38,0,13],'Fuldt hus'),([12,25,38,51,5],'Fire ens'),
    ([0,1,2,3,4],'Straight flush'),([8,9,10,11,12],'Royal flush')])
def test_hand_hint_labels_use_settlement_ranking(cards,label):
    game=table();game.update(stage='flop',board=cards[2:]);game['players'][0]['cards']=cards[:2]
    hint=engine.hand_hint(game,0)
    assert hint['label']==label
    category=engine.rank_five(cards)[0]
    assert len(hint['cards'])=={0:0,1:2,2:4,3:3,7:4}.get(category,5)
    assert set(hint['cards']).issubset(cards)
    assert hint['complete']


def test_hand_hint_playing_board_and_private_start_cards():
    game=table();game.update(stage='river',board=[8,9,10,11,12])
    game['players'][0]['cards']=[13,26]
    hint=engine.hand_hint(game,0)
    assert hint['label']=='Royal flush' and hint['plays_board']
    assert set(hint['cards'])==set(game['board'])
    game.update(stage='preflop',board=[])
    assert engine.hand_hint(game,0)['label']=='Ét par'
    assert not engine.hand_hint(game,0)['complete']
    game['players'][0]['cards']=[0,25]
    assert engine.hand_hint(game,0)['cards']==[]
    game['players'][0]['folded']=True
    assert engine.hand_hint(game,0) is None
    game['players'][1]['cards']=[12,38]
    assert engine.public(game,0)['players'][1]['cards']==[None,None]


def test_no_combination_screenshots_have_no_highlights():
    game=table();game['players'][0]['cards']=[47,16] # 10 diamonds, 5 hearts
    game.update(stage='flop',board=[24,46,27]) # K hearts, 9 diamonds, 3 clubs
    assert engine.hand_hint(game,0)['cards']==[]
    assert engine.hand_hint(game,0)['label']=='Ingen kombination endnu'
    game['players'][0]['cards']=[37,6] # K clubs, 8 spades
    game.update(stage='turn',board=[29,41,48,14]) # 5 clubs, 4 diamonds, J diamonds, 3 hearts
    assert engine.hand_hint(game,0)['cards']==[]


def test_two_pairs_do_not_highlight_ace_kicker():
    game=table();game['players'][0]['cards']=[34,6]
    game.update(stage='turn',board=[13,26,8,38])
    hint=engine.hand_hint(game,0)
    assert hint['label']=='To par'
    assert set(hint['cards'])=={34,13,26,8}
    assert 38 not in hint['cards']


def test_winning_straight_is_described_identically_for_both_players():
    game=table((0,0));game.update(stage='river',board=[47,33,43,32,49],dealer=0)
    for p,cards in zip(game['players'],([26,44],[45,23])):
        p.update(cards=cards,in_hand=True,folded=False,total=100)
    assert engine.winner_description(game,0) is None
    engine.settle(game)
    assert game['winners']==[0]
    for seat in (0,1):
        result=engine.public(game,seat)
        assert result['players'][0]['win_description']=='Vandt med straight'
        assert result['players'][1]['win_description'] is None


def test_win_description_after_fold_does_not_disclose_winners_hand_type():
    game=table((1000,1000));engine.start(game,now=0)
    loser=game['turn'];engine.act(game,loser,'fold',now=1)
    winner=game['winners'][0]
    for seat in (0,1):
        assert engine.public(game,seat)['players'][winner]['win_description']=='Vandt — de andre foldede'


def test_high_card_win_is_distinct_from_no_made_combination_hint():
    game=table((0,0));game.update(stage='river',board=[0,16,31,9,11],dealer=0)
    for p,cards in zip(game['players'],([12,20],[1,21])):
        p.update(cards=cards,in_hand=True,folded=False,total=100)
    engine.settle(game)
    assert game['winners']==[0]
    assert engine.hand_hint(game,0)['label']=='Ingen kombination endnu'
    assert engine.winner_description(game,0)=='Vandt med højt kort'


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


def test_two_pairs_beat_aces_and_uncalled_refund_is_not_a_win():
    game=table((1080,0));game.update(stage='river',board=[10,46,11,26,29],dealer=1)
    for p,total,cards in zip(game['players'],(390,530),([24,20],[51,25])):
        p.update(in_hand=True,folded=False,total=total,cards=cards)
    assert engine.best_hand(game['players'][0]['cards']+game['board'])==(2,13,9,12)
    assert engine.best_hand(game['players'][1]['cards']+game['board'])==(1,14,13,12,9)
    engine.settle(game)
    assert [p['stack'] for p in game['players']]==[1860,140]
    assert game['winners']==[0]


def test_real_side_pot_winner_remains_distinct_from_uncalled_refund():
    game=table((0,0,0));game.update(stage='river',board=[10,46,11,26,29],dealer=0)
    for p,total,cards in zip(game['players'],(100,200,250),([24,20],[51,25],[36,19])):
        p.update(in_hand=True,folded=False,total=total,cards=cards)
    engine.settle(game)
    assert [p['stack'] for p in game['players']]==[300,200,50]
    assert game['winners']==[0,1]


def test_deadline_folds_disconnected_player():
    game=table((1000,1000));engine.start(game,now=0);seat=game['turn']
    engine.tick(game,now=61)
    assert game['players'][seat]['folded'] and game['stage']=='finished'
    assert sum(p['stack'] for p in game['players'])==2000


@pytest.mark.parametrize('action,amount,paid,bet',[('fold',None,0,0),('call',None,20,20),('raise',60,60,60),('allin',None,1000,1000)])
def test_action_events_keep_correct_amount_before_street_or_cashout(action,amount,paid,bet):
    game=table();engine.start(game,now=0);seat=game['turn']
    engine.act(game,seat,action,amount,now=1)
    event=engine.public(game,seat)['events'][-1]
    assert event=={'id':game['revision'],'seat':seat,'action':action,'paid':paid,'bet':bet,'at':1}
    assert 'cards' not in event


def test_check_event_and_hand_number_survive_multiple_hands():
    game=table((1000,1000));engine.start(game,now=0)
    engine.act(game,game['turn'],'call',now=1)
    engine.act(game,game['turn'],'check',now=2)
    assert game['stage']=='flop' and game['events'][-1]['action']=='check'
    assert game['events'][-1]['paid']==0
    engine.act(game,game['turn'],'fold',now=3)
    engine.start(game,now=4)
    assert game['hand_id']==2


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


def test_waiting_cashout_player_is_not_seated_in_next_hand(pair):
    _,_,host,guest,peer,_=pair;code=join(pair)
    third=peer.post('/api/poker/peer',json={'op':'join','token':code,'join_id':'f'*32,'name':'Third','buyin':1000}).json
    view=host.get('/api/poker/state').json['view']
    post(host,'action',{'op':'start','revision':view['revision']})
    assert post(guest,'action',{'op':'leave'}).json['leaving']
    for _ in range(30):
        view=host.get('/api/poker/state').json['view']
        if view['stage']=='finished':break
        body={'op':'action','action':'call','revision':view['revision']}
        response=post(host,'action',body) if view['turn']==view['seat'] else peer.post('/api/poker/peer',json={**body,'token':third['token']})
        assert response.status_code==200
    assert view['stage']=='finished'
    started=post(host,'action',{'op':'start','revision':view['revision']})
    assert started.status_code==200
    assert started.json['view']['players'][1]['cards']==[]
    assert guest.get('/api/poker/state').json['connected'] is False
