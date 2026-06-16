"""Probability that each player holds each card.

A ``ProbabilityTable`` tracks, for a fixed universe of *cards* and *players*, the
marginal probability that a given player holds a given card. Conceptually it is a
matrix with one row per card and one column per player, maintaining two margins:

  * every (unresolved) card's row sums to 1   — the card is held by exactly one of
    the tracked players, and
  * every player's column sums to that player's capacity — the number of tracked
    cards they currently hold.

Updates come in three flavours:

  * ``assign(player, card)``  — a *known* fact: this player holds this card. The
    card leaves the unknown pool, the player's capacity drops by one, and every
    future query for it returns 1.0 (or 0.0 for the other players).
  * ``rule_out(player, card)`` — a known fact: this player does *not* hold this
    card (e.g. they failed to follow suit, so they are void in it).
  * ``set_prob(player, card, value)`` — a soft observation.
  * ``reassign(player, card)`` — move a known card to a new holder (passing).
  * ``play(player, card)`` — a card is played and leaves every hand.

After any update the table (a) runs cheap logical constraint propagation to turn
forced situations into certainties (a card with a single possible holder; a
player whose remaining capacity exactly fills, or empties, their candidates),
then (b) restores both margins by **Iterative Proportional Fitting** (a.k.a. the
Sinkhorn–Knopp / RAS algorithm) — alternately rescaling columns to their
capacities and rows to 1 until both hold. IPF is multiplicative, so a cell driven
to zero stays zero forever; "this player can't have this card" is preserved for
free.

Caveat for multi-card queries: cells within a column are *negatively* correlated
(a fixed hand size is sampling without replacement), so
``prob_has_at_least_one`` assumes independence and is an approximation. For an
exact joint answer you would sample valid deals instead.

The implementation is deliberately dependency-free pure Python — the table is
tiny (≤ 52 × 4) and IPF converges in a few sweeps, so numpy would only add a
runtime dependency for no real gain. ``to_dataframe()` offers an optional pandas
view for debugging if pandas is installed.
"""

import random
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple

from clients.python.api.types.Card import Card
from clients.python.api.types.PlayerTagSession import PlayerTagSession


# A sampled deal maps every tracked card to its holder (None once the card is played).
Deal = Dict[Card, Optional[PlayerTagSession]]


class ContradictionError(ValueError):
    """Raised when updates leave no valid assignment of cards to players."""


# Convergence controls for the IPF sweep. The system is small and well behaved,
# so this is plenty of headroom.
_IPF_MAX_ITERS = 1000
_IPF_TOL = 1e-12
_EPS = 1e-9


