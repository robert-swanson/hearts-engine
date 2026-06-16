#!/usr/bin/env python3
"""Unit tests for clients.python.util.probability_table (no server needed).

Covers the two things that make the table correct:

  * the *policy* — a freed/repinned probability is shared across the surviving
    cells in proportion to their existing odds (Bayesian conditioning), never an
    equal split, and
  * the *invariants* — after every update each card's row sums to 1 and each
    player's column sums to their hand size, with known cards reading exactly
    1.0/0.0 and over-constrained inputs raising ContradictionError.

Run directly: ``python3 tests/probability_table_test.py``.
"""

import itertools
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from clients.python.api.types.Card import Card
from clients.python.util.probability_table import ProbabilityTable, ContradictionError


def approx(a, b, tol=1e-6):
    return abs(a - b) < tol


def C(s):
    return Card(s)


# A fixed Hearts-style universe: 3 opponents, 9 unknown cards, 3 cards each.
CARDS = [C(x) for x in ["AS", "KS", "QS", "AH", "KH", "QH", "AD", "KD", "QD"]]
PLAYERS = ["left", "across", "right"]
CAPS = {"left": 3, "across": 3, "right": 3}


def _assert_rows_sum_to_one(t):
    for card in CARDS:
        total = sum(t.distribution(card).values())
        assert approx(total, 1.0), f"row {card} sums to {total}, not 1"


def _assert_columns_sum_to(t, caps):
    # Holds at the *original* hand size: a resolved card counts 1.0 for its owner.
    for player, cap in caps.items():
        total = sum(t.prob_has_one(player, card) for card in CARDS)
        assert approx(total, cap), f"column {player} sums to {total}, not {cap}"


def test_set_prob_shares_proportionally():
    """Repinning a cell reshares the remainder by existing odds, not equally."""
    t = ProbabilityTable(["A", "B", "C", "D"],
                         [C("AS"), C("KS"), C("QS"), C("JS")],
                         capacities={"A": 1, "B": 1, "C": 1, "D": 1})
    t._reconcile = lambda: None                 # isolate the row update from IPF
    t._P[0] = [0.20, 0.30, 0.50, 0.0]
    t._forbidden[0][3] = True
    t.set_prob("A", C("AS"), 0.40)
    row = t._P[0]
    assert approx(row[0], 0.40)
    assert approx(row[1], 0.225) and approx(row[2], 0.375)   # 0.3:0.5 ratio preserved
    assert approx(row[1] / row[2], 0.30 / 0.50)             # proportional, not equal split
    print("PASS: set_prob reshares proportionally (odds preserved)")


def test_rule_out_redistributes_proportionally():
    """Zeroing a cell is the same policy in the limit: [.25,.25,.5,0] -> [0,1/3,2/3,0]."""
    t = ProbabilityTable(["A", "B", "C", "D"],
                         [C("AS"), C("KS"), C("QS"), C("JS")],
                         capacities={"A": 1, "B": 1, "C": 1, "D": 1})
    t._reconcile = lambda: None
    t._P[0] = [0.25, 0.25, 0.50, 0.0]
    t._forbidden[0][3] = True
    t._forbid_raw(0, 0)                          # rule out A
    s = sum(t._P[0])
    t._P[0] = [x / s for x in t._P[0]]           # IPF's row-normalization step
    assert approx(t._P[0][1], 1 / 3) and approx(t._P[0][2], 2 / 3)
    assert approx(t._P[0][0], 0.0) and approx(t._P[0][3], 0.0)
    print("PASS: zeroing redistributes proportionally ([0, 1/3, 2/3, 0])")


def test_default_cards_full_deck():
    """Omitting cards defaults to the full 52-card deck (13 each for 4 players)."""
    t = ProbabilityTable(["N", "E", "S", "W"])
    assert len(t.cards) == 52
    assert approx(t.prob_has_one("N", C("QS")), 0.25)
    for p in ["N", "E", "S", "W"]:
        assert approx(sum(t.prob_has_one(p, c) for c in t.cards), 13.0)
    print("PASS: default cards = full 52-card deck, 13 per player")


def test_init_uniform_and_margins():
    t = ProbabilityTable(PLAYERS, CARDS, CAPS)
    for card in CARDS:
        assert approx(t.prob_has_one("left", card), 1 / 3)
    _assert_rows_sum_to_one(t)
    _assert_columns_sum_to(t, CAPS)
    print("PASS: init is uniform 1/3 with rows=1 and columns=capacity")


