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


def test_prob_has_at_least_one():
    t = ProbabilityTable(PLAYERS, CARDS, CAPS)
    v = t.prob_has_at_least_one("left", [C("AH"), C("KH")])
    assert approx(v, 1 - (2 / 3) ** 2), v        # independence approximation
    # A known card in the set short-circuits to certainty.
    t.assign("left", C("AH"))
    assert t.prob_has_at_least_one("left", [C("AH"), C("QD")]) == 1.0
    assert t.prob_has_at_least_one("left", []) == 0.0
    print("PASS: prob_has_at_least_one (independence approx + known short-circuit)")


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
    test_init_uniform_and_margins()
    test_assign_makes_known_and_preserves_margins()
    test_propagation_resolves_single_candidate()
    test_prob_has_at_least_one()
    test_contradiction_detected()
    test_capacity_validation()
    print("ALL PASS: probability table")


if __name__ == "__main__":
    run()
