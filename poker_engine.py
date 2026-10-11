"""Persistent six-seat Texas Hold'em with side pots and server-only cards."""
from collections import Counter
from itertools import combinations
import secrets
import time
from games import GameError, require_int


def rank_five(cards):
    values=sorted((c%13+2 for c in cards),reverse=True)
    groups=sorted(((n,v) for v,n in Counter(values).items()),reverse=True)
    flush=len({c//13 for c in cards})==1
    unique=sorted(set(values),reverse=True)
    straight=5 if unique==[14,5,4,3,2] else unique[0] if len(unique)==5 and unique[0]-unique[-1]==4 else 0
    if flush and straight:return (8,straight)
    if groups[0][0]==4:return (7,groups[0][1],groups[1][1])
    if [g[0] for g in groups]==[3,2]:return (6,groups[0][1],groups[1][1])
    if flush:return (5,*values)
    if straight:return (4,straight)
    if groups[0][0]==3:return (3,groups[0][1],*sorted((v for n,v in groups[1:]),reverse=True))
    if groups[0][0]==2 and groups[1][0]==2:return (2,*sorted([groups[0][1],groups[1][1]],reverse=True),groups[2][1])
    if groups[0][0]==2:return (1,groups[0][1],*sorted((v for n,v in groups[1:]),reverse=True))
    return (0,*values)


def best_hand(cards):return max(rank_five(list(c)) for c in combinations(cards,5))


def next_seat(table,after,eligible):
    for step in range(1,len(table['players'])+1):
        seat=(after+step)%len(table['players'])
        if eligible(table['players'][seat]):return seat
    return None


def ready(p):return not p.get('left') and not p.get('withdrawing') and p['stack']>0
def live(p):return p.get('in_hand') and not p.get('folded')
def movable(p):return live(p) and p['stack']>0


def pay(p,amount):
    amount=min(amount,p['stack']);p['stack']-=amount;p['bet']+=amount;p['total']+=amount


def start(table,now=None):
    if table['stage'] not in ('waiting','finished'):raise GameError('Afslut den aktuelle hånd først.')
    if sum(ready(p) for p in table['players'])<2:raise GameError('Mindst to spillere med jetoner skal sidde ved bordet.')
    table.update(stage='preflop',board=[],deck=list(range(52)),current_bet=20,min_raise=20,acted=[],message='',winners=[],revision=table['revision']+1)
    secrets.SystemRandom().shuffle(table['deck'])
    for p in table['players']:
        p.update(in_hand=ready(p),folded=False,bet=0,total=0,cards=[])
        if p['in_hand']:p['cards']=[table['deck'].pop(),table['deck'].pop()]
    table['dealer']=next_seat(table,table.get('dealer',-1),live)
    count=sum(live(p) for p in table['players'])
    small=table['dealer'] if count==2 else next_seat(table,table['dealer'],live)
    big=next_seat(table,small,live);pay(table['players'][small],10);pay(table['players'][big],20)
    table['turn']=next_seat(table,big,movable);table['deadline']=(time.time() if now is None else now)+60
    advance(table,now)


def settle(table):
    contenders=[(i,p) for i,p in enumerate(table['players']) if live(p)]
    if len(contenders)==1:
        winners=[contenders[0][0]];table['players'][winners[0]]['stack']+=sum(p.get('total',0) for p in table['players'])
    else:
        ranks={i:best_hand(p['cards']+table['board']) for i,p in contenders};winners=[];previous=0
        for level in sorted({p.get('total',0) for p in table['players'] if p.get('total',0)>0}):
            contributors=[i for i,p in enumerate(table['players']) if p.get('total',0)>=level]
            increment=level-previous;pot=increment*len(contributors);previous=level
            eligible=[i for i in contributors if i in ranks]
            if not eligible:
                # An unmatched contribution is returned to its contributor.
                for i in contributors:table['players'][i]['stack']+=increment
                continue
            best=max(ranks[i] for i in eligible);won=[i for i in eligible if ranks[i]==best]
            ordered=sorted(won,key=lambda i:(i-table['dealer']-1)%len(table['players']))
            for j,i in enumerate(ordered):table['players'][i]['stack']+=pot//len(won)+(j<pot%len(won))
            winners.extend(won)
    table.update(stage='finished',turn=None,winners=sorted(set(winners)),message='Hånden er afsluttet.',deadline=None)


def advance(table,now=None):
    now=time.time() if now is None else now
    while table['stage'] not in ('waiting','finished'):
        players=table['players']
        if sum(live(p) for p in players)<=1:settle(table);return
        can=[i for i,p in enumerate(players) if movable(p)]
        pending=[i for i in can if i not in table['acted'] or players[i]['bet']<table['current_bet']]
        if len(can)==1 and players[can[0]]['bet']>=table['current_bet']:pending=[]
        if pending:
            if table['turn'] not in pending:
                table['turn']=next_seat(table,table['turn'] if table['turn'] is not None else table['dealer'],lambda p:players.index(p) in pending)
            table['deadline']=now+60;return
        if table['stage']=='river':settle(table);return
        count=3 if table['stage']=='preflop' else 1
        table['deck'].pop() # burn
        table['board'].extend(table['deck'].pop() for _ in range(count))
        table['stage']={'preflop':'flop','flop':'turn','turn':'river'}[table['stage']]
        table['current_bet']=0;table['min_raise']=20;table['acted']=[]
        for p in players:p['bet']=0
        table['turn']=next_seat(table,table['dealer'],movable)


def act(table,seat,action,amount=None,now=None):
    if table['stage'] in ('waiting','finished') or table['turn']!=seat:raise GameError('Det er ikke din tur.')
    p=table['players'][seat];owed=table['current_bet']-p['bet']
    if action=='fold':p['folded']=True
    elif action=='check':
        if owed:raise GameError('Du skal kalde indsatsen eller folde.')
    elif action=='call':pay(p,owed)
    elif action in ('raise','allin'):
        target=p['bet']+p['stack'] if action=='allin' else require_int(amount,1,1000000)
        if target<=table['current_bet']:
            if action!='allin':raise GameError('Hæv til mere end den aktuelle indsats.')
            pay(p,target-p['bet'])
        else:
            if seat in table['acted']:raise GameError('En kort all-in har ikke genåbnet din mulighed for at hæve. Kald eller fold.')
            increment=target-table['current_bet']
            if target>p['bet']+p['stack'] or (increment<table['min_raise'] and target!=p['bet']+p['stack']):raise GameError('Hæv mindst minimumsindsatsen, eller gå all-in.')
            pay(p,target-p['bet'])
            if increment>=table['min_raise']:table['acted']=[];table['min_raise']=increment
            table['current_bet']=target
    else:raise GameError('Ugyldig pokerhandling.')
    if seat not in table['acted']:table['acted'].append(seat)
    table['revision']+=1;table['turn']=next_seat(table,seat,movable);advance(table,now)


def tick(table,now=None):
    now=time.time() if now is None else now
    if table.get('turn') is not None and now>table['deadline']:act(table,table['turn'],'fold',now=now)


def public(table,seat):
    p=table['players'][seat]
    return {'stage':table['stage'],'board':table.get('board',[]),'turn':table.get('turn'),'dealer':table.get('dealer'),
            'revision':table['revision'],'deadline':table.get('deadline'),'current_bet':table.get('current_bet',0),
            'min_raise':table.get('min_raise',20),'pot':sum(p.get('total',0) for p in table['players']) if table['stage'] not in ('waiting','finished') else 0,
            'winners':table.get('winners',[]),'seat':seat,'host':p.get('host',False),'message':table.get('message',''),
            'players':[{'name':v['name'],'stack':v['stack'],'bet':v.get('bet',0),'folded':v.get('folded',False),'left':v.get('left',False),
                       'cards':v.get('cards',[]) if i==seat or table['stage']=='finished' and live(v) else [None]*len(v.get('cards',[]))} for i,v in enumerate(table['players'])]}