def test_assign_makes_known_and_preserves_margins():
    t = ProbabilityTable(PLAYERS, CARDS, CAPS)
    t.assign("left", C("AS"))
    assert t.prob_has_one("left", C("AS")) == 1.0
    assert t.prob_has_one("across", C("AS")) == 0.0
    assert t.prob_has_one("right", C("AS")) == 0.0
    assert C("AS") in t.known_cards() and t.known_cards()[C("AS")] == "left"
    _assert_rows_sum_to_one(t)
    _assert_columns_sum_to(t, CAPS)              # full-hand invariant still 3 each
    unknown = [k for k in CARDS if k != C("AS")]
    assert approx(sum(t.prob_has_one("left", k) for k in unknown), 2.0)  # remaining mass
    print("PASS: assign -> 100%/0%, capacity decremented, margins intact")


def test_propagation_resolves_single_candidate():
    t = ProbabilityTable(PLAYERS, CARDS, CAPS)
    t.rule_out("left", C("KH"))
    t.rule_out("across", C("KH"))
    assert t.prob_has_one("right", C("KH")) == 1.0       # only possible holder
    assert t.known_cards().get(C("KH")) == "right"
    _assert_rows_sum_to_one(t)
    _assert_columns_sum_to(t, CAPS)
    print("PASS: card with a single possible holder auto-resolves to 100%")


def test_play_known_card_removes_it():
    """Playing an already-known card drops it to 0 for everyone; others unchanged."""
    t = ProbabilityTable(PLAYERS, CARDS, CAPS)
    t.assign("left", C("AS"))
    before = {k: t.distribution(k) for k in CARDS if k != C("AS")}
    t.play("left", C("AS"))
    assert t.prob_has_one("left", C("AS")) == 0.0
    assert all(t.prob_has_one(p, C("AS")) == 0.0 for p in PLAYERS)
    assert C("AS") in t.played_cards() and C("AS") not in t.known_cards()
    # No new information about the other cards: their distributions are unchanged.
    for k, dist in before.items():
        for p in PLAYERS:
            assert approx(t.prob_has_one(p, k), dist[p])
    print("PASS: playing a known card -> 0% everywhere, other cards unchanged")


def test_play_unknown_card_reveals_and_reweights():
    """Playing an unknown card reveals the holder and reweights the other cards."""
    t = ProbabilityTable(PLAYERS, CARDS, CAPS)
    t.play("left", C("AS"))                      # AS was unknown (1/3 each)
    assert all(t.prob_has_one(p, C("AS")) == 0.0 for p in PLAYERS)
    assert C("AS") in t.played_cards()
    # left has revealed one of their cards, so among the remaining 8 unknowns they
    # now account for 2, while across/right still account for 3 each.
    rest = [k for k in CARDS if k != C("AS")]
    assert approx(sum(t.prob_has_one("left", k) for k in rest), 2.0)
    assert approx(sum(t.prob_has_one("across", k) for k in rest), 3.0)
    assert approx(sum(t.prob_has_one("right", k) for k in rest), 3.0)
    for k in rest:                               # rows still sum to 1
        assert approx(sum(t.distribution(k).values()), 1.0)
    # left is now *less* likely than the others to hold any given remaining card.
    assert t.prob_has_one("left", C("KS")) < t.prob_has_one("across", C("KS"))
    print("PASS: playing an unknown card reveals holder and reweights the rest")


def test_play_contradictions():
    t = ProbabilityTable(PLAYERS, CARDS, CAPS)
    t.rule_out("left", C("QS"))
    raised = False
    try:
        t.play("left", C("QS"))                  # we had ruled left out of QS
    except ContradictionError:
        raised = True
    assert raised, "playing a ruled-out card should contradict"
    t2 = ProbabilityTable(PLAYERS, CARDS, CAPS)
    t2.assign("right", C("QS"))
    raised = False
    try:
        t2.play("left", C("QS"))                 # QS was known to be right's
    except ContradictionError:
        raised = True
    assert raised, "playing another player's known card should contradict"
    print("PASS: playing a ruled-out / mis-attributed card raises ContradictionError")


def test_prob_has_at_least_one():
    t = ProbabilityTable(PLAYERS, CARDS, CAPS)
    v = t.prob_has_at_least_one("left", [C("AH"), C("KH")])
    assert approx(v, 1 - (2 / 3) ** 2), v        # independence approximation
    # A known card in the set short-circuits to certainty.
    t.assign("left", C("AH"))
    assert t.prob_has_at_least_one("left", [C("AH"), C("QD")]) == 1.0
    assert t.prob_has_at_least_one("left", []) == 0.0
    print("PASS: prob_has_at_least_one (independence approx + known short-circuit)")


