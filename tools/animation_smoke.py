"""Real-browser regression checks for paced, labelled Jass card playback."""
from __future__ import annotations

from browser_smoke import Browser, main


OBSERVER = """(() => {
  window.__animationRecords = [];
  window.__fourCardIntervals = [];
  window.__animationFinishedAt = null;
  let previousCard = null, completeBoard = null, started = false;
  const capture = () => {
    const table = document.querySelector('.game-table');
    const animating = table?.dataset.animating === 'true';
    if (animating) started = true;
    if (started && table && !animating && window.__animationFinishedAt === null)
      window.__animationFinishedAt = performance.now();
    const cards = [...document.querySelectorAll('.game-table .trick-card')];
    const signature = cards.length === 4 ? cards.map(c => c.dataset.seat+':'+c.dataset.card).join('|') : null;
    if (signature !== completeBoard?.signature) {
      if (completeBoard) completeBoard.end = performance.now();
      completeBoard = signature ? {signature, start:performance.now(), end:null} : null;
      if (completeBoard) window.__fourCardIntervals.push(completeBoard);
    }
    const card = document.querySelector('.game-table .trick-card.card-arriving');
    if (!card) return;
    const key = card.dataset.seat+':'+card.dataset.card;
    if (key === previousCard) return;
    previousCard = key;
    window.__animationRecords.push({
      seat:Number(card.dataset.seat), card:card.dataset.card,
      name:card.querySelector('.trick-player-name')?.textContent?.trim(),
      status:document.querySelector('.playback-status')?.textContent?.trim(),
      time:performance.now(), animating,
      controlsLocked:!document.querySelector('.hand-card:not(:disabled)')
    });
  };
  new MutationObserver(capture).observe(document.querySelector('#main'), {
    childList:true, subtree:true, attributes:true
  });
  capture();
})()"""


def play_stream(game):
    return [card for trick in game["trick_history"] for card in trick["cards"]] + game["trick"]


def prepare_room(browser: Browser, page, base):
    browser.navigate(page, base)
    room = browser.api(page, "/api/rooms", {
        "name": "Animazioni", "player_name": "Anna", "mode": "solo",
        "rules": {"max_hands": 1, "weis": False, "stock": False,
                  "match_bonus": False, "bot_difficulty": "easy"},
    })
    url = base + "/room/" + room["code"]
    browser.navigate(page, url)
    browser.evaluate(page, "document.querySelector('.contract-button[data-contract=H]').click()")
    browser.wait(page, "!!document.querySelector('.hand-card:not(:disabled)')")
    return room["code"], url


def check_sequence(browser: Browser, page, code, reduced_motion=False):
    before = browser.api(page, "/api/rooms/" + code)
    baseline = len(play_stream(before["game"]))
    browser.evaluate(page, OBSERVER)
    browser.evaluate(page, "document.querySelector('.hand-card:not(:disabled)').click()")
    browser.wait(page, "document.querySelector('.game-table')?.dataset.animating === 'true'")
    assert not browser.evaluate(page, "!!document.querySelector('.hand-card:not(:disabled)')"), "Cards remain playable during bot playback"
    final = browser.api(page, "/api/rooms/" + code)
    expected = play_stream(final["game"])[baseline:]
    # A human lead is followed by at least all three bot responses.
    assert len(expected) >= 4, expected
    if not reduced_motion:
        browser.wait(page, "document.querySelectorAll('.game-table .trick-card').length === 4", timeout=15)
        browser.screenshot(page, "bot-playback-desktop.png")
    browser.wait(page, "window.__animationFinishedAt !== null", timeout=25)
    records = browser.evaluate(page, "window.__animationRecords")
    actual = [{"seat": item["seat"], "card": item["card"]} for item in records]
    assert actual == expected, {"expected": expected, "actual": actual}
    names = {player["seat"]: player["name"] for player in final["players"]}
    bots = {player["seat"] for player in final["players"] if player["bot"]}
    finished = browser.evaluate(page, "window.__animationFinishedAt")
    for index, item in enumerate(records):
        assert item["name"] == names[item["seat"]], item
        assert item["animating"] and item["controlsLocked"], item
        assert item["status"] and item["name"] in item["status"], item
        if item["seat"] in bots:
            next_time = records[index + 1]["time"] if index + 1 < len(records) else finished
            assert next_time - item["time"] >= 1800, {"reduced_motion": reduced_motion, "frame": item, "duration": next_time-item["time"]}
    complete_tricks = browser.evaluate(page, "window.__fourCardIntervals")
    assert complete_tricks, "Completed trick was never visible"
    assert any(item["end"] and item["end"] - item["start"] >= 1800 for item in complete_tricks), complete_tricks
    if final["game"]["phase"] == "play":
        assert browser.evaluate(page, "!!document.querySelector('.hand-card:not(:disabled)')")
    assert not browser.evaluate(page, "!!document.querySelector('.trick-card.card-arriving')"), "Entry animation remains after playback"


def run_animation_checks(browser: Browser, base):
    page = browser.page()
    browser.call("Emulation.setDeviceMetricsOverride", {
        "width": 1440, "height": 1050, "deviceScaleFactor": 1, "mobile": False,
    }, page)
    code, url = prepare_room(browser, page, base)
    check_sequence(browser, page, code)
    # Reload resumes the current board immediately, without replaying past cards.
    browser.evaluate(page, "document.documentElement.dataset.animationRefreshProbe = 'pending'")
    browser.call("Page.reload", session=page)
    browser.wait(page, "!document.documentElement.dataset.animationRefreshProbe && document.readyState === 'complete' && !!document.querySelector('.game-table')")
    assert browser.evaluate(page, "document.querySelector('.game-table')?.dataset.animating === 'false'")
    assert not browser.evaluate(page, "!!document.querySelector('.trick-card.card-arriving')")

    # Navigation must cancel pending frames, including an active bot animation.
    browser.evaluate(page, "document.querySelector('.hand-card:not(:disabled)').click()")
    browser.wait(page, "document.querySelector('.game-table')?.dataset.animating === 'true'")
    browser.evaluate(page, "document.querySelector('.main-nav [data-nav=home]').click()")
    browser.wait(page, "!!document.querySelector('.hero')")
    browser.evaluate(page, "new Promise(resolve => setTimeout(resolve, 2500))")
    assert browser.evaluate(page, "location.pathname === '/' && !!document.querySelector('.hero') && !document.querySelector('.game-table')")

    # Accessibility removes card travel while retaining time to read each play.
    reduced = browser.page()
    browser.call("Emulation.setEmulatedMedia", {"features": [
        {"name": "prefers-reduced-motion", "value": "reduce"},
    ]}, reduced)
    reduced_code, _ = prepare_room(browser, reduced, base)
    check_sequence(browser, reduced, reduced_code, reduced_motion=True)
    assert not browser.errors, browser.errors
    print("Animation checks passed: complete ordered playback, player labels, two-second bot pacing, held four-card tricks, locked controls, immediate resume, navigation cancellation and reduced motion.")


if __name__ == "__main__":
    main(run_animation_checks)
