"""Friend-table hosting and recoverable wallet escrow across installations."""
import hashlib
import ipaddress
import json
import secrets
import socket
from urllib.parse import urlsplit
import requests
from flask import g, jsonify, request
from db import connect
from games import GameError, require_int
import poker_engine as engine


def digest(value):return hashlib.sha256(value.encode()).hexdigest()


def address(value):
    if not isinstance(value,str) or len(value)>500:raise GameError('Ugyldig værtsadresse.')
    parsed=urlsplit(value.strip())
    if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('','/'):
        raise GameError('Brug værtens HTTP- eller HTTPS-adresse uden sti.')
    try:
        ips=[ipaddress.ip_address(item[4][0]) for item in socket.getaddrinfo(parsed.hostname,parsed.port or (443 if parsed.scheme=='https' else 80),type=socket.SOCK_STREAM)]
    except (OSError,ValueError):raise GameError('Værtens adresse kunne ikke findes.') from None
    if not ips or any(ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified for ip in ips):
        raise GameError('Vælg værtens domæne eller lokale netværksadresse.')
    return value.strip().rstrip('/')


def install(app,credit):
    path=app.extensions['db_path']

    def host(payload,local_uid=None):
        if not isinstance(payload,dict):raise GameError('Ugyldig pokerforespørgsel.')
        token=payload.get('token');op=payload.get('op')
        if not isinstance(token,str) or not 20<=len(token)<=100:raise GameError('Vennekoden eller spilleradgangen er ugyldig.')
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            if op in ('join','probe'):
                row=db.execute('SELECT * FROM poker_tables WHERE invite_hash=?',(digest(token),)).fetchone()
                if not row:raise GameError('Vennekoden findes ikke på denne installation.')
                if op=='probe':return {'ok':True,'protocol':'fjordcasino-poker-v1'}
                join=payload.get('join_id');name=payload.get('name');buyin=payload.get('buyin')
                if not isinstance(join,str) or len(join)!=32 or any(c not in '0123456789abcdef' for c in join) or not isinstance(name,str) or not 1<=len(name)<=100:raise GameError('Ugyldig spiller.')
                require_int(buyin,1000,1000)
                rejected_token=digest('rejected:'+token+':'+join)
                if db.execute('SELECT 1 FROM poker_members WHERE token_hash=? AND seat=-1',(digest(rejected_token),)).fetchone():
                    return {'ok':True,'token':rejected_token,'rejected':True}
                table=json.loads(row['state']);seat=next((i for i,p in enumerate(table['players']) if p['join_id']==join),None)
                if seat is None:
                    if sum(not p.get('left') for p in table['players'])>=6 or len(table['players'])>=100:
                        # Persist a refund receipt even if its HTTP reply is lost.
                        db.execute('INSERT INTO poker_members VALUES(?,?,?,?)',(digest(rejected_token),row['id'],-1,buyin))
                        return {'ok':True,'token':rejected_token,'rejected':True}
                    player={'join_id':join,'token':secrets.token_urlsafe(32),'name':name,'stack':buyin,'host':local_uid==row['owner'],'left':False,'in_hand':False}
                    table['players'].append(player);seat=len(table['players'])-1;table['revision']+=1
                p=table['players'][seat]
                if p.get('left'):raise GameError('Dette indskud er allerede afsluttet.')
                db.execute('INSERT OR IGNORE INTO poker_members VALUES(?,?,?,NULL)',(digest(p['token']),row['id'],seat))
                db.execute('UPDATE poker_tables SET state=? WHERE id=?',(json.dumps(table),row['id']))
                return {'ok':True,'token':p['token'],'table_id':row['id'],'view':engine.public(table,seat)}
            row=db.execute('SELECT * FROM poker_members WHERE token_hash=?',(digest(token),)).fetchone()
            if not row:raise GameError('Spilleradgangen er ugyldig.')
            if row['cashout'] is not None:
                if op!='leave':raise GameError('Du har forladt bordet.')
                return {'ok':True,'cashout':row['cashout'],'waiting':False}
            saved=db.execute('SELECT * FROM poker_tables WHERE id=?',(row['table_id'],)).fetchone()
            table=json.loads(saved['state']);seat=row['seat'];p=table['players'][seat];engine.tick(table)
            if op in ('action','start'):
                revision=payload.get('revision')
                if type(revision) is not int or revision!=table['revision']:
                    # A retry returns the current state without applying twice.
                    db.execute('UPDATE poker_tables SET state=? WHERE id=?',(json.dumps(table),saved['id']))
                    return {'ok':True,'view':engine.public(table,seat),'stale':True}
                if op=='start':
                    if not p['host']:raise GameError('Kun værten kan starte en hånd.')
                    engine.start(table)
                else:engine.act(table,seat,payload.get('action'),payload.get('amount'))
            elif op=='leave':
                p['withdrawing']=True
                if table['stage'] not in ('waiting','finished') and p.get('in_hand') and not p.get('folded'):
                    p['folded']=True;table['revision']+=1;engine.advance(table)
                if table['stage'] not in ('waiting','finished') and p.get('in_hand'):
                    db.execute('UPDATE poker_tables SET state=? WHERE id=?',(json.dumps(table),saved['id']))
                    return {'ok':True,'waiting':True,'view':engine.public(table,seat)}
                amount=p['stack'];p.update(left=True,stack=0);table['revision']+=1
                if p['host']:
                    p['host']=False
                    successor=next((other for other in table['players'] if not other.get('left')),None)
                    if successor:successor['host']=True
                db.execute('UPDATE poker_members SET cashout=? WHERE token_hash=?',(amount,digest(token)))
                db.execute('UPDATE poker_tables SET state=? WHERE id=?',(json.dumps(table),saved['id']))
                return {'ok':True,'waiting':False,'cashout':amount}
            elif op!='view':raise GameError('Ugyldig pokerhandling.')
            db.execute('UPDATE poker_tables SET state=? WHERE id=?',(json.dumps(table),saved['id']))
            return {'ok':True,'view':engine.public(table,seat)}

    def call(target,payload,uid):
        if target=='local':
            result=host(payload,uid)
        else:
            target=address(target)
            try:
                response=requests.post(target+'/api/poker/peer',json=payload,timeout=(3,8),allow_redirects=False)
                if response.is_redirect or response.status_code>=500:raise requests.RequestException()
                if len(response.content)>65536:raise requests.RequestException()
                result=response.json()
                if not response.ok:raise GameError('Værten afviste forbindelsen: '+str(result.get('error','ukendt fejl'))[:200])
            except (requests.RequestException,ValueError):raise GameError('Værten svarer ikke. Dit indskud er gemt; prøv igen uden at betale igen.') from None
        if not isinstance(result,dict) or result.get('ok') is not True:raise GameError('Værten svarede med et ukendt format.')
        return result

    def current(uid):
        with connect(path) as db:return db.execute("SELECT * FROM poker_escrow WHERE user_id=? AND status!='settled'",(uid,)).fetchone()

    def sync(uid,op='view',extra=None):
        entry=current(uid)
        if not entry:return {'connected':False}
        data=json.loads(entry['connection'])
        if entry['status']=='pending':
            result=call(data['url'],{'op':'join','token':data['code'],'join_id':entry['id'],'name':data['name'],'buyin':1000},uid)
            token=result.get('token')
            if not isinstance(token,str) or not 20<=len(token)<=100:raise GameError('Værten gav ikke en gyldig spilleradgang.')
            data['token']=token
            with connect(path) as db:
                db.execute("UPDATE poker_escrow SET connection=?,status=? WHERE id=? AND status='pending'",(json.dumps(data),'leaving' if result.get('rejected') or op=='leave' else 'active',entry['id']))
                entry=db.execute('SELECT * FROM poker_escrow WHERE id=?',(entry['id'],)).fetchone()
            if entry['status']=='settled':return {'connected':False}
        if entry['status']=='leaving':op='leave'
        result=call(data['url'],{'op':op,'token':data['token'],**(extra or {})},uid)
        if op=='leave' and not result.get('waiting'):
            amount=require_int(result.get('cashout'),0,1000000)
            with connect(path) as db:
                db.execute('BEGIN IMMEDIATE')
                changed=db.execute("UPDATE poker_escrow SET status='settled' WHERE id=? AND status!='settled'",(entry['id'],)).rowcount
                if changed:credit(db,uid,amount,'poker_cashout','Poker · jetoner tilbage på saldoen')
            return {'connected':False,'returned':amount}
        view=result.get('view')
        return {'connected':True,'view':view,'leaving':op=='leave','stale':result.get('stale',False),
                'invite_code':data['code'] if isinstance(view,dict) and view.get('host') and data['url']=='local' else None}

    @app.post('/api/poker/peer')
    def poker_peer():
        return jsonify(host(request.get_json(silent=True)))

    @app.post('/api/poker/create')
    def poker_create():
        if current(g.user['id']):raise GameError('Forlad eller hent dit eksisterende pokerbord først.')
        token=secrets.token_urlsafe(32);ident=secrets.token_hex(16)
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            open_tables=db.execute('SELECT state FROM poker_tables WHERE owner=?',(g.user['id'],)).fetchall()
            if any(any(not p.get('left') for p in json.loads(r['state'])['players']) for r in open_tables):raise GameError('Forlad dit eksisterende bord først.')
            table={'players':[],'stage':'waiting','revision':0,'board':[],'dealer':-1,'turn':None}
            db.execute('INSERT INTO poker_tables VALUES(?,?,?,?)',(ident,g.user['id'],digest(token),json.dumps(table)))
        return jsonify(code=token)

    @app.post('/api/poker/connect')
    def poker_connect():
        payload=request.get_json(silent=True) or {}
        code=payload.get('code');target=payload.get('url')
        if not isinstance(code,str) or not 20<=len(code)<=100:raise GameError('Indsæt en gyldig vennekode.')
        if target!='local':target=address(target)
        uid=g.user['id']
        if current(uid):return jsonify(sync(uid))
        probe=call(target,{'op':'probe','token':code},uid)
        if probe.get('protocol')!='fjordcasino-poker-v1':raise GameError('Adressen er ikke et kompatibelt FjordCasino-bord.')
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute("SELECT * FROM poker_escrow WHERE user_id=? AND status!='settled'",(uid,)).fetchone()
            if old:
                previous=json.loads(old['connection'])
                if previous['url']!=target or previous['code']!=code:raise GameError('Du har allerede et indskud ved et andet bord. Hent eller afslut det først.')
            else:
                if target=='local' and not db.execute('SELECT 1 FROM poker_tables WHERE invite_hash=?',(digest(code),)).fetchone():raise GameError('Vennekoden findes ikke her.')
                credit(db,uid,-1000,'poker_buyin','Poker · 1.000 mønter reserveret')
                db.execute('INSERT INTO poker_escrow VALUES(?,?,?,?)',(secrets.token_hex(16),uid,'pending',json.dumps({'url':target,'code':code,'name':g.user['username']})))
        return jsonify(sync(uid))

    @app.get('/api/poker/state')
    def poker_state():return jsonify(sync(g.user['id']))

    @app.post('/api/poker/action')
    def poker_action():
        body=request.get_json(silent=True) or {};op=body.get('op')
        if op not in ('action','start','leave'):raise GameError('Ugyldig pokerhandling.')
        if op=='leave':
            with connect(path) as db:db.execute("UPDATE poker_escrow SET status='leaving' WHERE user_id=? AND status='active'",(g.user['id'],))
        return jsonify(sync(g.user['id'],op,{key:body[key] for key in ('action','amount','revision') if key in body}))
