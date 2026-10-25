import json

import pytest

from app import create_app


@pytest.fixture
def app(tmp_path):
    application = create_app({"TESTING": True, "SECRET_KEY": "test-key-only",
                              "DATABASE_URL": "sqlite:///" + str(tmp_path / "test.sqlite")})
    yield application
    application.extensions["store"].engine.dispose()


@pytest.fixture
def client(app):
    return app.test_client()


def token(client):
    return client.get("/api/session").get_json()["csrf"]


def post(client, url, payload=None):
    return client.post(url, json=payload or {}, headers={"X-CSRF-Token": token(client)})


def create_match(client, **options):
    response = post(client, "/api/matches", {"name": "Test", "team_a": "Soazza", "team_b": "Mesocco", **options})
    assert response.status_code == 201, response.get_json()
    return response.get_json()["id"]


def create_tournament(client, **options):
    response = post(client, "/api/tournaments", {"name": "Coppa ASS", "teams": ["A", "B", "C", "D"], **options})
    assert response.status_code == 201, response.get_json()
    return response.get_json()["id"]


def test_health_and_csrf(client):
    assert client.get("/health").get_json() == {"status": "ok"}
    assert client.post("/api/matches", json={}).status_code == 403
    assert post(client, "/api/profile", {"name": "Alessio"}).status_code == 200
    assert client.get("/api/session").get_json()["name"] == "Alessio"


def test_physical_scores_validate_and_undo(client):
    match_id = create_match(client)
    url = f"/api/matches/{match_id}"
    assert post(client, url + "/rounds", {"points_a": 80, "points_b": 80}).status_code == 400
    result = post(client, url + "/rounds", {"points_a": 100, "points_b": 57,
                                             "bonus_a": 20, "bonus_b": 0, "multiplier": 2}).get_json()
    assert result["totals"] == [240, 114]
    assert result["rounds"][0]["total_a"] == 240
    assert post(client, url + "/undo").get_json()["totals"] == [0, 0]
    assert post(client, url + "/undo").status_code == 400


def test_scoring_authorization_and_csv(client, app):
    match_id = create_match(client)
    url = f"/api/matches/{match_id}"
    viewer = app.test_client()
    assert viewer.get(url).get_json()["is_owner"] is False
    assert post(viewer, url + "/rounds", {"points_a": 157}).status_code == 403
    assert post(viewer, url + "/undo").status_code == 403
    result = post(client, url + "/rounds", {"points_a": 157, "note": "=HYPERLINK(1)"})
    assert result.status_code == 200
    export = viewer.get(url + "/export.csv")
    assert export.status_code == 200
    assert "'=HYPERLINK" in export.get_data(as_text=True)
    assert "attachment" in export.headers["Content-Disposition"]


def test_score_sheet_finishes_and_undo_reopens(client):
    match_id = create_match(client, target=100)
    url = f"/api/matches/{match_id}"
    assert post(client, url + "/rounds", {"points_a": 120}).get_json()["winner"] == 0
    assert post(client, url + "/rounds", {"points_a": 157}).status_code == 400
    assert post(client, url + "/undo").get_json()["winner"] is None


def test_solo_room_keeps_opponents_private_and_plays_complete_hand(client, app):
    response = post(client, "/api/rooms", {"mode": "solo", "player_name": "Player", "rules": {"max_hands": 1}})
    assert response.status_code == 201
    code = response.get_json()["code"]
    url = f"/api/rooms/{code}"
    room = client.get(url).get_json()
    assert room["my_seat"] == 0
    assert len(room["game"]["hand"]) == 9
    assert "hands" not in room["game"]
    assert "sid" not in json.dumps(room)
    assert room["game"]["phase"] == "contract"
    viewer = app.test_client()
    public = viewer.get(url).get_json()
    assert public["my_seat"] is None
    assert public["game"]["hand"] == []
    assert post(viewer, url + "/action", {"type": "contract", "contract": "H"}).status_code == 403
    assert post(client, url + "/action", {"type": "play", "card": "invalid"}).status_code == 400
    response = post(client, url + "/action", {"type": "contract", "contract": "H"})
    assert response.status_code == 200, response.get_json()
    for _ in range(12):
        room = response.get_json()
        if room["game"]["phase"] == "finished":
            break
        assert room["game"]["turn"] == 0
        response = post(client, url + "/action", {"type": "play", "card": room["game"]["legal_cards"][0]})
        assert response.status_code == 200, response.get_json()
    assert response.get_json()["game"]["phase"] == "finished"
    assert response.get_json()["status"] == "finished"
    assert len(response.get_json()["game"]["history"]) == 1


