"""Server-authoritative Schieber, with optional club scoring variants.

Cards use H/D/C/S and 6..10/J/Q/K/A. Seats advance counterclockwise,
and opposite seats are partners. Scores finish at a hand boundary; automatic
Weis is an explicit convenience variant rather than a manual declaration.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import random


SUITS = ("H", "D", "C", "S")
RANKS = ("6", "7", "8", "9", "10", "J", "Q", "K", "A")
DECK = tuple(suit + rank for suit in SUITS for rank in RANKS)
CONTRACTS = SUITS + ("obenabe", "undenufe")
TRUMP_ORDER = ("6", "7", "8", "10", "Q", "K", "A", "9", "J")
DEFAULT_RULES = {
    "target_score": 1000,
    "max_hands": 0,
    "multipliers": False,
    "weis": True,
    "stock": True,
    "match_bonus": True,
    "bot_difficulty": "smart",
    "allow_topdown": True,
    "allow_bottomup": True,
}


def normalize_rules(rules=None):
    """Validate recognized options and produce a stable serializable config."""
    if rules is None:
        return dict(DEFAULT_RULES)
    if not isinstance(rules, dict):
        raise ValueError("Rules must be an object.")
    source = dict(rules)
    for alias, name in (("target", "target_score"), ("hands", "max_hands")):
        if alias in source and name not in source:
            source[name] = source[alias]
    result = dict(DEFAULT_RULES)
    for name in result:
        if name in source:
            result[name] = source[name]
    for name, minimum, maximum in (("target_score", 100, 10000), ("max_hands", 0, 100)):
        value = result[name]
        if type(value) is not int or not minimum <= value <= maximum:
            raise ValueError(f"{name} must be an integer between {minimum} and {maximum}.")
    for name in ("multipliers", "weis", "stock", "match_bonus", "allow_topdown", "allow_bottomup"):
        if type(result[name]) is not bool:
            raise ValueError(f"{name} must be true or false.")
    if result["bot_difficulty"] not in ("smart", "easy"):
        raise ValueError("Unknown bot difficulty.")
    return result


def card_strength(card, contract):
    rank = card[1:]
    if contract in SUITS and card[0] == contract:
        return TRUMP_ORDER.index(rank)
    index = RANKS.index(rank)
    return 8 - index if contract == "undenufe" else index


def card_points(card, contract):
    rank = card[1:]
    if contract in SUITS and card[0] == contract:
        if rank == "J":
            return 20
        if rank == "9":
            return 14
    if contract in ("obenabe", "undenufe") and rank == "8":
        return 8
    if contract == "undenufe":
        if rank == "6":
            return 11
        if rank == "A":
            return 0
    return {"A": 11, "K": 4, "Q": 3, "J": 2, "10": 10}.get(rank, 0)


def contract_multiplier(contract, rules):
    if not rules["multipliers"]:
        return 1
    return 3 if contract in ("obenabe", "undenufe") else (2 if contract in ("C", "S") else 1)


def available_contracts(rules):
    return list(SUITS) + (["obenabe"] if rules["allow_topdown"] else []) + (["undenufe"] if rules["allow_bottomup"] else [])


def _deal(game, seed=None):
    cards = list(DECK)
    # Never publish or persist a PRNG seed from which a hand can be recovered.
    rng = random.Random(seed) if seed is not None else random.SystemRandom()
    rng.shuffle(cards)
    game.update({
        "phase": "contract", "hands": [sorted(cards[i * 9:(i + 1) * 9], key=DECK.index) for i in range(4)],
        "turn": (game["dealer"] + 1) % 4, "forehand": (game["dealer"] + 1) % 4,
        "contract": None, "passed": False, "trick": [], "last_trick": None,
        "trick_history": [], "played_cards": [], "hand_scores": [0, 0],
        "tricks_won": [0, 0], "announcements": [], "stock_owner": None,
        "stock_played": [], "multiplier": 1, "winner": None,
    })


def new_game(rules=None, seed=None):
    game = {"rules": normalize_rules(rules), "scores": [0, 0], "dealer": 3, "hand_number": 1, "history": []}
    _deal(game, seed)
    return game


def _check_turn(game, seat, phase):
    if type(seat) is not int or seat not in range(4):
        raise ValueError("Invalid player seat.")
    if game["phase"] != phase:
        raise ValueError("This action is not available in the current phase.")
    if game["turn"] != seat:
        raise ValueError("It is another player's turn.")


def _legal(hand, trick, contract):
    if not trick:
        return list(hand)
    led = trick[0]["card"][0]
    followers = [c for c in hand if c[0] == led]
    if led == contract:
        if len(followers) == 1 and followers[0] == contract + "J":
            return list(hand)
        return followers or list(hand)
    trumps = [c for c in hand if c[0] == contract] if contract in SUITS else []
    candidates = followers + trumps if followers else list(hand)
    table_trumps = [p["card"] for p in trick if p["card"][0] == contract]
    if table_trumps and len(trumps) != len(hand):
        highest = max(card_strength(c, contract) for c in table_trumps)
        candidates = [c for c in candidates if c[0] != contract or card_strength(c, contract) > highest]
    return candidates


def legal_cards(game, seat):
    if type(seat) is not int or seat not in range(4) or game["phase"] != "play" or game["turn"] != seat:
        return []
    return _legal(game["hands"][seat], game["trick"], game["contract"])


def trick_winner(trick, contract):
    if not trick:
        raise ValueError("A trick must contain a card.")
    led = trick[0]["card"][0]
    def strength(play):
        card = play["card"]
        category = 2 if card[0] == contract else (1 if card[0] == led else 0)
        return category, card_strength(card, contract)
    return max(trick, key=strength)["seat"]


def find_melds(hand, contract):
    """Maximal runs and four of a rank; cross-melds are permitted."""
    melds = []
    cards = set(hand)
    for suit in SUITS:
        run = []
        for rank in RANKS + (None,):
            if rank is not None and suit + rank in cards:
                run.append(suit + rank)
            else:
                if len(run) >= 3:
                    size = len(run)
                    points = 20 if size == 3 else (50 if size == 4 else (size - 3) * 50)
                    high = run[0] if contract == "undenufe" else run[-1]
                    melds.append({"type": "sequence", "cards": list(run), "points": points,
                                  "strength": [points, size, card_strength(high, "undenufe" if contract == "undenufe" else "obenabe"), int(suit == contract)]})
                run = []
    for rank in RANKS:
        group = [s + rank for s in SUITS]
        if all(c in cards for c in group):
            points = 200 if rank == "J" else (150 if rank == "9" else 100)
            strength = card_strength(group[0], "undenufe" if contract == "undenufe" else "obenabe")
            melds.append({"type": "four", "cards": group, "points": points,
                          "strength": [points, 4, strength, 0]})
    return melds


def _award_melds(game):
    if not game["rules"]["weis"]:
        return
    all_melds = [find_melds(hand, game["contract"]) for hand in game["hands"]]
    ranked = []
    for offset in range(4):
        seat = (game["forehand"] + offset) % 4
        for meld in all_melds[seat]:
            ranked.append((tuple(meld["strength"]) + (-offset,), seat))
    if not ranked:
        return
    winner = max(ranked)[1]
    team = winner % 2
    # Only the winning team's actual melds are revealed.
    for seat in range(4):
        if seat % 2 == team and all_melds[seat]:
            points = sum(m["points"] for m in all_melds[seat]) * game["multiplier"]
            game["hand_scores"][team] += points
            game["announcements"].append({"type": "weis", "seat": seat, "team": team,
                                          "points": points, "melds": [{k:v for k,v in m.items() if k != "strength"} for m in all_melds[seat]]})


def choose_contract(game, seat, contract):
    _check_turn(game, seat, "contract")
    if not isinstance(contract, str) or contract not in available_contracts(game["rules"]):
        raise ValueError("Invalid contract.")
    game.update({"contract": contract, "phase": "play", "turn": game["forehand"],
                 "multiplier": contract_multiplier(contract, game["rules"])})
    _award_melds(game)
    if game["rules"]["stock"] and contract in SUITS:
        for owner, hand in enumerate(game["hands"]):
            if contract + "K" in hand and contract + "Q" in hand:
                game["stock_owner"] = owner
                break
    return game


def pass_contract(game, seat):
    _check_turn(game, seat, "contract")
    if game["passed"]:
        raise ValueError("The partner must choose a contract.")
    game["passed"] = True
    game["turn"] = (seat + 2) % 4
    return game


def _finish_hand(game):
    if game["rules"]["match_bonus"] and 9 in game["tricks_won"]:
        team = game["tricks_won"].index(9)
        points = 100 * game["multiplier"]
        game["hand_scores"][team] += points
        game["announcements"].append({"type": "match", "team": team, "points": points})
    game["scores"] = [game["scores"][i] + game["hand_scores"][i] for i in range(2)]
    game["history"].append({"hand_number": game["hand_number"], "contract": game["contract"],
                            "multiplier": game["multiplier"], "points": list(game["hand_scores"]),
                            "scores": list(game["scores"]), "tricks_won": list(game["tricks_won"]),
                            "announcements": deepcopy(game["announcements"])})
    rules = game["rules"]
    tied = game["scores"][0] == game["scores"][1]
    # Target games require a winner. Fixed-hand games may draw; knockout
    # orchestration can explicitly append a playoff hand.
    finished = (game["hand_number"] >= rules["max_hands"] if rules["max_hands"] else
                max(game["scores"]) >= rules["target_score"] and not tied)
    game["phase"] = "finished" if finished else "hand_end"
    if finished:
        game["winner"] = None if game["scores"][0] == game["scores"][1] else int(game["scores"][1] > game["scores"][0])


def play_card(game, seat, card):
    _check_turn(game, seat, "play")
    if not isinstance(card, str) or card not in legal_cards(game, seat):
        raise ValueError("This card cannot be played.")
    game["hands"][seat].remove(card)
    game["trick"].append({"seat": seat, "card": card})
    game["played_cards"].append(card)
    if game.get("stock_owner") == seat and card in (game["contract"] + "K", game["contract"] + "Q"):
        game["stock_played"].append(card)
        if len(game["stock_played"]) == 2:
            points = 20 * game["multiplier"]
            game["hand_scores"][seat % 2] += points
            game["announcements"].append({"type": "stock", "seat": seat, "team": seat % 2, "points": points})
    if len(game["trick"]) < 4:
        game["turn"] = (seat + 1) % 4
        return game
    winner = trick_winner(game["trick"], game["contract"])
    final = len(game["played_cards"]) == 36
    points = (sum(card_points(p["card"], game["contract"]) for p in game["trick"]) + (5 if final else 0)) * game["multiplier"]
    game["hand_scores"][winner % 2] += points
    game["tricks_won"][winner % 2] += 1
    game["last_trick"] = {"cards": deepcopy(game["trick"]), "winner": winner, "points": points}
    game["trick_history"].append(deepcopy(game["last_trick"]))
    game["trick"] = []
    game["turn"] = winner
    if final:
        _finish_hand(game)
    return game


def next_hand(game):
    if game["phase"] != "hand_end":
        raise ValueError("The next hand is not available.")
    game["dealer"] = (game["dealer"] + 1) % 4
    game["hand_number"] += 1
    _deal(game)
    return game


def apply_action(game, seat, action):
    if not isinstance(action, dict):
        raise ValueError("Action must be an object.")
    kind = action.get("type")
    if kind in ("contract", "choose_contract"):
        return choose_contract(game, seat, action.get("contract"))
    if kind in ("pass", "pass_contract"):
        return pass_contract(game, seat)
    if kind in ("play", "play_card"):
        return play_card(game, seat, action.get("card"))
    if kind == "next_hand":
        return next_hand(game)
    raise ValueError("Unknown action.")


PUBLIC_FIELDS = ("phase", "turn", "forehand", "dealer", "contract", "passed", "scores", "hand_scores", "trick",
                 "last_trick", "hand_number", "tricks_won", "rules", "history", "announcements", "multiplier",
                 "winner", "played_cards", "trick_history")


def public_view(game, seat=None):
    view = {key: deepcopy(game[key]) for key in PUBLIC_FIELDS}
    valid_seat = type(seat) is int and seat in range(4)
    view.update({"hand": list(game["hands"][seat]) if valid_seat else [],
                 "legal_cards": legal_cards(game, seat) if valid_seat else [],
                 "hand_counts": [len(hand) for hand in game["hands"]],
                 "can_pass": bool(valid_seat and game["phase"] == "contract" and game["turn"] == seat and not game["passed"]),
                 "available_contracts": available_contracts(game["rules"])})
    return view


def _contract_value(hand, contract):
    """Hand strength estimate: controls, long suits, trump texture and melds."""
    value = 0.0
    for suit in SUITS:
        cards = [c for c in hand if c[0] == suit]
        if not cards:
            continue
        strengths = {card_strength(c, contract) for c in cards}
        if suit == contract:
            value += len(cards) * 2 + max(0, len(cards) - 2) ** 2
            for card in cards:
                value += {"J": 12, "9": 7, "A": 4, "K": 2}.get(card[1:], 0)
        else:
            for strength in strengths:
                value += max(0, strength - 5) * 1.7
            if 8 in strengths and 7 in strengths:
                value += 4
            if 8 in strengths:
                value += max(0, len(cards) - 2) * 1.5
    if contract in ("obenabe", "undenufe"):
        value *= 1.25
    return value


def _heuristic_card(hand, trick, contract, seat, played):
    """A partnership-aware policy using this seat's own hand and exposed cards."""
    options = _legal(hand, trick, contract)
    if len(options) == 1:
        return options[0]
    unseen = set(DECK) - set(hand) - set(played)
    if not trick:
        def lead_value(card):
            higher = sum(c[0] == card[0] and card_strength(c, contract) > card_strength(card, contract) for c in unseen)
            master = higher == 0
            suit_length = sum(c[0] == card[0] for c in hand)
            return master * 18 + card_points(card, contract) * (0.8 if master else -0.4) + suit_length + (card[0] == contract) * 1.5 - higher
        return max(options, key=lead_value)
    current_winner = trick_winner(trick, contract)
    partner_winning = current_winner % 2 == seat % 2
    last_to_play = len(trick) == 3
    table_points = sum(card_points(p["card"], contract) for p in trick)
    def value(card):
        winner = trick_winner(trick + [{"seat": seat, "card": card}], contract)
        wins = winner == seat
        strength = card_strength(card, contract)
        points = card_points(card, contract)
        if partner_winning:
            if last_to_play:
                return points * 2 - (wins and card[0] == contract) * (strength + 3)
            winner_card = next(p["card"] for p in trick if p["seat"] == current_winner)
            threats = sum(c[0] == winner_card[0] and card_strength(c, contract) > card_strength(winner_card, contract) for c in unseen)
            return points * (1 if threats == 0 else -0.5) - (wins and card[0] == contract) * strength
        if wins:
            return 20 + table_points + points * 0.4 - strength * 0.55 - (card[0] == contract) * 2
        return -points * 1.5 - strength * 0.12 - (card[0] == contract) * 4
    return max(options, key=value)


