"""Presence failures must be distinguishable from a hidden/inactive tab."""
import sys
import tempfile
import threading
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import create_app

with tempfile.TemporaryDirectory() as data:
    app=create_app({'TESTING':True,'AUTH_MODE':'local','DATA_DIR':data})
    server=make_server('127.0.0.1',0,app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch()
            for width in (390,1440):
                page=browser.new_page(viewport={'width':width,'height':900})
                page.route('**/api/presence',lambda route:route.fulfill(status=403,
                    json={'error':'Sessionen er udløbet. Genindlæs siden.'}))
                page.goto(f'http://127.0.0.1:{server.server_port}/login')
                page.get_by_label('Brugernavn').fill('Presence'+str(width))
                page.get_by_label('Adgangskode').fill('synthetic-password')
                page.get_by_role('button',name='Opret en spiller').click()
                expect(page.locator('#daily-label')).to_have_text('Optjening afbrudt')
                expect(page.locator('#reward-error')).to_be_visible()
                expect(page.locator('#reward-error')).to_contain_text('Sessionen er udløbet')
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                page.unroute('**/api/presence')
                page.evaluate('() => presence(true)')
                expect(page.locator('#daily-label')).to_contain_text('Næste 500 om')
                expect(page.locator('#reward-error')).to_be_hidden()
                page.close()
            browser.close()
    finally:
        server.shutdown();server.server_close()
print('PASS: presence error is visible on mobile/desktop and clears after recovery')