def test_lobby_seats_permissions_and_rejoining(client, app):
    code = post(client, "/api/rooms", {"mode": "multiplayer", "player_name": "Host"}).get_json()["code"]
    url = f"/api/rooms/{code}"
    friend = app.test_client()
    assert post(friend, url + "/join", {"name": "Partner", "seat": 2}).get_json()["my_seat"] == 2
    assert post(friend, url + "/join", {"name": "Ignored", "seat": 1}).get_json()["my_seat"] == 2
    assert post(friend, url + "/start", {"fill_bots": True}).status_code == 403
    assert post(client, url + "/start").status_code == 400
    assert post(client, url + "/start", {"fill_bots": True}).status_code == 200
    assert post(app.test_client(), url + "/join", {"name": "Late"}).status_code == 409
    assert post(friend, url + "/action", {"type": "contract", "contract": "H"}).status_code == 400
    assert post(client, url + "/action", {"type": "next_hand"}).status_code == 400


def test_four_independent_players_complete_hand_and_host_controls_deal(client, app):
    players = [client, *(app.test_client() for _ in range(3))]
    code = post(client, "/api/rooms", {"mode": "multiplayer", "rules": {"max_hands": 2}}).get_json()["code"]
    url = f"/api/rooms/{code}"
    for seat in range(1, 4):
        assert post(players[seat], url + "/join", {"name": f"Player {seat}", "seat": seat}).status_code == 200
    assert post(client, url + "/start").status_code == 200
    hands = [p.get(url).get_json()["game"]["hand"] for p in players]
    assert len(set(card for hand in hands for card in hand)) == 36
    response = post(client, url + "/action", {"type": "contract", "contract": "S"})
    assert response.status_code == 200
    assert post(players[1], url + "/action", {"type": "play", "card": hands[1][0]}).status_code == 400
    for _ in range(36):
        current = client.get(url).get_json()["game"]
        active = players[current["turn"]]
        personal = active.get(url).get_json()["game"]
        assert personal["legal_cards"]
        response = post(active, url + "/action", {"type": "play", "card": personal["legal_cards"][0]})
        assert response.status_code == 200, response.get_json()
    room = response.get_json()
    assert room["game"]["phase"] == "hand_end"
    assert room["game"]["hand_counts"] == [0, 0, 0, 0]
    assert post(players[1], url + "/action", {"type": "next_hand"}).status_code == 403
    next_deal = post(client, url + "/action", {"type": "next_hand"})
    assert next_deal.status_code == 200
    assert next_deal.get_json()["game"]["hand_number"] == 2
    assert next_deal.get_json()["game"]["turn"] == 1


def test_overview_excludes_other_users(client, app):
    create_match(client)
    create_tournament(client)
    code = post(client, "/api/rooms", {"mode": "multiplayer"}).get_json()["code"]
    other = app.test_client()
    assert other.get("/api/overview").get_json() == {"rooms": [], "matches": [], "tournaments": []}
    post(other, f"/api/rooms/{code}/join", {"name": "Visitor"})
    own = client.get("/api/overview").get_json()
    assert all(len(own[key]) == 1 for key in ("rooms", "matches", "tournaments"))
    assert len(other.get("/api/overview").get_json()["rooms"]) == 1


def test_overview_includes_actual_match_and_tournament_metadata(client):
    match_id = create_match(client, target=2500)
    post(client, f"/api/matches/{match_id}/rounds", {"points_a": 100})
    create_tournament(client, mode="digital", format="knockout", teams=["Soazza", "Mesocco", "Cama"])
    overview = client.get("/api/overview").get_json()
    match = overview["matches"][0]
    assert match["team_a"] == "Soazza" and match["team_b"] == "Mesocco"
    assert match["target"] == 2500 and match["totals"] == [100, 57]
    assert match["winner"] is None
    tournament = overview["tournaments"][0]
    assert tournament["format"] == "knockout" and tournament["mode"] == "digital"
    assert tournament["teams"] == ["Soazza", "Mesocco", "Cama"]


