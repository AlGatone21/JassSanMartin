# Rules implemented by ASS Jass

## The table

Schieber uses four players in two partnerships: seats 0 and 2 against seats 1 and 3. Each player receives nine cards from a 36-card deck. The app displays French suits (hearts, diamonds, clubs, spades), with ranks 6 through ace. Forehand chooses the contract or passes that decision to their partner; the partner must choose. Forehand leads even after passing. The dealer and forehand rotate between hands.

Contracts are a suit as trump, Obenabe (highest wins without trump), or Undenufe (lowest wins without trump). No-trump contracts can be disabled in custom rules.

## Legal cards

The server enforces following suit, the option to trump, the lone trump jack exemption and the restriction on undertrumping. The UI highlights legal cards. It is legal to play trump while holding the led non-trump suit. A lower trump cannot be played after a stronger trump on a non-trump lead unless the player's entire remaining hand is trump. When trump is led, a player holding only the trump jack may keep it and discard another suit.

These choices follow the [Swisslos Schieber rules](https://www.swisslos.ch/en/jass/informations/jass-rules/schieber-jass.html). Local clubs may use different house rules; verify your event's chosen settings before starting.

## Points and contracts

Normal cards score ace 11, ten 10, king 4, queen 3, jack 2. In trump, the jack scores 20 and nine 14. In Obenabe, eights score 8. In Undenufe, sixes score 11 instead of aces, and eights score 8. The final trick adds 5, giving **157 card points** per hand before bonuses and multipliers. Card ranking and point values follow the [Swisslos championship scoring tables](https://static.swisslos.ch/media/en/swisslos/jass/ssm/official-rules-swiss-schieber-championship.pdf).

The optional multipliers are hearts/diamonds ×1, clubs/spades ×2, Obenabe/Undenufe ×3. Presets provide a simple 1,000-point game, a multiplied 2,500-point game, and a 12-hand tournament game without declaration, marriage or sweep bonuses.

## Automatic bonuses and finishing

With Weis enabled, the engine finds qualifying runs and four-of-a-kind declarations, compares the strongest individual declarations and scores the winning partnership's declarations. Stöck awards 20 for holding trump king and queen; the marriage is credited when both cards have been played. A Match adds 100 for taking all nine tricks when enabled. Applicable contract multipliers also apply to bonuses.

Declarations are automatic in this app. There is no manual declaration window or penalty system for incorrect announcements. In point-target mode, the game checks the target at the **end of each complete hand**. If both partnerships reach the target, the higher total wins; equal totals require another hand. Fixed-hand mode finishes after the configured hand count and may finish in a draw.

This is a club-friendly digital convention. Championship Stöck–Wys–Stich priority and immediate mid-hand claiming are not implemented. A physical score sheet can record the result agreed at your real table, including bonuses.

## Bots

Easy bots play random legal cards. Smart bots evaluate contracts and simulate 12 possible deals consistent with public melds and inferred missing suits. Their rollouts use partnership tactics to preserve strong cards and help a winning partner collect points. They are tactical practice opponents, not tournament-strength AI, and do not look at the other hands.

## Competitions

Round robin pairs every team once, with a bye when necessary. Standings use match points (3 for a win, 1 for a draw), then score difference, points scored and team name. Knockout competitions advance the winner and support byes. Physical knockout ties must be resolved at the table before entering a winning result; a tied digital game offers an extra playoff hand. Physical events accept organizer-entered results. Digital fixtures link to Schieber rooms and post completed room scores back to the competition. Organizers can manage a digital table as spectators, leaving all four seats available for competitors.

The digital rules engine implements Schieber rather than every distinct Jass game. Coiffeur, Differenzler, bidding games and regional negative contracts are outside the digital ruleset.
