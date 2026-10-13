"""Real Chromium UI against an isolated local server; no real accounts/services."""
import sys
from pathlib import Path
import tempfile
import threading

from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app

root=Path(__file__).resolve().parents[1]
out=root/'test-results';out.mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(prefix='fjordcasino-browser-') as data:
    app=create_app({'TESTING':True,'AUTH_MODE':'local','DATA_DIR':data})
    server=make_server('127.0.0.1',0,app,threaded=True)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch()
            errors=[]
            for width in (1440,390):
                page=browser.new_page(viewport={'width':width,'height':1000},reduced_motion='reduce')
                page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(f'http://127.0.0.1:{server.server_port}/login')
                page.get_by_label('Brugernavn').fill('Browser'+str(width))
                page.get_by_label('Adgangskode').fill('synthetic-browser-password')
                page.get_by_role('button',name='Opret en spiller').click()
                expect(page.locator('#balance')).to_have_text('50.000')
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                page.screenshot(path=str(out/f'lobby-{width}.png'),full_page=True)
                for machine in ('duck','cosmic','fruit'):
                    page.locator(f'.game-card[data-open="slot:{machine}"]').click()
                    page.get_by_role('button',name='Drej hjulene').click()
                    expect(page.locator('#game-result')).to_contain_text('indsats')
                    expect(page.get_by_role('button',name='Drej hjulene')).to_be_enabled()
                    if machine=='duck':page.screenshot(path=str(out/f'slots-{width}.png'),full_page=True)
                    page.get_by_role('button',name='Tilbage til lobbyen').click()
                for table in ('classic','duck'):
                    page.locator(f'.game-card[data-open="roulette:{table}"]').click()
                    page.get_by_role('button',name='Grøn (0)',exact=True).click()
                    expect(page.locator('.roulette-board [data-bet="number:0"] .board-badge')).to_have_text('20')
                    page.get_by_role('button',name='Sort',exact=True).click()
                    expect(page.locator('#roulette-slip')).to_contain_text('40 mønter')
                    page.get_by_role('button',name='Ryd bordet').click()
                    page.get_by_role('button',name='Rød',exact=True).click()
                    page.get_by_role('button',name='Drej hjulet').click()
                    expect(page.locator('#game-result')).to_contain_text('Kuglen landede')
                    expect(page.get_by_role('button',name='Drej hjulet')).to_be_enabled()
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    if table=='duck':page.screenshot(path=str(out/f'roulette-{width}.png'),full_page=True)
                    page.get_by_role('button',name='Tilbage til lobbyen').click()
                page.locator('.game-card[data-open="blackjack"]').click()
                page.get_by_role('button',name='Giv kort').click()
                page.wait_for_function("() => document.querySelector('#game-content select') || document.querySelector('.blackjack-actions')")
                expect(page.locator('[data-nav="lobby"]').first).to_be_enabled()
                hand=page.locator('.card-hand').last.inner_text()
                page.reload();expect(page.locator('#balance')).not_to_have_text('—')
                page.locator('.game-card[data-open="blackjack"]').click()
                assert page.locator('.card-hand').last.inner_text()==hand
                if page.get_by_role('button',name='Stå',exact=True).count():
                    page.get_by_role('button',name='Stå',exact=True).click()
                    expect(page.get_by_role('button',name='Giv kort')).to_be_enabled()
                page.screenshot(path=str(out/f'blackjack-{width}.png'),full_page=True)
                page.locator('[data-nav="history"]').click()
                expect(page.locator('#history-rows tr')).not_to_have_count(0)
                # Simulate a lost reply after a committed round, then reload/retry.
                page.locator('[data-nav="lobby"]').first.click()
                page.locator('.game-card[data-open="slot:duck"]').click()
                def lose_reply(route):
                    route.fetch();route.abort()
                page.route('**/api/play/slots',lose_reply,times=1)
                page.get_by_role('button',name='Drej hjulene').click()
                expect(page.get_by_role('button',name='Prøv samme runde igen')).to_be_visible()
                page.reload();expect(page.get_by_role('button',name='Prøv samme runde igen')).to_be_visible()
                before=page.request.get(f'http://127.0.0.1:{server.server_port}/api/state').json()['stats']['rounds']
                page.get_by_role('button',name='Prøv samme runde igen').click()
                expect(page.locator('#history-view')).to_be_visible()
                after=page.request.get(f'http://127.0.0.1:{server.server_port}/api/state').json()['stats']['rounds']
                assert before==after
                page.locator('#account-button').click();page.get_by_role('button',name='Log ud',exact=True).last.click()
                page.wait_for_url('**/login');page.close()
            assert not errors,errors
            browser.close()
        print('PASS: six games, mobile/desktop, persisted blackjack, lost-response recovery, logout, no page errors')
    finally:
        server.shutdown();thread.join(timeout=5);server.server_close()
