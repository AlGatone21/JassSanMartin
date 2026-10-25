"""Rules regression tests and complete games, independent of Flask or storage."""

import copy
import json
import random
import unittest

from jass.engine import (
    CONTRACTS, DECK, apply_action, bot_action, card_points, choose_contract,
    find_melds, legal_cards, new_game, next_hand, normalize_rules,
    pass_contract, play_card, public_view, trick_winner,
    _finish_hand, _public_constraints, _sample_hands,
)


class RulesTests(unittest.TestCase):
    def table(self, hand, trick, contract="H", seat=1):
        game = new_game({"weis": False, "stock": False, "match_bonus": False}, seed=42)
        game.update(phase="play", turn=seat, contract=contract, trick=trick)
        game["hands"][seat] = hand
        return game

    def test_deal_has_36_unique_cards_and_json_roundtrip(self):
        game = new_game(seed=15)
        self.assertEqual(sorted(sum(game["hands"], [])), sorted(DECK))
        self.assertEqual([len(h) for h in game["hands"]], [9, 9, 9, 9])
        self.assertEqual(json.loads(json.dumps(game)), game)
        self.assertEqual(game["turn"], 0)

    def test_follow_suit_or_trump(self):
        game = self.table(["H6", "D6", "D7", "SA"], [{"seat": 0, "card": "DA"}])
        self.assertEqual(set(legal_cards(game, 1)), {"H6", "D6", "D7"})
        self.assertEqual(legal_cards(game, 0), [])

    def test_no_undertrumping_even_if_void(self):
        game = self.table(["H6", "HJ", "SA"], [{"seat": 3, "card": "DA"}, {"seat": 0, "card": "H9"}])
        self.assertEqual(set(legal_cards(game, 1)), {"HJ", "SA"})
        game["hands"][1] = ["H6", "HJ"]
        self.assertEqual(set(legal_cards(game, 1)), {"H6", "HJ"})

    def test_undertrump_not_allowed_while_following(self):
        game = self.table(["H6", "D7", "SA"], [{"seat": 3, "card": "DA"}, {"seat": 0, "card": "H9"}])
        self.assertEqual(legal_cards(game, 1), ["D7"])

    def test_lone_trump_jack_exception(self):
        game = self.table(["HJ", "SA"], [{"seat": 0, "card": "H6"}])
        self.assertEqual(set(legal_cards(game, 1)), {"HJ", "SA"})
        game["hands"][1].append("H7")
        self.assertEqual(set(legal_cards(game, 1)), {"HJ", "H7"})

    def test_can_undertrump_when_trump_was_led(self):
        game = self.table(["H6", "H7", "SA"], [{"seat": 0, "card": "HJ"}])
        self.assertEqual(set(legal_cards(game, 1)), {"H6", "H7"})

    def test_no_trump_follow_and_winners(self):
        game = self.table(["D6", "SA"], [{"seat": 0, "card": "DA"}], "undenufe")
        self.assertEqual(legal_cards(game, 1), ["D6"])
        cards = [{"seat": 0, "card": "DA"}, {"seat": 1, "card": "D6"}, {"seat": 2, "card": "H6"}, {"seat": 3, "card": "D7"}]
        self.assertEqual(trick_winner(cards, "undenufe"), 1)
        self.assertEqual(trick_winner(cards, "obenabe"), 0)
        self.assertEqual(trick_winner(cards, "H"), 2)

    def test_card_points_conserved_for_all_contracts(self):
        for contract in CONTRACTS:
            self.assertEqual(sum(card_points(c, contract) for c in DECK) + 5, 157)
        self.assertEqual(card_points("H9", "H"), 14)
        self.assertEqual(card_points("HJ", "H"), 20)
        self.assertEqual(card_points("HA", "undenufe"), 0)
        self.assertEqual(card_points("H6", "undenufe"), 11)

    def test_contract_pass_only_once_and_forehand_starts(self):
        game = new_game(seed=10)
        pass_contract(game, 0)
        self.assertEqual(game["turn"], 2)
        with self.assertRaises(ValueError):
            pass_contract(game, 2)
        choose_contract(game, 2, "undenufe")
        self.assertEqual(game["turn"], 0)

    def test_invalid_action_does_not_mutate(self):
        game = new_game(seed=0)
        before = copy.deepcopy(game)
        with self.assertRaises(ValueError):
            choose_contract(game, 1, "H")
        self.assertEqual(before, game)
        with self.assertRaises(ValueError):
            choose_contract(game, 0, "invalid")
        self.assertEqual(before, game)
        choose_contract(game, 0, "H")
        before = copy.deepcopy(game)
        with self.assertRaises(ValueError):
            play_card(game, 0, "FA")
        self.assertEqual(before, game)

    def test_rule_validation(self):
        self.assertEqual(normalize_rules({"target": 2500})["target_score"], 2500)
        for rules in ({"target_score": True}, {"max_hands": -1}, {"stock": "false"}, {"bot_difficulty": "expert"}):
            with self.assertRaises(ValueError):
                normalize_rules(rules)

    def test_public_view_hides_opponents_and_stock_owner(self):
        game = new_game(seed=7)
        choose_contract(game, 0, "H")
        view = public_view(game, 0)
        self.assertEqual(view["hand"], game["hands"][0])
        for key in ("hands", "stock_owner", "stock_played", "seed"):
            self.assertNotIn(key, view)
        self.assertEqual(public_view(game)["hand"], [])
        self.assertEqual(public_view(game)["legal_cards"], [])
        view["scores"][0] = 99999
        self.assertEqual(game["scores"][0], 0)

    def test_meld_points_and_cross_melds(self):
        melds = find_melds(["HA", "HK", "HQ", "HJ", "H10", "DK", "CK", "SK", "S6"], "H")
        self.assertEqual(sorted(m["points"] for m in melds), [100, 100])
        self.assertEqual(find_melds(["HJ", "DJ", "CJ", "SJ"], "H")[0]["points"], 200)
        self.assertEqual(find_melds(["H9", "D9", "C9", "S9"], "H")[0]["points"], 150)
        self.assertEqual(find_melds(list(DECK[:9]), "H")[0]["points"], 300)

    def test_weis_only_winning_team_counts_all_their_melds(self):
        game = new_game({"stock": False}, seed=0)
        game["hands"] = [
            ["HA", "HK", "HQ", "H6", "D6", "D8", "C6", "C8", "S6"],
            ["DJ", "D10", "D9", "D7", "C7", "C9", "S7", "S9", "HJ"],
            ["SA", "SK", "SQ", "S8", "H7", "H8", "H9", "H10", "CJ"],
            ["DA", "DK", "DQ", "CA", "CK", "CQ", "C10", "S10", "SJ"],
        ]
        choose_contract(game, 0, "H")
        # Seat0's highest run A wins over seat3's equally high nontrump run;
        # both seat0's and partner seat2's sequences score.
        self.assertEqual({a["team"] for a in game["announcements"]}, {0})
        self.assertEqual(game["hand_scores"][1], 0)
        self.assertGreaterEqual(game["hand_scores"][0], 40)

    def test_stock_awarded_when_second_card_played(self):
        game = self.table(["HK", "HQ", "H6"], [], seat=0)
        game["rules"]["stock"] = True
        game["stock_owner"] = 0
        play_card(game, 0, "HK")
        self.assertEqual(game["hand_scores"][0], 0)
        game["turn"] = 0
        game["trick"] = []
        play_card(game, 0, "HQ")
        self.assertEqual(game["hand_scores"][0], 20)
        self.assertEqual(game["announcements"][-1]["type"], "stock")

    def test_full_hands_points_rotation_and_finish(self):
        for contract in CONTRACTS:
            game = new_game({"weis": False, "stock": False, "match_bonus": False,
                             "max_hands": 2, "multipliers": True}, seed=0)
            choose_contract(game, 0, contract)
            for _ in range(36):
                seat = game["turn"]
                apply_action(game, seat, bot_action(game, seat, "easy"))
            self.assertEqual(game["phase"], "hand_end")
            self.assertEqual(sum(game["scores"]), 157 * game["multiplier"])
            self.assertEqual(sum(game["tricks_won"]), 9)
            self.assertEqual(len(game["trick_history"]), 9)
            next_hand(game)
            self.assertEqual(game["forehand"], 1)
            self.assertEqual(game["dealer"], 0)
            self.assertEqual(game["hand_number"], 2)
            while game["phase"] in ("contract", "play"):
                seat = game["turn"]
                apply_action(game, seat, bot_action(game, seat, "easy"))
            self.assertEqual(game["phase"], "finished")
            with self.assertRaises(ValueError):
                next_hand(game)

    def test_smart_bot_does_not_use_opponent_hands(self):
        game = new_game({"weis": False}, seed=2)
        choose_contract(game, 0, "H")
        original = bot_action(game, 0)
        altered = copy.deepcopy(game)
        altered["hands"][1], altered["hands"][3] = altered["hands"][3], altered["hands"][1]
        self.assertEqual(bot_action(altered, 0), original)
        self.assertIn(original["card"], legal_cards(game, 0))

    def test_smart_bots_complete_a_game(self):
        game = new_game({"max_hands": 1}, seed=18)
        count = 0
        while game["phase"] in ("contract", "play"):
            seat = game["turn"]
            action = bot_action(game, seat)
            apply_action(game, seat, action)
            count += 1
            self.assertLess(count, 40)
        self.assertEqual(game["phase"], "finished")
        self.assertEqual(len(game["played_cards"]), 36)
        self.assertEqual(sum(game["tricks_won"]), 9)

    def test_target_game_tie_continues_but_fixed_hands_can_draw(self):
        target = new_game({"target_score": 100, "match_bonus": False}, seed=0)
        target["scores"] = [100, 100]
        target["hand_scores"] = [0, 0]
        _finish_hand(target)
        self.assertEqual(target["phase"], "hand_end")
        self.assertIsNone(target["winner"])
        next_hand(target)
        target["hand_scores"] = [1, 0]
        _finish_hand(target)
        self.assertEqual(target["phase"], "finished")
        self.assertEqual(target["winner"], 0)
        fixed = new_game({"max_hands": 1, "match_bonus": False}, seed=0)
        fixed["hand_scores"] = [100, 100]
        _finish_hand(fixed)
        self.assertEqual(fixed["phase"], "finished")
        self.assertIsNone(fixed["winner"])

    def test_public_void_inference_distinguishes_trumping_and_jack_exception(self):
        game = new_game(seed=0)
        game["contract"] = "H"
        game["trick_history"] = [
            {"cards": [{"seat": 0, "card": "DA"}, {"seat": 1, "card": "H6"},
                       {"seat": 2, "card": "S6"}, {"seat": 3, "card": "DK"}]},
            {"cards": [{"seat": 0, "card": "HA"}, {"seat": 1, "card": "D6"},
                       {"seat": 2, "card": "H7"}, {"seat": 3, "card": "HK"}]},
        ]
        _, forbidden = _public_constraints(game, 0)
        self.assertNotIn("DQ", forbidden[1])  # Earlier trump did not prove void.
        self.assertIn("DQ", forbidden[2])     # Third-suit discard did prove void.
        self.assertIn("H9", forbidden[1])
        self.assertNotIn("HJ", forbidden[1])  # A lone Puur can be held back.

    def test_sampled_worlds_preserve_revealed_melds_and_inferred_voids(self):
        game = new_game({"max_hands": 1}, seed=22)
        # Use legal play to generate consistent public constraints.
        while game["phase"] == "contract":
            apply_action(game, game["turn"], bot_action(game, game["turn"]))
        for _ in range(20):
            seat = game["turn"]
            if game["phase"] != "play":
                break
            known, forbidden = _public_constraints(game, seat)
            counts = [len(hand) for hand in game["hands"]]
            sampled = _sample_hands(game["hands"][seat], seat, counts, game["played_cards"],
                                    random.Random(15), known, forbidden)
            self.assertEqual([len(hand) for hand in sampled], counts)
            self.assertEqual(len(set(sum(sampled, []) + game["played_cards"])), 36)
            for player in range(4):
                self.assertTrue(known[player] <= set(sampled[player]))
                self.assertFalse(set(sampled[player]) & forbidden[player])
            apply_action(game, seat, bot_action(game, seat))


if __name__ == "__main__":
    unittest.main()
