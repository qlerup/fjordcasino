import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests
from flask import Flask, g, jsonify, redirect, render_template, request, session, url_for
from flask.sessions import SecureCookieSessionInterface
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.exceptions import HTTPException

from db import connect, initialize
import games


class CasinoCookies(SecureCookieSessionInterface):
    def get_cookie_secure(self, app):
        return request.is_secure or super().get_cookie_secure(app)


def create_app(config=None):
    app = Flask(__name__)
    app.session_interface = CasinoCookies()
    app.config.update(DATA_DIR=os.getenv('DATA_DIR', str(Path(__file__).parent/'data')),
        AUTH_MODE=os.getenv('AUTH_MODE', 'fjordhub'), FJORDHUB_URL=os.getenv('FJORDHUB_URL',''),
        FJORDHUB_API_KEY=os.getenv('FJORDHUB_API_KEY',''), TZ=os.getenv('TZ','Europe/Copenhagen'),
        SESSION_COOKIE_NAME='fjordcasino_session', SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax', PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
        MAX_CONTENT_LENGTH=16384)
    if config: app.config.update(config)
    if app.config['AUTH_MODE'] not in ('local','fjordhub'):
        raise RuntimeError('AUTH_MODE must be local or fjordhub')
    managed = app.config['AUTH_MODE'] == 'fjordhub'
    if managed and not (app.config['FJORDHUB_URL'] and app.config['FJORDHUB_API_KEY']):
        raise RuntimeError('FjordHub URL and API key are required')
    # FjordHub's reverse proxy sets this header; forwarded hosts are never trusted.
    if managed: app.wsgi_app = ProxyFix(app.wsgi_app, x_for=0, x_proto=1, x_host=0)
    data = Path(app.config['DATA_DIR']); data.mkdir(parents=True, exist_ok=True)
    key = data/'session.key'
    try:
        fd = os.open(key, os.O_CREAT|os.O_EXCL|os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'wb') as stream: stream.write(secrets.token_bytes(32))
    except FileExistsError:
        pass
    for _ in range(20):
        app.secret_key = key.read_bytes()
        if len(app.secret_key) >= 32: break
        time.sleep(.05)
    if len(app.secret_key) < 32: raise RuntimeError('Invalid session key')
    path = data/'casino.sqlite3'; initialize(path)
    app.extensions['db_path'] = path
    zone = ZoneInfo(app.config['TZ'])
    clock = app.config.get('CLOCK') or (lambda: datetime.now(timezone.utc))

    def stamp(): return clock().isoformat()

    def hub_api(endpoint, payload=None, method='GET'):
        try:
            params = {'app_id':'fjordcasino', **(payload or {})}
            response = requests.request(method, app.config['FJORDHUB_URL'].rstrip('/')+endpoint,
                headers={'X-Hub-Key':app.config['FJORDHUB_API_KEY']}, timeout=(3,6), allow_redirects=False,
                **({'params':params} if method == 'GET' else {'json':params}))
            if response.status_code >= 500: raise requests.RequestException()
            return response.json() if response.ok else {'ok':False}
        except (requests.RequestException, ValueError):
            raise games.GameError('FjordHub kunne ikke kontaktes. Prøv igen om lidt.') from None
    app.extensions['hub_api'] = hub_api

    def credit(db, uid, amount, kind, description):
        row = db.execute('SELECT balance FROM users WHERE id=?', (uid,)).fetchone()
        balance = row['balance'] + amount
        if balance < 0: raise games.GameError('Du har ikke mønter nok til denne indsats.')
        db.execute('UPDATE users SET balance=? WHERE id=?', (balance,uid))
        db.execute('INSERT INTO ledger(user_id,kind,amount,balance,description,created_at) VALUES(?,?,?,?,?,?)',
                   (uid,kind,amount,balance,description,stamp()))
        return balance

    def daily(db, uid):
        day = clock().astimezone(zone).date().isoformat()
        added = db.execute('INSERT OR IGNORE INTO daily_rewards VALUES(?,?)', (uid,day)).rowcount
        if added: credit(db,uid,1000,'daily','Dagens 1.000 mønter')
        return bool(added)

    def establish(identity, username, password=None):
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT id FROM users WHERE identity=?', (identity,)).fetchone()
            if not row:
                uid = db.execute('INSERT INTO users(identity,username,password,created_at) VALUES(?,?,?,?)',
                                 (identity,username,password,stamp())).lastrowid
                credit(db,uid,5000,'welcome','Velkommen til FjordCasino')
            else:
                uid = row['id']; db.execute('UPDATE users SET username=? WHERE id=?', (username,uid))
            daily(db, uid)
        session.clear()
        session.update(uid=uid, csrf=secrets.token_urlsafe(32), login_at=time.time())
        session.permanent = True

    def establish_hub(user):
        if not isinstance(user, dict) or type(user.get('id')) is not int or user['id'] <= 0 or user.get('must_change_password'):
            return False
        users = hub_api('/api/hub/apps/users')
        confirmed = next((u for u in users.get('items',[]) if u.get('id') == user['id'] and not u.get('must_change_password')), None)
        if not users.get('ok') or not confirmed: return False
        establish('hub:'+str(user['id']), str(confirmed.get('username','Spiller'))[:100])
        session['hub_checked'] = time.time()
        return True

    @app.before_request
    def protect():
        if request.endpoint in ('health','static'): return
        session.setdefault('csrf',secrets.token_urlsafe(32))
        if request.method in ('POST','PUT','PATCH','DELETE'):
            token = request.form.get('csrf','') if request.endpoint == 'login' else request.headers.get('X-CSRF-Token','')
            if not secrets.compare_digest(session['csrf'].encode(),token.encode()):
                return jsonify(error='Sessionen er udløbet. Genindlæs siden.'), 403
            origin = request.headers.get('Origin')
            if origin and origin != request.host_url.rstrip('/'):
                return jsonify(error='Forespørgslen skal komme fra FjordCasino.'), 403
        if request.endpoint in ('health','static','login','hub_login'): return
        with connect(path) as db:
            g.user = db.execute('SELECT id,identity,username,balance FROM users WHERE id=?', (session.get('uid'),)).fetchone()
        if g.user and time.time()-session.get('login_at',0) < 43200:
            if managed and time.time()-session.get('hub_checked',0) > 60:
                result = hub_api('/api/hub/apps/users')
                if not result.get('ok'):
                    return jsonify(error='FjordHub kunne ikke bekræfte din adgang.'), 503
                uid = int(g.user['identity'].split(':')[1])
                if not any(u.get('id') == uid and not u.get('must_change_password') for u in result.get('items',[])):
                    g.user = None; session.clear()
                else: session['hub_checked'] = time.time()
            if g.user: return
        session.pop('uid',None)
        if request.path.startswith('/api/'):
            return jsonify(error='Log ind for at spille.', authenticated=False), 401
        return redirect(url_for('login'))

    @app.after_request
    def headers(response):
        response.headers['Cache-Control'] = 'no-store' if request.endpoint != 'static' else 'public, max-age=3600'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer' if request.endpoint == 'hub_login' else 'same-origin'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'self'; base-uri 'self'; form-action 'self'"
        return response

    @app.errorhandler(games.GameError)
    def game_error(error): return jsonify(error=str(error)), 400

    @app.errorhandler(HTTPException)
    def http_error(error): return jsonify(error=error.description), error.code

    @app.errorhandler(Exception)
    def unexpected(error):
        app.logger.exception('Request failed')
        return jsonify(error='Der opstod en fejl. Din gemte saldo er bevaret. Genindlæs siden.'), 500

    @app.route('/login', methods=['GET','POST'])
    def login():
        error = None
        if request.method == 'POST':
            username = request.form.get('username','').strip()[:100]
            password = request.form.get('password','')[:1024]
            address = request.remote_addr or 'unknown'
            with connect(path) as db:
                db.execute('BEGIN IMMEDIATE')
                db.execute('DELETE FROM login_attempts WHERE at<?', (time.time()-300,))
                if db.execute('SELECT count(*) FROM login_attempts WHERE address=?',(address,)).fetchone()[0] >= 10:
                    return render_template('login.html', managed=managed,error='Vent fem minutter før du prøver igen.'),429
                db.execute('INSERT INTO login_attempts VALUES(?,?)',(address,time.time()))
            try:
                if managed:
                    result = hub_api('/api/hub/apps/authenticate', {'username':username,'password':password},'POST')
                    if result.get('ok') and establish_hub(result.get('user')): return redirect('/')
                else:
                    identity = 'local:'+username.casefold()
                    with connect(path) as db:
                        user = db.execute('SELECT * FROM users WHERE identity=?',(identity,)).fetchone()
                    if request.form.get('mode') == 'register':
                        if user or not re.fullmatch(r'[\w .-]{2,40}',username) or len(password) < 10:
                            error = 'Vælg et ledigt navn på 2–40 tegn og en adgangskode på mindst 10 tegn.'
                        else:
                            # Serialize registration to avoid replacing a racing account.
                            with connect(path) as db:
                                db.execute('BEGIN IMMEDIATE')
                                cursor = db.execute('INSERT OR IGNORE INTO users(identity,username,password,created_at) VALUES(?,?,?,?)',
                                    (identity,username,generate_password_hash(password),stamp()))
                                if not cursor.rowcount: raise games.GameError('Brugernavnet er optaget.')
                                credit(db,cursor.lastrowid,5000,'welcome','Velkommen til FjordCasino')
                            establish(identity,username); return redirect('/')
                    elif user and user['password'] and check_password_hash(user['password'],password):
                        establish(identity,user['username']); return redirect('/')
                error = error or 'Login afvist. Kontrollér navn, adgangskode og adgang i FjordHub.'
            except games.GameError as exc: error = str(exc)
        return render_template('login.html', error=error, managed=managed)

    @app.get('/hub-login')
    def hub_login():
        token = request.args.get('token','')
        if managed and 0 < len(token) <= 512:
            result = hub_api('/api/hub/sso-verify',{'token':token})
            if result.get('ok') and establish_hub(result): return redirect('/')
        return redirect('/login')

    @app.post('/api/logout')
    def logout():
        session.clear(); return jsonify(ok=True)

    @app.get('/api/auth/hub-access')
    def access(): return jsonify(authenticated=True)

    @app.get('/api/health')
    def health():
        with connect(path) as db: db.execute('SELECT 1 FROM users LIMIT 1')
        return jsonify(ok=True,app='fjordcasino',version='1.0.0')

    @app.get('/')
    def index(): return render_template('index.html', username=g.user['username'])

    @app.get('/api/state')
    def state():
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            awarded = daily(db,g.user['id'])
            user = dict(db.execute('SELECT id,username,balance FROM users WHERE id=?',(g.user['id'],)).fetchone())
            history = [dict(row) for row in db.execute('SELECT kind,amount,balance,description,created_at FROM ledger WHERE user_id=? ORDER BY id DESC LIMIT 50',(g.user['id'],))]
            row = db.execute('SELECT state FROM blackjack WHERE user_id=?',(g.user['id'],)).fetchone()
            stats = dict(db.execute("SELECT count(CASE WHEN kind='bet' THEN 1 END) AS rounds, coalesce(sum(CASE WHEN kind='payout' THEN amount ELSE 0 END),0) AS won, coalesce(max(CASE WHEN kind='payout' THEN amount ELSE 0 END),0) AS biggest FROM ledger WHERE user_id=?",(g.user['id'],)).fetchone())
        now = clock().astimezone(zone)
        tomorrow = datetime.combine(now.date()+timedelta(days=1),datetime.min.time(),tzinfo=zone)
        return jsonify(user=user, history=history, stats=stats, daily={'amount':1000,'awarded':awarded,'next_at':tomorrow.isoformat()},
                       blackjack=games.public_blackjack(json.loads(row['state'])) if row else None)

    @app.post('/api/play/<game>')
    def play(game):
        body = request.get_json(silent=True)
        if not isinstance(body,dict): raise games.GameError('Ugyldig forespørgsel.')
        request_id = body.pop('request_id', '')
        if not isinstance(request_id,str) or not re.fullmatch(r'[a-zA-Z0-9-]{16,80}',request_id):
            raise games.GameError('Ugyldigt runde-id. Genindlæs siden.')
        fingerprint = hashlib.sha256(json.dumps([game,body],sort_keys=True).encode()).hexdigest()
        uid = g.user['id']
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            previous = db.execute('SELECT * FROM actions WHERE user_id=? AND request_id=?',(uid,request_id)).fetchone()
            if previous:
                if previous['fingerprint'] != fingerprint:
                    return jsonify(error='Dette runde-id er allerede brugt.'),409
                return jsonify(json.loads(previous['response']))
            daily(db,uid)
            if game == 'slots':
                result = games.spin_slots(body.get('machine'),body.get('bet'))
                name = games.SLOTS[body['machine']]['name']
                credit(db,uid,-result['bet'],'bet',name)
                if result['payout']: credit(db,uid,result['payout'],'payout',name)
            elif game == 'roulette':
                result = games.spin_roulette(body.get('table'),body.get('bets'))
                name = 'Anderoulette' if body['table']=='duck' else 'Roulette Royale'
                credit(db,uid,-result['bet'],'bet',name)
                if result['payout']: credit(db,uid,result['payout'],'payout',name)
            elif game == 'blackjack':
                row = db.execute('SELECT state FROM blackjack WHERE user_id=?',(uid,)).fetchone()
                current = json.loads(row['state']) if row else None
                if body.get('action') == 'start':
                    if current and current['status']=='playing': raise games.GameError('Afslut din nuværende hånd først.')
                    current = games.start_blackjack(body.get('bet'))
                    credit(db,uid,-current['bet'],'bet','Blackjack · ny hånd')
                else:
                    if not current or body.get('round_id') != current['round_id']:
                        raise games.GameError('Hånden er ændret. Genindlæs bordet.')
                    if body.get('action')=='double': credit(db,uid,-current['bet'],'double','Blackjack · fordobling')
                    current = games.act_blackjack(current,body.get('action'))
                if current['status']=='finished' and current['payout']:
                    credit(db,uid,current['payout'],'payout','Blackjack · '+current['result'])
                db.execute('INSERT OR REPLACE INTO blackjack VALUES(?,?)',(uid,json.dumps(current)))
                result = games.public_blackjack(current)
            else: raise games.GameError('Spillet findes ikke.')
            result['balance'] = db.execute('SELECT balance FROM users WHERE id=?',(uid,)).fetchone()[0]
            db.execute('INSERT INTO actions VALUES(?,?,?,?,?)',(uid,request_id,fingerprint,json.dumps(result),stamp()))
        return jsonify(result)

    return app


if __name__ == '__main__':
    create_app().run(host='127.0.0.1',port=int(os.getenv('APP_PORT','8070')))
