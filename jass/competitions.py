"""Validated score sheets and deterministic competition schedules."""
import secrets


def integer(value, label, minimum=0, maximum=100000):
    if isinstance(value, bool):
        raise ValueError(f"{label}: integer required")
    if isinstance(value, str):
        if not value.strip().lstrip("-").isdigit():
            raise ValueError(f"{label}: integer required")
        value = int(value)
    if not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"{label}: must be between {minimum} and {maximum}")
    return value


def text(value, label, maximum=80, default=None):
    if value is None and default is not None:
        value = default
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise ValueError(f"{label}: enter 1–{maximum} characters")
    return value.strip()


def new_match(payload):
    a = text(payload.get("team_a"), "Team A", default="ASS A")
    b = text(payload.get("team_b"), "Team B", default="ASS B")
    if a.casefold() == b.casefold():
        raise ValueError("Team names must be different")
    return {"name": text(payload.get("name"), "Name", default="Jass"),
            "team_a": a, "team_b": b,
            "target": integer(payload.get("target", 1000), "Target", 100, 100000),
            "totals": [0, 0], "rounds": [], "winner": None}


def add_round(match, payload):
    if match["winner"] is not None:
        raise ValueError("Match already finished; undo the last round to correct it")
    a = integer(payload.get("points_a"), "Points A", 0, 157)
    b = integer(payload.get("points_b", 157 - a), "Points B", 0, 157)
    if a + b != 157:
        raise ValueError("Card points must total 157")
    bonus_a = integer(payload.get("bonus_a", 0), "Bonus A", 0, 2000)
    bonus_b = integer(payload.get("bonus_b", 0), "Bonus B", 0, 2000)
    multiplier = integer(payload.get("multiplier", 1), "Multiplier", 1, 3)
    note = payload.get("note", "")
    if not isinstance(note, str) or len(note) > 240:
        raise ValueError("Note: maximum 240 characters")
    match["rounds"].append({"number": len(match["rounds"]) + 1,
                            "points_a": a, "points_b": b,
                            "bonus_a": bonus_a, "bonus_b": bonus_b,
                            "multiplier": multiplier, "note": note.strip(),
                            "total_a": (a + bonus_a) * multiplier,
                            "total_b": (b + bonus_b) * multiplier})
    recompute_match(match)


def recompute_match(match):
    match["totals"] = [sum(r["total_a"] for r in match["rounds"]),
                       sum(r["total_b"] for r in match["rounds"])]
    a, b = match["totals"]
    match["winner"] = (0 if a > b else 1) if max(a, b) >= match["target"] and a != b else None


def fixture(round_number, a, b, source_a=None, source_b=None):
    return {"id": secrets.token_hex(5), "round": round_number,
            "team_a": a, "team_b": b, "source_a": source_a, "source_b": source_b,
            "score_a": None, "score_b": None, "status": "pending",
            "winner": None, "room_code": None}


def new_tournament(payload):
    teams = payload.get("teams")
    if not isinstance(teams, list) or not 2 <= len(teams) <= 32:
        raise ValueError("Enter between 2 and 32 teams")
    teams = [text(t, "Team", 50) for t in teams]
    if len({t.casefold() for t in teams}) != len(teams):
        raise ValueError("Team names must be unique")
    form = payload.get("format", "round_robin")
    mode = payload.get("mode", "physical")
    if form not in ("round_robin", "knockout") or mode not in ("physical", "digital"):
        raise ValueError("Invalid tournament format or mode")
    tournament = {"name": text(payload.get("name"), "Name", default="ASS Jass"),
                  "format": form, "mode": mode, "teams": teams, "fixtures": []}
    if form == "round_robin":
        circle = list(teams)
        if len(circle) % 2:
            circle.append(None)
        for round_number in range(1, len(circle)):
            for i in range(len(circle) // 2):
                a, b = circle[i], circle[-1 - i]
                if a is not None and b is not None:
                    tournament["fixtures"].append(fixture(round_number, a, b))
            circle = [circle[0], circle[-1], *circle[1:-1]]
    else:
        size = 2
        while size < len(teams):
            size *= 2
        bye_count = size - len(teams)
        initial = []
        for i in range(bye_count):
            initial.extend([teams[i], None])
        initial.extend(teams[bye_count:])
        previous = []
        for i in range(0, size, 2):
            item = fixture(1, initial[i], initial[i + 1])
            if item["team_b"] is None:
                item.update(status="bye", winner=item["team_a"])
            tournament["fixtures"].append(item)
            previous.append(item)
        round_number = 2
        while len(previous) > 1:
            current = []
            for i in range(0, len(previous), 2):
                item = fixture(round_number, None, None, previous[i]["id"], previous[i + 1]["id"])
                item["status"] = "waiting"
                tournament["fixtures"].append(item)
                current.append(item)
            previous = current
            round_number += 1
        refresh_knockout(tournament)
    return tournament


def refresh_knockout(tournament):
    if tournament["format"] != "knockout":
        return
    by_id = {f["id"]: f for f in tournament["fixtures"]}
    for item in tournament["fixtures"]:
        if item["source_a"]:
            item["team_a"] = by_id[item["source_a"]]["winner"]
            item["team_b"] = by_id[item["source_b"]]["winner"]
            if item["status"] != "finished":
                item["status"] = "pending" if item["team_a"] and item["team_b"] else "waiting"


def set_result(tournament, fixture_id, score_a, score_b, from_room=False):
    fixtures = tournament["fixtures"]
    item = next((f for f in fixtures if f["id"] == fixture_id), None)
    if item is None:
        raise ValueError("Fixture not found")
    if item["status"] in ("waiting", "bye"):
        raise ValueError("This fixture cannot receive a result yet")
    if item.get("room_code") and not from_room:
        raise ValueError("Digital results are updated from the linked game")
    a = integer(score_a, "Score A")
    b = integer(score_b, "Score B")
    if tournament["format"] == "knockout":
        if a == b:
            raise ValueError("Knockout fixtures cannot end in a draw")
        descendants = {item["id"]}
        for child in fixtures:
            if child.get("source_a") in descendants or child.get("source_b") in descendants:
                if child["status"] == "finished" or child.get("room_code"):
                    raise ValueError("A later fixture has already started; its earlier result cannot be changed")
                descendants.add(child["id"])
    item.update(score_a=a, score_b=b, status="finished",
                winner=item["team_a"] if a > b else item["team_b"] if b > a else None)
    refresh_knockout(tournament)


def standings(tournament):
    rows = {team: {"team": team, "played": 0, "won": 0, "drawn": 0, "lost": 0,
                   "points": 0, "scored": 0, "conceded": 0, "difference": 0}
            for team in tournament["teams"]}
    for item in tournament["fixtures"]:
        if item["status"] != "finished":
            continue
        for team, own, other in ((item["team_a"], item["score_a"], item["score_b"]),
                                  (item["team_b"], item["score_b"], item["score_a"])):
            row = rows[team]
            row["played"] += 1
            row["scored"] += own
            row["conceded"] += other
            row["difference"] = row["scored"] - row["conceded"]
            if own > other:
                row["won"] += 1
                row["points"] += 3
            elif own == other:
                row["drawn"] += 1
                row["points"] += 1
            else:
                row["lost"] += 1
    return sorted(rows.values(), key=lambda r: (-r["points"], -r["difference"], -r["scored"], r["team"].casefold()))