def _brute_force_deals(players, cards, caps, forbidden):
    """Enumerate every feasible assignment of cards to players (small cases only)."""
    deals = []
    for combo in itertools.product(players, repeat=len(cards)):
        deal = dict(zip(cards, combo))
        if any(deal[c] in forbidden.get(c, ()) for c in cards):
            continue
        if all(sum(1 for c in cards if deal[c] == p) == caps[p] for p in players):
            deals.append(deal)
    return deals


def test_monte_carlo_matches_brute_force():
    """Sampled marginals match exact enumeration even with a ruled-out (void) cell."""
    players = ["A", "B"]
    cards = [C("2C"), C("3C"), C("4C"), C("5C")]
    t = ProbabilityTable(players, cards, {"A": 2, "B": 2})
    t.rule_out("A", C("2C"))                     # A is void in 2C -> propagates 2C to B
    assert t.known_cards().get(C("2C")) == "B"

    # Brute force the three feasible deals: A holds two of {3C,4C,5C}, B holds 2C + the third.
    deals = _brute_force_deals(players, cards, {"A": 2, "B": 2}, {C("2C"): {"A"}})
    assert len(deals) == 3
    exact = {c: sum(1 for d in deals if d[c] == "A") / len(deals) for c in cards}

    rng = random.Random(12345)
    for c in cards:
        est = t.estimate(lambda d, c=c: d[c] == "A", n=8000, rng=rng)
        assert approx(est, exact[c], tol=0.03), (c, est, exact[c])
    print("PASS: Monte Carlo marginals match brute-force enumeration (with a void)")


def test_exact_beats_independence_for_correlated_query():
    """A holds 2 of {3C,4C,5C}, so they ALWAYS hold >=1 of any two of them.

    Exact answer is 1.0; the independence approximation underestimates it.
    """
    players = ["A", "B"]
    cards = [C("2C"), C("3C"), C("4C"), C("5C")]
    t = ProbabilityTable(players, cards, {"A": 2, "B": 2})
    t.rule_out("A", C("2C"))
    rng = random.Random(7)
    exact = t.prob_has_at_least_one_exact("A", [C("3C"), C("4C")], n=8000, rng=rng)
    approxd = t.prob_has_at_least_one("A", [C("3C"), C("4C")])
    assert approx(exact, 1.0, tol=0.001), exact          # genuinely certain
    assert approx(approxd, 1 - (1 / 3) ** 2, tol=0.02), approxd  # 8/9, the biased guess
    assert exact > approxd + 0.05
    print("PASS: exact joint query (1.0) beats independence approx (~0.889)")


def test_sampled_deals_are_valid():
    """Every sampled deal respects capacities and ruled-out cells."""
    t = ProbabilityTable(PLAYERS, CARDS, CAPS)
    t.rule_out("left", C("AH"))
    t.rule_out("left", C("KH"))
    t.play("right", C("AS"))
    rng = random.Random(99)
    for deal, weight in t.sample_deals(200, rng=rng):
        assert weight > 0.0
        assert deal[C("AS")] is None                     # played card held by nobody
        assert deal[C("AH")] != "left" and deal[C("KH")] != "left"   # voids respected
        held = [c for c in CARDS if deal.get(c) is not None]
        for p in PLAYERS:                                 # capacities respected
            assert sum(1 for c in held if deal[c] == p) == {"left": 3, "across": 3, "right": 2}[p]
    print("PASS: sampled deals respect voids, played cards, and capacities")


def test_contradiction_detected():
    t = ProbabilityTable(PLAYERS, CARDS, CAPS)
    raised = False
    try:
        for p in PLAYERS:
            t.rule_out(p, C("QD"))               # nobody can hold QD -> infeasible
    except ContradictionError:
        raised = True
    assert raised, "expected ContradictionError when a card has no possible holder"
    print("PASS: over-constrained input raises ContradictionError")


def test_capacity_validation():
    raised = False
    try:
        ProbabilityTable(PLAYERS, CARDS, {"left": 3, "across": 3, "right": 2})  # sums to 8, not 9
    except ValueError:
        raised = True
    assert raised, "expected ValueError when capacities do not sum to #cards"
    print("PASS: capacities must sum to the number of cards")


def run():
    test_set_prob_shares_proportionally()
    test_rule_out_redistributes_proportionally()
    test_default_cards_full_deck()
    test_init_uniform_and_margins()
    test_assign_makes_known_and_preserves_margins()
    test_propagation_resolves_single_candidate()
    test_play_known_card_removes_it()
    test_play_unknown_card_reveals_and_reweights()
    test_play_contradictions()
    test_monte_carlo_matches_brute_force()
    test_exact_beats_independence_for_correlated_query()
    test_sampled_deals_are_valid()
    test_prob_has_at_least_one()
    test_contradiction_detected()
    test_capacity_validation()
    print("ALL PASS: probability table")


if __name__ == "__main__":
    run()
