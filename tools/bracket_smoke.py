"""Browser checks for connected elimination brackets and their score controls."""
import json

from browser_smoke import main


def run_bracket_checks(browser, base):
    page = browser.page()
    browser.call("Emulation.setDeviceMetricsOverride", {
        "width": 1440, "height": 1100, "deviceScaleFactor": 1, "mobile": False,
    }, page)
    browser.navigate(page, base)
    created = browser.api(page, "/api/tournaments", {
        "name": "Coppa San Martin", "format": "knockout", "mode": "physical",
        "teams": ["ASS Soazza", "Mesocco", "Cama", "Grono", "Lostallo"],
    })
    endpoint = "/api/tournaments/" + created["id"]
    url = base + "/tournament/" + created["id"]
    browser.navigate(page, url)
    browser.wait(page, "document.querySelectorAll('.bracket-round').length === 3")
    assert browser.evaluate(page, "[...document.querySelectorAll('.bracket-round')].map(r=>r.querySelectorAll('.fixture-card').length)") == [4, 2, 1]
    assert browser.evaluate(page, "[...document.querySelectorAll('.bracket-round-title')].map(r=>r.firstChild.textContent)") == ["Quarti di finale", "Semifinali", "Finale"]
    assert browser.evaluate(page, "document.querySelectorAll('.bracket-connector').length") == 6
    data = browser.api(page, endpoint)
    links = browser.evaluate(page, "[...document.querySelectorAll('.bracket-connector')].map(p=>({source:p.dataset.source,target:p.dataset.target}))")
    expected = [{"source": f[key], "target": f["id"]} for f in data["fixtures"] for key in ("source_a", "source_b") if f[key]]
    assert links == expected
    # Each receiving match must sit halfway between the two source matches.
    for fixture in data["fixtures"]:
        if not fixture["source_a"]:
            continue
        ids = [fixture["source_a"], fixture["source_b"], fixture["id"]]
        positions = browser.evaluate(page, """IDS.map(id=>{
          const r=document.querySelector('[data-fixture-id="'+id+'"]').getBoundingClientRect();
          return r.top+r.height/2;
        })""".replace("IDS", json.dumps(ids)))
        assert abs((positions[0] + positions[1]) / 2 - positions[2]) < 2, positions
    playable = next(f for f in data["fixtures"] if f["round"] == 1 and f["status"] == "pending")
    form = 'form[data-fixture="' + playable["id"] + '"]'
    browser.fill(page, form, {"score_a": 250, "score_b": 120})
    browser.submit(page, form)
    browser.wait(page, "document.querySelector(" + json.dumps('[data-fixture-id="' + playable["id"] + '"] .winner') + ")?.textContent.includes('Grono')")
    assert browser.evaluate(page, "document.querySelectorAll('.bracket-team.winner').length") == 4
    assert "Grono" in browser.evaluate(page, "document.querySelectorAll('.bracket-round')[1].innerText")
    browser.screenshot(page, "bracket-desktop.png")

    browser.evaluate(page, "document.querySelector('[data-lang=de]').click()")
    assert "Turnierbaum" in browser.evaluate(page, "document.querySelector('.section-tabs').innerText")
    assert "Halbfinale" in browser.evaluate(page, "document.querySelector('.tournament-bracket').innerText")
    browser.evaluate(page, "document.querySelector('[data-lang=it]').click()")

    browser.call("Emulation.setDeviceMetricsOverride", {
        "width": 390, "height": 844, "deviceScaleFactor": 1, "mobile": True,
    }, page)
    assert browser.evaluate(page, "document.documentElement.scrollWidth <= innerWidth")
    assert browser.evaluate(page, "document.querySelector('.bracket-scroll').scrollWidth > document.querySelector('.bracket-scroll').clientWidth")
    browser.evaluate(page, "document.querySelector('.bracket-scroll').scrollTo(200,120)")
    position = browser.evaluate(page, "[document.querySelector('.bracket-scroll').scrollLeft,document.querySelector('.bracket-scroll').scrollTop]")
    ready = next(f for f in browser.api(page, endpoint)["fixtures"] if f["round"] == 2 and f["status"] == "pending")
    form = 'form[data-fixture="' + ready["id"] + '"]'
    browser.fill(page, form, {"score_a": 300, "score_b": 100})
    browser.submit(page, form)
    browser.wait(page, "document.querySelector(" + json.dumps('[data-fixture-id="' + ready["id"] + '"] .winner') + ") !== null")
    assert browser.evaluate(page, "[document.querySelector('.bracket-scroll').scrollLeft,document.querySelector('.bracket-scroll').scrollTop]") == position
    browser.evaluate(page, "document.querySelector('.bracket-scroll').scrollTo(0,0)")
    browser.screenshot(page, "bracket-mobile.png")

    # Progress through the remaining matches and display the eventual champion.
    while True:
        data = browser.api(page, endpoint)
        pending = next((f for f in data["fixtures"] if f["status"] == "pending"), None)
        if not pending:
            break
        browser.api(page, endpoint + "/results", {"fixture_id": pending["id"], "score_a": 200, "score_b": 100})
    browser.navigate(page, url)
    browser.wait(page, "!!document.querySelector('.bracket-champion')")
    assert data["fixtures"][-1]["winner"] in browser.evaluate(page, "document.querySelector('.bracket-champion').innerText")
    viewer = browser.page()
    browser.navigate(viewer, url)
    assert not browser.evaluate(viewer, "!!document.querySelector('form[data-form=fixture-result]')")
    assert browser.evaluate(viewer, "!!document.querySelector('.tournament-bracket')")

    # A two-team digital final retains its room action, and large brackets fit.
    for count in (2, 32):
        event = browser.api(page, "/api/tournaments", {"name": "Digital", "format": "knockout", "mode": "digital", "teams": [f"Team {i+1}" for i in range(count)]})
        browser.navigate(page, base + "/tournament/" + event["id"])
        assert browser.evaluate(page, "document.querySelectorAll('.bracket-fixture').length") == (1 if count == 2 else 31)
        assert browser.evaluate(page, "!!document.querySelector('[data-action=fixture-room]')")
        assert browser.evaluate(page, "document.documentElement.scrollWidth <= innerWidth")
    robin = browser.api(page, "/api/tournaments", {"name": "Girone", "format": "round_robin", "mode": "physical", "teams": ["A", "B", "C"]})
    browser.navigate(page, base + "/tournament/" + robin["id"])
    assert browser.evaluate(page, "!!document.querySelector('.fixtures-grid') && !document.querySelector('.tournament-bracket')")
    assert not browser.errors, browser.errors
    print("Bracket checks passed: connected rounds, byes, geometry, score entry, advancement, champion, IT/DE, mobile scrolling, spectator permissions, digital tables and round robin.")


if __name__ == "__main__":
    main(run_bracket_checks)