def _public_constraints(game, own_seat):
    """Known meld cards and voids logically inferable from public trick play."""
    exposed = set(game["played_cards"])
    known = [set() for _ in range(4)]
    forbidden = [set() for _ in range(4)]
    for announcement in game["announcements"]:
        if announcement["type"] == "weis":
            owner = announcement["seat"]
            for meld in announcement.get("melds", []):
                known[owner].update(set(meld["cards"]) - exposed)
    tricks = [trick["cards"] for trick in game["trick_history"]] + [game["trick"]]
    contract = game["contract"]
    for trick in tricks:
        if not trick:
            continue
        led = trick[0]["card"][0]
        for play in trick[1:]:
            if play["card"][0] == led:
                continue
            player = play["seat"]
            if led == contract:
                # A player may decline to play a lone trump jack.
                forbidden[player].update(c for c in DECK if c[0] == led and c != contract + "J")
            elif play["card"][0] != contract:
                # Trumping does not establish a void; a third-suit discard does.
                forbidden[player].update(c for c in DECK if c[0] == led)
    known[own_seat] = set(game["hands"][own_seat])
    return known, forbidden


def _sample_hands(own_hand, seat, counts, exposed, rng, known=None, forbidden=None):
    """Random feasible deal respecting exposed melds and inferred void suits.

    Bipartite matching assigns cards to hand slots. Augmenting paths repair
    greedy collisions instead of silently violating established public facts.
    """
    unknown = list(set(DECK) - set(own_hand) - set(exposed))
    unknown.sort(key=DECK.index)
    hands = [[] for _ in range(4)]
    hands[seat] = list(own_hand)
    known = known or [set() for _ in range(4)]
    forbidden = forbidden or [set() for _ in range(4)]
    for player in range(4):
        if player != seat:
            hands[player] = sorted(known[player], key=DECK.index)
            unknown = [c for c in unknown if c not in known[player]]
    slots = [player for player in range(4) if player != seat
             for _ in range(counts[player] - len(hands[player]))]
    rng.shuffle(slots)
    rng.shuffle(unknown)
    choices = {card: [i for i, player in enumerate(slots) if card not in forbidden[player]] for card in unknown}
    for eligible in choices.values():
        rng.shuffle(eligible)
    unknown.sort(key=lambda c: len(choices[c]))
    assigned = {}
    def place(card, visited):
        for slot in choices[card]:
            if slot in visited:
                continue
            visited.add(slot)
            if slot not in assigned or place(assigned[slot], visited):
                assigned[slot] = card
                return True
        return False
    for card in unknown:
        if not place(card, set()):
            raise ValueError("Public card history is inconsistent.")
    for slot, card in assigned.items():
        hands[slots[slot]].append(card)
    return hands