def test_creating_normal_room_persists_player_profile(client):
    assert post(client, "/api/rooms", {"mode": "multiplayer", "player_name": "Alessio"}).status_code == 201
    assert client.get("/api/session").get_json()["name"] == "Alessio"
    response = post(client, "/api/rooms", {"mode": "multiplayer"})
    code = response.get_json()["code"]
    assert client.get(f"/api/rooms/{code}").get_json()["players"][0]["name"] == "Alessio"


def test_round_robin_all_pairs_and_standings(client, app):
    tournament_id = create_tournament(client, teams=["A", "B", "C", "D", "E"])
    url = f"/api/tournaments/{tournament_id}"
    tournament = client.get(url).get_json()
    assert len(tournament["fixtures"]) == 10
    assert len({tuple(sorted((f["team_a"], f["team_b"]))) for f in tournament["fixtures"]}) == 10
    item = tournament["fixtures"][0]
    result = post(client, url + "/results", {"fixture_id": item["id"], "score_a": 1000, "score_b": 740})
    assert result.status_code == 200
    leader = result.get_json()["standings"][0]
    assert leader["team"] == item["team_a"]
    assert leader["points"] == 3 and leader["difference"] == 260
    other = app.test_client()
    assert post(other, url + "/results", {"fixture_id": item["id"], "score_a": 0, "score_b": 1}).status_code == 403
    assert client.get(url + "/export.csv").status_code == 200


def test_knockout_byes_progression_and_corrections(client):
    tournament_id = create_tournament(client, format="knockout", teams=["A", "B", "C", "D", "E"])
    url = f"/api/tournaments/{tournament_id}"
    tournament = client.get(url).get_json()
    assert sum(f["status"] == "bye" for f in tournament["fixtures"]) == 3
    for _ in range(4):
        tournament = client.get(url).get_json()
        item = next((f for f in tournament["fixtures"] if f["status"] == "pending"), None)
        assert item is not None
        assert post(client, url + "/results", {"fixture_id": item["id"], "score_a": 500, "score_b": 500}).status_code == 400
        response = post(client, url + "/results", {"fixture_id": item["id"], "score_a": 1000, "score_b": 500})
        assert response.status_code == 200, response.get_json()
    tournament = client.get(url).get_json()
    assert tournament["fixtures"][-1]["winner"] is not None
    first = next(f for f in tournament["fixtures"] if f["status"] == "finished")
    assert post(client, url + "/results", {"fixture_id": first["id"], "score_a": 1, "score_b": 2}).status_code == 400


def test_digital_fixture_creates_linked_room(client):
    tournament_id = create_tournament(client, mode="digital", teams=["A", "B"])
    url = f"/api/tournaments/{tournament_id}"
    fixture = client.get(url).get_json()["fixtures"][0]
    room_url = url + f"/fixtures/{fixture['id']}/room"
    response = post(client, room_url, {"rules": {"max_hands": 1}, "player_name": "Host"})
    assert response.status_code == 201
    code = response.get_json()["code"]
    assert post(client, room_url).get_json()["code"] == code
    room = client.get(f"/api/rooms/{code}").get_json()
    assert room["team_a"] == "A" and room["team_b"] == "B"
    assert room["tournament_id"] == tournament_id
    assert room["my_seat"] is None and room["players"] == []
    assert post(client, url + "/results", {"fixture_id": fixture["id"], "score_a": 10, "score_b": 20}).status_code == 400
    assert post(client, f"/api/rooms/{code}/join", {"name": "Host player", "seat": 0}).status_code == 200
    post(client, f"/api/rooms/{code}/start", {"fill_bots": True})
    response = post(client, f"/api/rooms/{code}/action", {"type": "contract", "contract": "H"})
    for _ in range(12):
        room = response.get_json()
        if room["game"]["phase"] == "finished":
            break
        response = post(client, f"/api/rooms/{code}/action", {"type": "play", "card": room["game"]["legal_cards"][0]})
        assert response.status_code == 200
    recorded = client.get(url).get_json()["fixtures"][0]
    assert recorded["status"] == "finished"
    assert [recorded["score_a"], recorded["score_b"]] == response.get_json()["game"]["scores"]


