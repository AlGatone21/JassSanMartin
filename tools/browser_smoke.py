"""Optional real-browser smoke checks using Chrome/Edge's DevTools protocol.

Run with the project virtual environment after installing requirements-dev.txt.
No browser download, Node.js installation, or webdriver is needed.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from urllib.request import urlopen

import websocket
from werkzeug.serving import WSGIRequestHandler, make_server

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import create_app  # noqa: E402


class QuietHandler(WSGIRequestHandler):
    def log(self, *args, **kwargs):
        pass


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def find_browser():
    candidates = [
        os.environ.get("BROWSER_PATH"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        shutil.which("chromium"), shutil.which("chromium-browser"),
        shutil.which("google-chrome"),
    ]
    return next((p for p in candidates if p and Path(p).is_file()), None)


class Browser:
    def __init__(self, endpoint):
        self.ws = websocket.create_connection(endpoint, timeout=20, suppress_origin=True)
        self.counter = 0
        self.errors = []

    def call(self, method, params=None, session=None):
        self.counter += 1
        message = {"id": self.counter, "method": method, "params": params or {}}
        if session:
            message["sessionId"] = session
        self.ws.send(json.dumps(message))
        while True:
            result = json.loads(self.ws.recv())
            if result.get("method") == "Runtime.exceptionThrown":
                self.errors.append(result["params"]["exceptionDetails"])
            if result.get("id") == message["id"]:
                if "error" in result:
                    raise RuntimeError(result["error"])
                return result.get("result", {})

    def page(self):
        context = self.call("Target.createBrowserContext")["browserContextId"]
        target = self.call("Target.createTarget", {"url": "about:blank", "browserContextId": context})["targetId"]
        session = self.call("Target.attachToTarget", {"targetId": target, "flatten": True})["sessionId"]
        self.call("Runtime.enable", session=session)
        self.call("Page.enable", session=session)
        return session

    def evaluate(self, session, expression):
        result = self.call("Runtime.evaluate", {
            "expression": expression, "awaitPromise": True, "returnByValue": True,
        }, session)
        if "exceptionDetails" in result:
            raise AssertionError(result["exceptionDetails"])
        return result["result"].get("value")

    def wait(self, session, expression, timeout=10):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.evaluate(session, expression):
                return
            time.sleep(.1)
        raise AssertionError(f"Timed out: {expression}")

    def navigate(self, session, url):
        self.call("Page.navigate", {"url": url}, session)
        self.wait(session, "location.href === new URL(" + json.dumps(url) + ").href && document.readyState === 'complete' && !!document.querySelector('#main h1')")

    def fill(self, session, selector, values):
        self.evaluate(session, """(() => {
          const form = document.querySelector(SELECTOR);
          if (!form) throw Error('Form missing');
          for (const [name, value] of Object.entries(VALUES)) {
            const field = form.elements.namedItem(name);
            if (!field) throw Error('Field missing: ' + name);
            if (field.type === 'checkbox') field.checked = value;
            else field.value = value;
            field.dispatchEvent(new Event('input', {bubbles:true}));
            field.dispatchEvent(new Event('change', {bubbles:true}));
          }
        })()""".replace("SELECTOR", json.dumps(selector)).replace("VALUES", json.dumps(values)))

    def submit(self, session, selector):
        self.evaluate(session, "document.querySelector(" + json.dumps(selector) + ").requestSubmit()")

    def api(self, session, path, payload=None):
        expression = """(async () => {
          const s = await (await fetch('/api/session')).json();
          const r = await fetch(PATH, PAYLOAD === null ? {} : {
            method:'POST', headers:{'Content-Type':'application/json','X-CSRF-Token':s.csrf},
            body:JSON.stringify(PAYLOAD)
          });
          const data = await r.json();
          if (!r.ok) throw Error(r.status + ': ' + JSON.stringify(data));
          return data;
        })()""".replace("PATH", json.dumps(path)).replace("PAYLOAD", json.dumps(payload))
        return self.evaluate(session, expression)

    def screenshot(self, session, filename):
        result = self.call("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False}, session)
        (ROOT / "artifacts" / filename).write_bytes(base64.b64decode(result["data"]))


def run_checks(browser, base):
    page = browser.page()
    browser.call("Emulation.setDeviceMetricsOverride", {"width": 1440, "height": 1050, "deviceScaleFactor": 1, "mobile": False}, page)
    browser.navigate(page, base)
    assert browser.evaluate(page, "document.documentElement.lang") == "it"
    browser.screenshot(page, "dashboard-desktop.png")
    browser.evaluate(page, "document.querySelector('[data-lang=de]').click()")
    browser.wait(page, "document.documentElement.lang === 'de'")
    assert "Spielen" in browser.evaluate(page, "document.body.innerText")
    browser.screenshot(page, "dashboard-german.png")
    browser.evaluate(page, "document.querySelector('[data-lang=it]').click()")

    # Use the actual creation form, contract buttons and card-click handler.
    browser.evaluate(page, "document.querySelector('[data-action=new-solo]').click()")
    browser.fill(page, "form[data-form=new-room]", {"player_name": "Anna", "name": "Browser test", "max_hands": 1, "weis": False, "stock": False, "match_bonus": False})
    browser.submit(page, "form[data-form=new-room]")
    browser.wait(page, "!!document.querySelector('.hand-card')")
    room = {"code": browser.evaluate(page, "location.pathname.split('/').pop()")}
    browser.screenshot(page, "game-desktop.png")
    browser.evaluate(page, "document.querySelector('.contract-button[data-contract=H]').click()")
    browser.wait(page, "!!document.querySelector('.hand-card:not(:disabled)')")
    browser.call("Emulation.setDeviceMetricsOverride", {"width": 390, "height": 844, "deviceScaleFactor": 1, "mobile": True}, page)
    browser.screenshot(page, "game-mobile.png")
    assert browser.evaluate(page, "document.documentElement.scrollWidth <= innerWidth")
    browser.evaluate(page, "document.querySelector('.hand-panel').scrollIntoView({block:'center'})")
    browser.screenshot(page, "game-mobile-hand.png")
    browser.evaluate(page, "document.querySelector('.hand-card:not(:disabled)').click()")
    browser.wait(page, "document.querySelectorAll('.hand-card').length === 8")
    browser.wait(page, "document.querySelector('.game-table')?.dataset.animating === 'false'", timeout=25)
    browser.call("Emulation.setDeviceMetricsOverride", {"width": 1440, "height": 1050, "deviceScaleFactor": 1, "mobile": False}, page)
    state = browser.api(page, "/api/rooms/" + room["code"])
    for _ in range(60):
        game = state["game"]
        if game["phase"] == "finished":
            break
        action = {"type": "contract", "contract": "H"} if game["phase"] == "contract" else {"type": "play", "card": game["legal_cards"][0]}
        state = browser.api(page, "/api/rooms/" + room["code"] + "/action", action)
    assert state["game"]["phase"] == "finished"
    assert sum(state["game"]["scores"]) == 157

    browser.navigate(page, base)
    browser.evaluate(page, "document.querySelector('[data-action=new-match]').click()")
    browser.fill(page, "form[data-form=new-match]", {"name": "Serata ASS", "team_a": "Soazza", "team_b": "Mesocco"})
    browser.submit(page, "form[data-form=new-match]")
    browser.wait(page, "!!document.querySelector('form[data-form=score-round]')")
    match = {"id": browser.evaluate(page, "location.pathname.split('/').pop()")}
    browser.fill(page, "form[data-form=score-round]", {"points_a": 100, "bonus_a": 20, "multiplier": 2})
    assert browser.evaluate(page, "document.querySelector('[name=points_b]').value") == "57"
    assert browser.evaluate(page, "document.querySelector('#round-preview').textContent") == "240 : 114"
    browser.submit(page, "form[data-form=score-round]")
    browser.wait(page, "document.querySelector('.scoreboard .score')?.textContent === '240'")
    browser.screenshot(page, "score-desktop.png")
    state = browser.api(page, "/api/matches/" + match["id"])
    assert state["totals"] == [240, 114]
    # Reaching the target closes score entry, and undo reopens the sheet.
    browser.fill(page, "form[data-form=score-round]", {"points_a": 157, "bonus_a": 1000})
    browser.submit(page, "form[data-form=score-round]")
    browser.wait(page, "!!document.querySelector('.hand-result') && !document.querySelector('form[data-form=score-round]')")
    browser.evaluate(page, "document.querySelector('[data-action=undo-round]').click()")
    browser.evaluate(page, "document.querySelector('[data-action=confirm-undo]').click()")
    browser.wait(page, "!!document.querySelector('form[data-form=score-round]')")
    assert browser.api(page, "/api/matches/" + match["id"])["totals"] == [240, 114]

    browser.navigate(page, base + "/#tournaments")
    browser.evaluate(page, "document.querySelector('[data-action=new-tournament]').click()")
    browser.fill(page, "form[data-form=new-tournament]", {"name": "Coppa ASS", "format": "knockout", "mode": "physical", "teams": "Soazza\nMesocco\nCama\nGrono\nLostallo"})
    browser.submit(page, "form[data-form=new-tournament]")
    browser.wait(page, "!!document.querySelector('.fixture-card')")
    event = {"id": browser.evaluate(page, "location.pathname.split('/').pop()")}
    browser.fill(page, "form[data-form=fixture-result]", {"score_a": 200, "score_b": 100})
    browser.submit(page, "form[data-form=fixture-result]")
    browser.wait(page, "document.querySelector('.tournament-status')?.textContent.startsWith('1 /')")
    browser.screenshot(page, "tournament-desktop.png")

    # A separate guest can read the score sheet, but cannot edit it.
    guest = browser.page()
    browser.navigate(guest, base + "/score/" + match["id"])
    assert not browser.api(guest, "/api/matches/" + match["id"])["is_owner"]
    assert not browser.evaluate(guest, "!!document.querySelector('form[data-form=score-round]')")

    # Join a shared room from another browser profile through its lobby form.
    shared = browser.api(page, "/api/rooms", {"mode": "multiplayer", "name": "Tavolo condiviso", "player_name": "Anna"})
    browser.navigate(page, base + "/room/" + shared["code"])
    browser.screenshot(page, "lobby-desktop.png")
    browser.navigate(guest, base + "/room/" + shared["code"])
    browser.fill(guest, "form[data-form=join-room]", {"name": "Luca", "seat": 2})
    browser.submit(guest, "form[data-form=join-room]")
    browser.wait(guest, "!document.querySelector('form[data-form=join-room]')")
    browser.evaluate(page, "document.querySelector('[data-action=start-room]').click()")
    browser.wait(page, "!!document.querySelector('.contract-button')")
    browser.wait(guest, "!!document.querySelector('.hand-card')")
    assert browser.api(guest, "/api/rooms/" + shared["code"])["my_seat"] == 2

    browser.call("Emulation.setDeviceMetricsOverride", {"width": 390, "height": 844, "deviceScaleFactor": 1, "mobile": True}, page)
    browser.navigate(page, base)
    browser.screenshot(page, "dashboard-mobile.png")
    assert browser.evaluate(page, "document.documentElement.scrollWidth <= innerWidth"), "Mobile page overflows horizontally"
    assert not browser.errors, browser.errors
    print("Browser checks passed: IT/DE, creation forms, card/contract clicks, full solo hand, score preview/save, knockout result, shared-room join, guest permissions and mobile layout.")


def main(checks=run_checks):
    executable = find_browser()
    if not executable:
        raise SystemExit("Install Chrome/Edge or set BROWSER_PATH to its executable.")
    (ROOT / "artifacts").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ass-jass-browser-", ignore_cleanup_errors=True) as temporary:
        location = Path(temporary)
        app = create_app({"TESTING": True, "SECRET_KEY": "browser-test-only", "DATABASE_URL": "sqlite:///" + str(location / "test.db"), "SESSION_COOKIE_SECURE": False})
        server = make_server("127.0.0.1", 0, app, threaded=True, request_handler=QuietHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        port = free_port()
        command = [executable, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check", "--remote-debugging-port=" + str(port), "--user-data-dir=" + str(location / "chrome"), "about:blank"]
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        browser = None
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                try:
                    with urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1) as response:
                        endpoint = json.load(response)["webSocketDebuggerUrl"]
                    break
                except OSError:
                    time.sleep(.2)
            else:
                raise RuntimeError("Browser debugging endpoint did not start")
            browser = Browser(endpoint)
            checks(browser, f"http://127.0.0.1:{server.server_port}")
        finally:
            if browser:
                try:
                    browser.call("Browser.close")
                except (websocket.WebSocketException, OSError):
                    pass
                browser.ws.close()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=5)
            server.shutdown()
            app.extensions["store"].engine.dispose()


if __name__ == "__main__":
    main()