class ProbabilityTable:
    def __init__(self, players: List[PlayerTagSession], cards: Optional[Iterable[Card]] = None,
                 capacities: Optional[Dict[PlayerTagSession, int]] = None):
        """Build a table over ``players`` and ``cards``.

        ``cards`` defaults to the full 52-card deck. ``capacities`` maps each
        player to the number of tracked cards they hold; the values must sum to
        ``len(cards)``. If omitted, the cards are assumed split evenly
        (``len(cards)`` must then divide by ``len(players)``).
        """
        self.players: List[PlayerTagSession] = list(players)
        self.cards: List[Card] = list(cards) if cards is not None else Card.make_deck()
        self._pj: Dict[PlayerTagSession, int] = {p: j for j, p in enumerate(self.players)}
        self._ci: Dict[Card, int] = {c: i for i, c in enumerate(self.cards)}
        if len(self._pj) != len(self.players):
            raise ValueError("duplicate player in players")
        if len(self._ci) != len(self.cards):
            raise ValueError("duplicate card in cards")

        n, m = len(self.cards), len(self.players)
        cap: List[float]
        if capacities is None:
            if m == 0 or n % m != 0:
                raise ValueError("cannot split %d cards evenly across %d players" % (n, m))
            cap = [n / m] * m
        else:
            cap = [float(capacities[p]) for p in self.players]
        if abs(sum(cap) - n) > _EPS:
            raise ValueError("capacities sum to %g but there are %d cards" % (sum(cap), n))

        self._hand: List[float] = list(cap)                # current hand size per player
        self._cap: List[float] = list(cap)                 # remaining unknown capacity (= hand - #resolved)
        self._P: List[List[float]] = [[cap[j] / n for j in range(m)] for _ in range(n)]
        # _void: structural rule-outs (permanent). _forbidden: _void plus capacity-derived
        # forbids that propagation adds and that a later pass may need to undo.
        self._forbidden: List[List[bool]] = [[False] * m for _ in range(n)]
        self._void: List[List[bool]] = [[False] * m for _ in range(n)]
        self._resolved: Dict[Card, PlayerTagSession] = {}  # card -> player known to hold it
        self._played: Set[Card] = set()                    # cards out of play (held by nobody)
        self._settle()

    # ── updates ────────────────────────────────────────────────────────────
    def assign(self, player: PlayerTagSession, card: Card) -> None:
        """Record the known fact that ``player`` holds ``card``."""
        i, j = self._idx(card), self._col(player)
        prior = self._resolved.get(card)
        self._reject_if_played(card)
        if prior is not None:
            if prior != player:
                raise ContradictionError("%r already assigned to %r, not %r"
                                         % (card, prior, player))
            return
        if self._forbidden[i][j]:
            raise ContradictionError("%r was ruled out for %r" % (card, player))
        self._assign_raw(j, i)
        self._settle()

    def rule_out(self, player: PlayerTagSession, card: Card) -> None:
        """Record the known fact that ``player`` does not hold ``card``."""
        i, j = self._idx(card), self._col(player)
        self._reject_if_played(card)
        if self._resolved.get(card) == player:
            raise ContradictionError("%r is known to be held by %r" % (card, player))
        if self._void[i][j]:
            return
        self._void[i][j] = True          # structural: never lifted by capacity changes
        self._forbid_raw(j, i)
        self._settle()

    def play(self, player: PlayerTagSession, card: Card) -> None:
        """Record that ``player`` played ``card``: it leaves play for good.

        Afterwards every ``prob_has_one(*, card)`` is 0.0 — nobody holds it. If
        the card was previously unknown, the play *reveals* that this player held
        it, so their remaining capacity drops by one and the other unknown cards
        are reweighted accordingly. Playing a card the model had ruled out for
        this player (or assigned to another) raises ContradictionError.
        """
        i, j = self._idx(card), self._col(player)
        if card in self._played:
            raise ContradictionError("%r has already been played" % (card,))
        owner = self._resolved.get(card)
        if owner is not None and owner != player:
            raise ContradictionError("%r was held by %r, but %r played it"
                                     % (card, owner, player))
        if owner is None and self._void[i][j]:
            raise ContradictionError("%r was ruled out for %r, but they played it"
                                     % (card, player))
        if owner is not None:
            del self._resolved[card]     # a known card simply leaves the hand
        self._hand[j] -= 1.0             # the player holds one fewer card now
        self._played.add(card)
        for jj in range(len(self.players)):
            self._P[i][jj] = 0.0
            self._forbidden[i][jj] = True
        self._recompute_cap()
        self._settle()

    def reassign(self, player: PlayerTagSession, card: Card) -> None:
        """Change a card's known holder to ``player`` (e.g. when you pass it).

        Unlike ``assign``, this is allowed even when the card is already known to
        be held by someone else — that is exactly the passing case. Hand sizes are
        held fixed (you pass three and receive three), so the previous holder
        regains an unknown slot for the card they will receive and the new holder
        gives up one. The other unknown cards are reweighted accordingly. Use this
        only for an authoritative ownership change; for *learning* a holder use
        ``assign``, which stays strict and rejects conflicts.
        """
        self._reject_if_played(card)
        i, j = self._idx(card), self._col(player)
        prior = self._resolved.get(card)
        if prior == player:
            return
        if self._void[i][j]:
            self._void[i][j] = False     # we are giving this card to player; any prior void is moot
        if prior is None:
            self._assign_raw(j, i)       # card was unknown: this just learns the holder
        else:
            self._resolved[card] = player  # row already collapsed; move the resolution
            self._recompute_cap()
            self._reenable_player(self._col(prior))  # the old holder regained an unknown slot
        self._settle()

    def set_prob(self, player: PlayerTagSession, card: Card, value: float) -> None:
        """Pin a soft probability that ``player`` holds ``card`` and rebalance.

        The card's other (non-forbidden) cells keep their relative odds while
        sharing the remaining ``1 - value`` — i.e. Bayesian conditioning, not an
        equal split — before margins are restored.
        """
        if not 0.0 <= value <= 1.0:
            raise ValueError("probability must be in [0, 1]")
        i, j = self._idx(card), self._col(player)
        self._reject_if_played(card)
        if self._resolved.get(card) is not None:
            raise ContradictionError("%r is already known; clear it before set_prob" % (card,))
        if value == 0.0:
            self.rule_out(player, card)
            return
        if self._forbidden[i][j]:
            raise ContradictionError("%r was ruled out for %r" % (card, player))
        row = self._P[i]
        others = sum(row) - row[j]
        if others > _EPS:
            scale = (1.0 - value) / others
            for jj in range(len(self.players)):
                if jj != j:
                    row[jj] *= scale
        row[j] = value
        self._settle()

    # ── queries ────────────────────────────────────────────────────────────
    def prob_has_one(self, player: PlayerTagSession, card: Card) -> float:
        """Probability that ``player`` holds ``card`` (1.0/0.0 once known, 0.0 once played)."""
        i, j = self._idx(card), self._col(player)
        if card in self._played:
            return 0.0
        owner = self._resolved.get(card)
        if owner is not None:
            return 1.0 if owner == player else 0.0
        return self._P[i][j]

    def prob_has_at_least_one(self, player: PlayerTagSession, cards: List[Card]) -> float:
        """Probability that ``player`` holds at least one of ``cards``.

        Assumes the per-card events are independent. They are in fact mildly
        (negatively) correlated through the player's fixed hand size, so treat
        this as a close approximation; use ``prob_has_at_least_one_exact`` (Monte
        Carlo) when the correlation matters.
        """
        p_none = 1.0
        for card in cards:
            p = self.prob_has_one(player, card)
            if p >= 1.0 - _EPS:
                return 1.0
            p_none *= (1.0 - p)
        return 1.0 - p_none

    def distribution(self, card: Card) -> Dict[PlayerTagSession, float]:
        """Map of player -> probability of holding ``card`` (sums to 1)."""
        return {p: self.prob_has_one(p, card) for p in self.players}

    def known_cards(self) -> Dict[Card, PlayerTagSession]:
        """Cards still in a hand whose holder is known, mapped to that player."""
        return dict(self._resolved)

    def played_cards(self) -> Set[Card]:
        """Cards that have been played and are out of every hand."""
        return set(self._played)

    # ── Monte Carlo (exact joint queries) ────────────────────────────────────
    def sample_deals(self, n: int, rng: Optional[random.Random] = None
                     ) -> List[Tuple[Deal, float]]:
        """Draw ``n`` complete valid deals, each with an importance weight.

        A *deal* maps every tracked card to the player holding it (known cards to
        their owner, played cards to ``None``, unknown cards to a sampled holder),
        always respecting capacities and ruled-out cells. Cards are filled
        most-constrained-first and each is given to a still-eligible player with
        probability proportional to that player's remaining capacity; dead ends
        are rejected and redrawn.

        Without ruled-out cells that scheme is already uniform; with them it is
        biased, so each deal carries weight ``1 / P(generated)``. Feeding (deal,
        weight) pairs to ``estimate`` yields a self-normalized importance-sampling
        estimate of the *uniform* distribution over feasible deals. See
        ``estimate`` for the typical entry point.
        """
        rng = rng or random.Random()
        out: List[Tuple[Deal, float]] = []
        attempts, limit = 0, n * 100 + 100
        while len(out) < n and attempts < limit:
            attempts += 1
            drawn = self._sample_one_deal(rng)
            if drawn is not None:
                deal, p = drawn
                out.append((deal, 1.0 / p))
        if len(out) < n:
            raise RuntimeError(
                "drew only %d of %d deals in %d attempts; constraints may be too tight"
                % (len(out), n, attempts))
        return out

    def estimate(self, predicate: Callable[[Deal], bool],
                 n: int = 10000, rng: Optional[random.Random] = None) -> float:
        """Probability that ``predicate(deal)`` holds, over uniform feasible deals.

        Unlike the marginal-based queries this captures correlations between
        cards exactly (in the Monte Carlo limit), e.g.
        ``estimate(lambda d: d[QS] == p and d[KS] == p)``.
        """
        samples = self.sample_deals(n, rng)
        denom = sum(w for _, w in samples)
        if denom <= 0.0:
            return 0.0
        numer = sum(w for deal, w in samples if predicate(deal))
        return numer / denom

    def prob_has_at_least_one_exact(self, player: PlayerTagSession, cards: List[Card],
                                    n: int = 10000,
                                    rng: Optional[random.Random] = None) -> float:
        """Exact (sampled) counterpart to ``prob_has_at_least_one``.

        Accounts for the negative correlation between cards in a hand that the
        independence-based ``prob_has_at_least_one`` ignores.
        """
        targets = list(cards)
        if not targets:
            return 0.0
        return self.estimate(lambda deal: any(deal.get(c) == player for c in targets), n, rng)

    def _sample_one_deal(self, rng: random.Random) -> Optional[Tuple[Deal, float]]:
        """One forward sampling pass. Returns (deal, generation_prob) or None on a dead end."""
        m = len(self.players)
        active: List[int] = [i for i in range(len(self.cards)) if self._is_active(i)]
        cap: List[int] = [int(round(c)) for c in self._cap]
        allowed: Dict[int, List[int]] = {
            i: [j for j in range(m) if not self._forbidden[i][j]] for i in active}

        assigned: Dict[int, int] = {}
        remaining: Set[int] = set(active)
        gen_p = 1.0
        while remaining:
            # Most-constrained card first (fewest still-eligible players).
            pick_i: Optional[int] = None
            pick_feas: Optional[List[int]] = None
            for i in remaining:
                feas = [j for j in allowed[i] if cap[j] > 0]
                if not feas:
                    return None                          # dead end → reject
                if pick_feas is None or len(feas) < len(pick_feas):
                    pick_i, pick_feas = i, feas
                    if len(feas) == 1:
                        break
            # Choose proportional to remaining capacity.
            total = sum(cap[j] for j in pick_feas)
            r = rng.random() * total
            acc, chosen = 0, pick_feas[-1]
            for j in pick_feas:
                acc += cap[j]
                if r <= acc:
                    chosen = j
                    break
            gen_p *= cap[chosen] / total
            assigned[pick_i] = chosen
            cap[chosen] -= 1
            remaining.discard(pick_i)

        deal: Deal = {}
        for card, owner in self._resolved.items():
            deal[card] = owner
        for card in self._played:
            deal[card] = None
        for i, j in assigned.items():
            deal[self.cards[i]] = self.players[j]
        return deal, gen_p

    # ── internals ────────────────────────────────────────────────────────────
    def _idx(self, card: Card) -> int:
        try:
            return self._ci[card]
        except KeyError:
            raise KeyError("card %r is not tracked by this table" % (card,))

    def _col(self, player: PlayerTagSession) -> int:
        try:
            return self._pj[player]
        except KeyError:
            raise KeyError("player %r is not tracked by this table" % (player,))

    def _is_active(self, i: int) -> bool:
        """True if card ``i`` is still unknown (not yet resolved or played)."""
        card = self.cards[i]
        return card not in self._resolved and card not in self._played

    def _reject_if_played(self, card: Card) -> None:
        if card in self._played:
            raise ContradictionError("%r has already been played" % (card,))

    def _assign_raw(self, j: int, i: int) -> None:
        self._resolved[self.cards[i]] = self.players[j]
        for jj in range(len(self.players)):
            self._P[i][jj] = 0.0
            self._forbidden[i][jj] = True
        self._recompute_cap()

    def _recompute_cap(self) -> None:
        """Remaining unknown capacity = current hand size minus cards already known to be held."""
        counts = [0] * len(self.players)
        for owner in self._resolved.values():
            counts[self._pj[owner]] += 1
        for j in range(len(self.players)):
            self._cap[j] = self._hand[j] - counts[j]

    def _forbid_raw(self, j: int, i: int) -> None:
        self._forbidden[i][j] = True
        self._P[i][j] = 0.0

    def _reenable_player(self, j: int) -> None:
        """Lift capacity-derived (non-structural) forbids for player ``j``.

        Called when a pass returns capacity to ``j``: cards propagation had ruled
        out only because ``j`` was momentarily full are eligible again, so clear
        those forbids and reseed a positive probability for IPF to redistribute.
        """
        n = len(self.cards)
        for i in range(n):
            if not self._is_active(i):
                continue
            if self._forbidden[i][j] and not self._void[i][j]:
                self._forbidden[i][j] = False
                self._P[i][j] = self._cap[j] / n

    def _settle(self) -> None:
        self._propagate()
        self._reconcile()

    def _propagate(self) -> None:
        """Apply logical certainties to a fixpoint (cheap, exact deductions)."""
        n, m = len(self.cards), len(self.players)
        changed = True
        while changed:
            changed = False
            # A card with a single possible holder is held by them.
            for i in range(n):
                if not self._is_active(i):
                    continue
                candidates = [j for j in range(m) if not self._forbidden[i][j]]
                if not candidates:
                    raise ContradictionError("%r can be held by no player" % (self.cards[i],))
                if len(candidates) == 1:
                    self._assign_raw(candidates[0], i)
                    changed = True
            # Per-player capacity vs. the cards they could still hold.
            for j in range(m):
                cap = self._cap[j]
                cand = [i for i in range(n)
                        if self._is_active(i) and not self._forbidden[i][j]]
                if cap < -_EPS or cap - len(cand) > _EPS:
                    raise ContradictionError(
                        "player %r needs %g cards but has %d candidates"
                        % (self.players[j], cap, len(cand)))
                if cap <= _EPS and cand:                    # no room left → rule out the rest
                    for i in cand:
                        self._forbid_raw(j, i)
                    changed = True
                elif abs(cap - len(cand)) < _EPS and cand:  # must take all candidates
                    for i in cand:
                        if self._is_active(i) and not self._forbidden[i][j]:
                            self._assign_raw(j, i)
                    changed = True

    def _reconcile(self) -> None:
        """Iterative Proportional Fitting over the still-unknown rows."""
        rows = [i for i in range(len(self.cards)) if self._is_active(i)]
        if not rows:
            return
        m = len(self.players)
        for _ in range(_IPF_MAX_ITERS):
            # Scale columns to their capacities.
            for j in range(m):
                col_sum = sum(self._P[i][j] for i in rows)
                if col_sum > _EPS:
                    factor = self._cap[j] / col_sum
                    for i in rows:
                        self._P[i][j] *= factor
            # Scale rows to 1.
            for i in rows:
                row_sum = sum(self._P[i])
                if row_sum > _EPS:
                    inv = 1.0 / row_sum
                    for j in range(m):
                        self._P[i][j] *= inv
            # Converged once columns are within tolerance (rows were just set).
            if max(abs(sum(self._P[i][j] for i in rows) - self._cap[j])
                   for j in range(m)) < _IPF_TOL:
                break

    # ── debugging helpers ────────────────────────────────────────────────────
    def to_dataframe(self) -> "pandas.DataFrame":  # noqa: F821  (lazy optional dep)
        """Return a labelled pandas DataFrame view (lazy import; debug only)."""
        import pandas as pd  # optional dependency, imported on demand
        data = {p: [self.prob_has_one(p, c) for c in self.cards] for p in self.players}
        return pd.DataFrame(data, index=[str(c) for c in self.cards])

    def __repr__(self) -> str:
        return "ProbabilityTable(%d cards, %d players, %d known)" % (
            len(self.cards), len(self.players), len(self._resolved))
