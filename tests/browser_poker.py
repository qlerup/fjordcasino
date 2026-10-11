"""Two real installations over TCP with separate Chromium player contexts."""
import sys
from pathlib import Path
import socket
import tempfile
import threading
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server, WSGIRequestHandler
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import create_app


class Quiet(WSGIRequestHandler):
    def log_request(self,*args):pass


root=Path(__file__).resolve().parents[1];out=root/'test-results';out.mkdir(exist_ok=True)
lan=socket.gethostbyname(socket.gethostname())
with tempfile.TemporaryDirectory(prefix='casino-poker-test-') as data:
    servers=[];threads=[]
    try:
        for name in ('host','guest'):
            app=create_app({'TESTING':True,'AUTH_MODE':'local','DATA_DIR':str(Path(data)/name)})
            server=make_server(lan,0,app,threaded=True,request_handler=Quiet);servers.append(server)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();threads.append(thread)
        urls=[f'http://{lan}:{s.server_port}' for s in servers]
        with sync_playwright() as pw:
            browser=pw.chromium.launch();contexts=[];pages=[];errors=[]
            for i,width in enumerate((1440,390)):
                context=browser.new_context(viewport={'width':width,'height':1000});contexts.append(context);page=context.new_page();pages.append(page)
                page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(urls[i]+'/login');page.get_by_label('Brugernavn').fill(['Host','Guest'][i]);page.get_by_label('Adgangskode').fill('fixture-only-password');page.get_by_role('button',name='Opret en spiller').click()
                expect(page.locator('#balance')).to_have_text('10.000')
                page.locator('.sidebar [data-nav="poker"]').click()
                expect(page.get_by_role('button',name='Opret bord')).to_be_visible()
            host,guest=pages
            host.get_by_role('button',name='Opret bord').click();expect(host.locator('#poker-share-code')).to_be_visible()
            invite=host.locator('#poker-share-code').input_value()
            guest.locator('#poker-invite').fill(invite);guest.locator('.poker-connect button').click()
            expect(guest.locator('.poker-seat')).to_have_count(2)
            expect(host.locator('.poker-seat')).to_have_count(2)
            expect(host.locator('#balance')).to_have_text('9.000');expect(guest.locator('#balance')).to_have_text('9.000')
            host.get_by_role('button',name='Start næste hånd').click()
            expect(host.locator('.poker-felt')).to_contain_text('Før floppet')
            for _ in range(20):
                view=host.request.get(urls[0]+'/api/poker/state').json()['view']
                if view['stage']=='finished':break
                actor=host if view['turn']==view['seat'] else guest
                action=actor.get_by_role('button',name='Check',exact=True).or_(actor.get_by_role('button',name='Kald',exact=False))
                expect(action).to_be_visible(timeout=10000);action.click()
                expect(actor.locator('.poker-felt')).to_be_visible()
                # Wait until the committed revision advances before another action.
                actor.wait_for_function('r=>pokerData?.view?.revision>r',arg=view['revision'])
            expect(host.locator('.poker-felt')).to_contain_text('Hånden er afsluttet',timeout=10000)
            expect(guest.locator('.poker-felt')).to_contain_text('Hånden er afsluttet',timeout=10000)
            for i,page in enumerate(pages):
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                page.screenshot(path=str(out/f'poker-{[1440,390][i]}.png'),full_page=True)
                page.get_by_role('button',name='Forlad bordet').click();expect(page.get_by_role('button',name='Opret bord')).to_be_visible()
            balances=[p.request.get(url+'/api/state').json()['user']['balance'] for p,url in zip(pages,urls)]
            assert sum(balances)==20000
            assert not errors,errors
            for context in contexts:context.close()
            browser.close()
        print('PASS two independent servers over LAN TCP, shared invite, full hand, own wallets, 1440/390px, cashout and total conservation')
    finally:
        for server in servers:server.shutdown();server.server_close()
        for thread in threads:thread.join(timeout=5)