def test_digital_knockout_draw_preserves_hand_and_requests_playoff(client, monkeypatch):
    from app import engine

    tournament_id = create_tournament(client, mode="digital", format="knockout", teams=["A", "B"])
    url = f"/api/tournaments/{tournament_id}"
    item = client.get(url).get_json()["fixtures"][0]
    code = post(client, url + f"/fixtures/{item['id']}/room", {"rules": {"max_hands": 2}}).get_json()["code"]
    room_url = f"/api/rooms/{code}"
    assert post(client, room_url + "/join", {"name": "Host player", "seat": 0}).status_code == 200
    assert post(client, room_url + "/start", {"fill_bots": True}).status_code == 200

    def finish_tied_hand(game, seat, action):
        game.update(phase="finished", scores=[500, 500], winner=None, hand_number=2)
        return game

    monkeypatch.setattr(engine, "apply_action", finish_tied_hand)
    response = post(client, room_url + "/action", {"type": "contract", "contract": "H"})
    assert response.status_code == 200
    room = response.get_json()
    assert room["status"] == "playing" and room["playoff"] is True
    assert room["game"]["phase"] == "hand_end"
    assert room["game"]["scores"] == [500, 500]
    assert room["game"]["rules"]["max_hands"] == 3
    fixture = client.get(url).get_json()["fixtures"][0]
    assert fixture["status"] == "pending" and fixture["score_a"] is None


@pytest.mark.parametrize("hands", [1, 2])
def test_digital_organizer_can_spectate_and_run_bot_table(client, app, hands):
    tournament_id = create_tournament(client, mode="digital", teams=["A", "B"])
    url = f"/api/tournaments/{tournament_id}"
    item = client.get(url).get_json()["fixtures"][0]
    code = post(client, url + f"/fixtures/{item['id']}/room", {"rules": {"max_hands": hands}}).get_json()["code"]
    room_url = f"/api/rooms/{code}"
    response = post(client, room_url + "/start", {"fill_bots": True})
    assert response.status_code == 200, response.get_json()
    room = response.get_json()
    assert room["my_seat"] is None and room["is_host"] is True
    assert room["game"]["hand"] == []
    if hands == 2:
        assert room["game"]["phase"] == "hand_end"
        assert post(client, room_url + "/action", {"type": "play", "card": "HA"}).status_code == 403
        stranger = app.test_client()
        assert post(stranger, room_url + "/action", {"type": "next_hand"}).status_code == 403
        response = post(client, room_url + "/action", {"type": "next_hand"})
        assert response.status_code == 200, response.get_json()
        room = response.get_json()
    assert room["game"]["phase"] == "finished"
    recorded = client.get(url).get_json()["fixtures"][0]
    assert recorded["status"] == "finished"
    assert [recorded["score_a"], recorded["score_b"]] == room["game"]["scores"]


def test_database_survives_new_app(tmp_path):
    database = "sqlite:///" + str(tmp_path / "persistent.sqlite")
    first = create_app({"TESTING": True, "SECRET_KEY": "persistent-test", "DATABASE_URL": database})
    client1 = first.test_client()
    match_id = create_match(client1)
    post(client1, f"/api/matches/{match_id}/rounds", {"points_a": 90})
    first.extensions["store"].engine.dispose()
    second = create_app({"TESTING": True, "SECRET_KEY": "persistent-test", "DATABASE_URL": database})
    result = second.test_client().get(f"/api/matches/{match_id}").get_json()
    assert result["totals"] == [90, 67]
    second.extensions["store"].engine.dispose()


@pytest.mark.parametrize("payload", [None, [], "bad", {"name": "A" * 500}, {"teams": ["A", "a"]}])
def test_bad_input_returns_json(client, payload):
    result = client.post("/api/tournaments", json=payload, headers={"X-CSRF-Token": token(client)})
    assert result.status_code == 400
    assert "error" in result.get_json()
