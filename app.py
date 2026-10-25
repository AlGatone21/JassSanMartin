"""ASS Jass: local Flask application and production WSGI entry point."""
import csv
import io
import os
from pathlib import Path
import secrets

from dotenv import load_dotenv
from flask import Flask, Response, abort, jsonify, render_template, request, session
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from jass import engine
from jass.competitions import (add_round, integer, new_match, new_tournament,
                               recompute_match, set_result, standings, text)
from jass.storage import Store

load_dotenv()


def create_app(config=None):
    app = Flask(__name__, instance_relative_config=True)
    instance = Path(app.instance_path)
    instance.mkdir(parents=True, exist_ok=True)
    secret = os.environ.get("SECRET_KEY")
    if not secret:
        keyfile = instance / "secret.key"
        try:
            secret = keyfile.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            secret = secrets.token_hex(32)
            try:
                with keyfile.open("x", encoding="utf-8") as handle:
                    handle.write(secret)
            except FileExistsError:
                secret = keyfile.read_text(encoding="utf-8").strip()
    app.config.from_mapping(
        SECRET_KEY=secret,
        DATABASE_URL=os.environ.get("DATABASE_URL", "sqlite:///" + str(instance / "jass.db")),
        MAX_CONTENT_LENGTH=32768,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE", os.environ.get("COOKIE_SECURE", "false")).lower() == "true",
        PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 365,
    )
    if config:
        app.config.update(config)
    if os.environ.get("RENDER"):
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
    store = Store(app.config["DATABASE_URL"])
    app.extensions["store"] = store

    def identity():
        if "sid" not in session:
            session["sid"] = secrets.token_hex(24)
            session["csrf"] = secrets.token_hex(24)
            session.permanent = True
        return session["sid"]

    def body():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise ValueError("A JSON object is required")
        return data

    def record(connection, record_id, kind):
        found = store.get(connection, record_id, kind)
        if found is None:
            abort(404, description="Not found")
        return found

    def owner(found):
        if found["owner"] != identity():
            abort(403, description="Only the organizer can change this item")

    def save(connection, found):
        store.put(connection, found["id"], found["kind"], found["owner"], found["data"])

    def new_id(connection, kind):
        while True:
            candidate = secrets.token_hex(4).upper() if kind == "room" else secrets.token_hex(8)
            if not store.get(connection, candidate):
                return candidate

    def member_seat(room):
        return next((p["seat"] for p in room["players"] if p.get("sid") == identity()), None)

    def room_view(found):
        room = found["data"]
        seat = member_seat(room)
        return dict(code=found["id"], name=room["name"], status=room["status"],
                    is_host=found["owner"] == identity(), my_seat=seat,
                    players=[{k: v for k, v in p.items() if k != "sid"} for p in room["players"]],
                    game=engine.public_view(room["game"], seat) if room["game"] else None,
                    rules=room["rules"], team_a=room.get("team_a", "ASS A"),
                    team_b=room.get("team_b", "ASS B"), tournament_id=room.get("tournament_id"),
                    playoff=room.get("playoff", False))

    def match_view(found):
        return dict(found["data"], id=found["id"], is_owner=found["owner"] == identity())

    def tournament_view(found):
        tournament = found["data"]
        return dict(tournament, id=found["id"], is_owner=found["owner"] == identity(),
                    standings=standings(tournament))

    def make_room(connection, payload, tournament=None, fixture=None):
        mode = payload.get("mode", "solo")
        if mode not in ("solo", "multiplayer"):
            raise ValueError("Invalid room mode")
        room = {"name": text(payload.get("name"), "Name", default="ASS Jass"),
                "rules": engine.normalize_rules(payload.get("rules", {})),
                "players": [{"seat": 0, "name": text(payload.get("player_name"), "Player", 32,
                                                          default=session.get("name", "ASS")),
                             "bot": False, "sid": identity()}],
                "game": None, "status": "lobby"}
        if not (tournament and fixture):
            session["name"] = room["players"][0]["name"]
        if tournament and fixture:
            # The organizer runs the table; all four competition seats stay free.
            room["players"] = []
            room.update(tournament_id=tournament["id"], fixture_id=fixture["id"],
                        team_a=fixture["team_a"], team_b=fixture["team_b"])
        if mode == "solo":
            fill_bots(room)
            room["game"] = engine.new_game(room["rules"])
            room["status"] = "playing"
            advance_bots(room)
        code = new_id(connection, "room")
        store.put(connection, code, "room", identity(), room, new=True)
        return code

    def fill_bots(room):
        occupied = {p["seat"] for p in room["players"]}
        names = ("Nell", "Puur", "Rosa", "Bündner")
        for seat in range(4):
            if seat not in occupied:
                room["players"].append({"seat": seat, "name": names[seat], "bot": True})
        room["players"].sort(key=lambda p: p["seat"])

    def advance_bots(room):
        game = room["game"]
        bots = {p["seat"] for p in room["players"] if p["bot"]}
        for _ in range(50):
            if game["phase"] not in ("contract", "play") or game["turn"] not in bots:
                break
            seat = game["turn"]
            action = engine.bot_action(game, seat, room["rules"].get("bot_difficulty", "smart"))
            engine.apply_action(game, seat, action)
        room["status"] = "finished" if game["phase"] == "finished" else "playing"

    def sync_tournament(connection, room):
        if room["status"] != "finished" or not room.get("tournament_id"):
            return
        found = record(connection, room["tournament_id"], "tournament")
        if found["data"]["format"] == "knockout" and room["game"]["scores"][0] == room["game"]["scores"][1]:
            # Keep a completed tied hand, then let the host deal a playoff hand.
            game = room["game"]
            game["phase"] = "hand_end"
            if game["rules"]["max_hands"]:
                game["rules"]["max_hands"] = game["hand_number"] + 1
            room["rules"] = dict(game["rules"])
            room.update(status="playing", playoff=True)
            return
        item = next(f for f in found["data"]["fixtures"] if f["id"] == room["fixture_id"])
        if item["status"] != "finished":
            set_result(found["data"], room["fixture_id"], *room["game"]["scores"], from_room=True)
            save(connection, found)

    @app.before_request
    def protect_request():
        if request.path.startswith("/api/"):
            identity()
            if request.method in ("POST", "PUT", "PATCH", "DELETE"):
                token = request.headers.get("X-CSRF-Token", "")
                if not token or not secrets.compare_digest(token, session.get("csrf", "")):
                    abort(403, description="Session expired; refresh the page and try again")

    @app.after_request
    def headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(ValueError)
    def invalid(error):
        return jsonify(error=str(error)), 400

    @app.errorhandler(HTTPException)
    def http_error(error):
        if request.path.startswith("/api/"):
            return jsonify(error=error.description), error.code
        return error

    @app.route("/")
    @app.route("/room/<record_id>")
    @app.route("/score/<record_id>")
    @app.route("/tournament/<record_id>")
    def index(record_id=None):
        identity()
        return render_template("index.html")

    @app.get("/health")
    def health():
        with store.transaction() as connection:
            connection.exec_driver_sql("SELECT 1")
        return jsonify(status="ok")

    @app.get("/api/session")
    def get_session():
        return jsonify(csrf=session["csrf"], name=session.get("name", ""))

    @app.post("/api/profile")
    def profile():
        session["name"] = text(body().get("name"), "Player", 32)
        return jsonify(name=session["name"])

    @app.get("/api/overview")
    def overview():
        result = {"rooms": [], "matches": [], "tournaments": []}
        with store.transaction() as connection:
            for found in store.all(connection):
                data = found["data"]
                if found["kind"] == "room":
                    if found["owner"] == identity() or member_seat(data) is not None:
                        result["rooms"].append({"code": found["id"], "name": data["name"],
                                                 "status": data["status"], "updated": found["updated"]})
                elif found["owner"] == identity():
                    key = "matches" if found["kind"] == "match" else "tournaments"
                    fields = ("team_a", "team_b", "target", "totals", "winner") if key == "matches" else ("format", "mode", "teams")
                    summary = {"id": found["id"], "name": data["name"], "updated": found["updated"]}
                    summary.update({field: data[field] for field in fields})
                    result[key].append(summary)
        return jsonify(result)

    @app.post("/api/rooms")
    def create_room():
        with store.transaction() as connection:
            code = make_room(connection, body())
        return jsonify(code=code), 201

    @app.get("/api/rooms/<code>")
    def get_room(code):
        with store.transaction() as connection:
            return jsonify(room_view(record(connection, code.upper(), "room")))

    @app.post("/api/rooms/<code>/join")
    def join_room(code):
        payload = body()
        with store.transaction() as connection:
            found = record(connection, code.upper(), "room")
            room = found["data"]
            if member_seat(room) is not None:
                return jsonify(room_view(found))
            if room["status"] != "lobby":
                abort(409, description="This game has already started")
            occupied = {p["seat"] for p in room["players"]}
            available = [seat for seat in range(4) if seat not in occupied]
            if not available:
                abort(409, description="This room is full")
            seat = integer(payload.get("seat", available[0]), "Seat", 0, 3)
            if seat not in available:
                abort(409, description="That seat is taken")
            name = text(payload.get("name"), "Player", 32, default=session.get("name", "ASS"))
            session["name"] = name
            room["players"].append({"seat": seat, "name": name, "bot": False, "sid": identity()})
            room["players"].sort(key=lambda p: p["seat"])
            save(connection, found)
            return jsonify(room_view(found))

    @app.post("/api/rooms/<code>/start")
    def start_room(code):
        payload = body()
        with store.transaction() as connection:
            found = record(connection, code.upper(), "room")
            owner(found)
            room = found["data"]
            if room["status"] != "lobby":
                abort(409, description="This game has already started")
            if payload.get("fill_bots", False):
                fill_bots(room)
            if len(room["players"]) != 4:
                raise ValueError("Four players are required; invite friends or fill empty seats with bots")
            room["game"] = engine.new_game(room["rules"])
            room["status"] = "playing"
            advance_bots(room)
            sync_tournament(connection, room)
            save(connection, found)
            return jsonify(room_view(found))

    @app.post("/api/rooms/<code>/action")
    def room_action(code):
        payload = body()
        with store.transaction() as connection:
            found = record(connection, code.upper(), "room")
            room = found["data"]
            seat = member_seat(room)
            if room["status"] != "playing" or not room["game"]:
                abort(409, description="This game is not running")
            if payload.get("type") == "next_hand":
                owner(found)
                engine.next_hand(room["game"])
            else:
                if seat is None:
                    abort(403, description="Join this room before playing")
                engine.apply_action(room["game"], seat, payload)
            advance_bots(room)
            sync_tournament(connection, room)
            save(connection, found)
            return jsonify(room_view(found))

    @app.post("/api/matches")
    def create_match():
        match = new_match(body())
        with store.transaction() as connection:
            record_id = new_id(connection, "match")
            store.put(connection, record_id, "match", identity(), match, new=True)
        return jsonify(id=record_id), 201

    @app.get("/api/matches/<record_id>")
    def get_match(record_id):
        with store.transaction() as connection:
            return jsonify(match_view(record(connection, record_id, "match")))

    @app.post("/api/matches/<record_id>/rounds")
    def match_round(record_id):
        payload = body()
        with store.transaction() as connection:
            found = record(connection, record_id, "match")
            owner(found)
            add_round(found["data"], payload)
            save(connection, found)
            return jsonify(match_view(found))

    @app.post("/api/matches/<record_id>/undo")
    def undo_round(record_id):
        with store.transaction() as connection:
            found = record(connection, record_id, "match")
            owner(found)
            if not found["data"]["rounds"]:
                raise ValueError("No rounds to undo")
            found["data"]["rounds"].pop()
            recompute_match(found["data"])
            save(connection, found)
            return jsonify(match_view(found))

    @app.post("/api/tournaments")
    def create_tournament():
        tournament = new_tournament(body())
        with store.transaction() as connection:
            record_id = new_id(connection, "tournament")
            store.put(connection, record_id, "tournament", identity(), tournament, new=True)
        return jsonify(id=record_id), 201

    @app.get("/api/tournaments/<record_id>")
    def get_tournament(record_id):
        with store.transaction() as connection:
            return jsonify(tournament_view(record(connection, record_id, "tournament")))

    @app.post("/api/tournaments/<record_id>/results")
    def tournament_result(record_id):
        payload = body()
        with store.transaction() as connection:
            found = record(connection, record_id, "tournament")
            owner(found)
            set_result(found["data"], payload.get("fixture_id"), payload.get("score_a"), payload.get("score_b"))
            save(connection, found)
            return jsonify(tournament_view(found))

    @app.post("/api/tournaments/<record_id>/fixtures/<fixture_id>/room")
    def fixture_room(record_id, fixture_id):
        payload = body()
        with store.transaction() as connection:
            found = record(connection, record_id, "tournament")
            owner(found)
            tournament = found["data"]
            if tournament["mode"] != "digital":
                raise ValueError("Digital rooms are available for digital tournaments")
            item = next((f for f in tournament["fixtures"] if f["id"] == fixture_id), None)
            if item is None:
                abort(404, description="Fixture not found")
            if item["room_code"]:
                return jsonify(code=item["room_code"])
            if item["status"] != "pending":
                raise ValueError("This fixture is not ready to play")
            room_payload = {"name": f"{item['team_a']} · {item['team_b']}",
                            "mode": "multiplayer", "rules": payload.get("rules", {}),
                            "player_name": payload.get("player_name", session.get("name", "ASS"))}
            code = make_room(connection, room_payload, found, item)
            item["room_code"] = code
            save(connection, found)
            return jsonify(code=code), 201

    def csv_response(rows, filename):
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        for row in rows:
            # Neutralize spreadsheet formulas in user-supplied names and notes.
            writer.writerow([("'" + cell if isinstance(cell, str) and cell.lstrip().startswith(("=", "+", "-", "@")) else cell)
                             for cell in row])
        return Response("\ufeff" + output.getvalue(), mimetype="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    @app.get("/api/matches/<record_id>/export.csv")
    def match_csv(record_id):
        with store.transaction() as connection:
            match = record(connection, record_id, "match")["data"]
        rows = [["Round / Mano / Runde", match["team_a"], match["team_b"], "Multiplier", "Note"]]
        rows.extend([[r["number"], r["total_a"], r["total_b"], r["multiplier"], r["note"]] for r in match["rounds"]])
        rows.append(["Total", *match["totals"], "", ""])
        return csv_response(rows, f"jass-{record_id}.csv")

    @app.get("/api/tournaments/<record_id>/export.csv")
    def tournament_csv(record_id):
        with store.transaction() as connection:
            tournament = record(connection, record_id, "tournament")["data"]
        rows = [["Round / Turno / Runde", "Team A", "Team B", "Score A", "Score B", "Status"]]
        rows.extend([[f["round"], f["team_a"], f["team_b"], f["score_a"], f["score_b"], f["status"]]
                     for f in tournament["fixtures"]])
        rows.append([])
        rows.append(["Team", "Played", "Won", "Drawn", "Lost", "Points", "Scored", "Conceded", "Difference"])
        rows.extend([[r[key] for key in ("team", "played", "won", "drawn", "lost", "points", "scored", "conceded", "difference")]
                     for r in standings(tournament)])
        return csv_response(rows, f"tournament-{record_id}.csv")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "5000")),
            debug=os.environ.get("FLASK_DEBUG", "0") == "1")