def _rollout(hands, trick, contract, turn, exposed, candidate, own_seat):
    """Complete an independently sampled hand; return own team's card margin."""
    hands = [list(h) for h in hands]
    trick = [dict(p) for p in trick]
    exposed = list(exposed)
    margin = 0
    first = True
    while any(hands):
        card = candidate if first else _heuristic_card(hands[turn], trick, contract, turn, exposed)
        first = False
        hands[turn].remove(card)
        trick.append({"seat": turn, "card": card})
        exposed.append(card)
        if len(trick) == 4:
            winner = trick_winner(trick, contract)
            points = sum(card_points(p["card"], contract) for p in trick) + (5 if not any(hands) else 0)
            margin += points * (1 if winner % 2 == own_seat % 2 else -1)
            turn = winner
            trick = []
        else:
            turn = (turn + 1) % 4
    return margin


def bot_action(game, seat, difficulty="smart"):
    """Choose without reading opponent cards; smart uses sampled hidden hands.

    Sampling is bounded (12 worlds), is not expert-level search, and makes no
    claim of competition strength. Future rollouts use a public-information
    partnership heuristic for each sampled player's policy.
    """
    if difficulty not in ("smart", "easy"):
        raise ValueError("Unknown bot difficulty.")
    if game["phase"] not in ("contract", "play"):
        raise ValueError("Bots have no action in this phase.")
    _check_turn(game, seat, game["phase"])
    own_hand = list(game["hands"][seat])
    contracts = available_contracts(game["rules"])
    if difficulty == "easy":
        if game["phase"] == "contract":
            return {"type": "contract", "contract": random.choice(contracts)}
        return {"type": "play", "card": random.choice(_legal(own_hand, game["trick"], game["contract"]))}
    if game["phase"] == "contract":
        best = max(contracts, key=lambda c: _contract_value(own_hand, c))
        if not game["passed"] and _contract_value(own_hand, best) < 23:
            return {"type": "pass"}
        return {"type": "contract", "contract": best}
    options = _legal(own_hand, game["trick"], game["contract"])
    if len(options) == 1:
        return {"type": "play", "card": options[0]}
    counts = [len(hand) for hand in game["hands"]]  # Counts are public, contents never read.
    material = "|".join(own_hand + list(game["played_cards"]) + [str(seat), game["contract"]])
    rng = random.Random(int.from_bytes(hashlib.sha256(material.encode()).digest()[:8], "big"))
    known, forbidden = _public_constraints(game, seat)
    values = {card: 0 for card in options}
    for _ in range(12):
        sampled = _sample_hands(own_hand, seat, counts, game["played_cards"], rng, known, forbidden)
        for candidate in options:
            values[candidate] += _rollout(sampled, game["trick"], game["contract"], seat,
                                          game["played_cards"], candidate, seat)
    # A small tactical tie-break preserves masters rather than wasting trumps.
    preferred = _heuristic_card(own_hand, game["trick"], game["contract"], seat, game["played_cards"])
    best = max(options, key=lambda c: (values[c], c == preferred, -card_points(c, game["contract"])))
    return {"type": "play", "card": best}
