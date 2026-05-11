"""
Tim-Claude Hearts AI.

Phase 1 — heuristic "Counter" with thorough state tracking:
  played-cards, voids, hearts-broken, score-aware moon offense/defense.

Phase 2 — online opponent modeling: per-opponent stats accumulated across
the rounds of a game (and reset per game) feed back into pass selection,
moon-defense triggers, and off-suit dump priorities. The model captures
opponents' duck aggressiveness, QS-dump aggressiveness, lead style, and
shoot-prep signals. Designed to exploit unknown opponents at runtime
without source-code access.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Set

from clients.python.api.Game import Game
from clients.python.api.Player import Player
from clients.python.api.Round import Round
from clients.python.api.Trick import Trick
from clients.python.api.networking.ManagedConnection import ManagedConnection
from clients.python.api.networking.SessionHelpers import RunMultipleGames
from clients.python.api.types.Card import (
    Card,
    GroupCardsBySuit,
    Rank,
    SortCardsByRank,
    Suit,
)
from clients.python.api.types.PassDirection import PassDirection
from clients.python.api.types.PlayerTagSession import PlayerTagSession
from clients.python.players.random_player import RandomPlayer
from clients.python.util.Constants import GameType


QS = Card("QS")
KS = Card("KS")
AS_ = Card("AS")
JS = Card("JS")
AH = Card("AH")
TWO_C = Card("2C")
ALL_RANKS_INT = [r.to_int() for r in Rank]


# Tunable parameters — extracted so Phase 3 (CMA-ES) can sweep them.
# Default values are the v14 hand-tuned baseline.
DEFAULT_PARAMS: Dict[str, float] = {
    # passing — danger scores per card type (higher = more eager to pass)
    "danger_qs_protected": 12.0,
    "danger_qs_naked": 100.0,
    "danger_as_with_cover": 30.0,
    "danger_as_no_cover": 60.0,
    "danger_ks_with_cover": 28.0,
    "danger_ks_no_cover": 55.0,
    "danger_js": 12.0,
    "danger_low_spade_mult": 0.6,
    "danger_ah": 50.0,
    "danger_kh": 42.0,
    "danger_qh": 35.0,
    "danger_jh": 28.0,
    "danger_th": 20.0,
    "danger_9h": 12.0,
    "danger_8h": 7.0,
    "danger_low_heart_left_seed": 4.0,
    "danger_low_heart_default": 2.0,
    "danger_a_cd": 26.0,
    "danger_k_cd": 21.0,
    "danger_q_cd": 14.0,
    "danger_j_cd": 7.0,
    "danger_t_cd": 3.0,
    # passing — moon-shoot trigger
    "moon_threshold_pre_pass": 14.0,
    "moon_threshold_post_receive": 16.0,
    "moon_score_per_8_behind": 1.0,  # lower threshold by N per 8-pt deficit
    "moon_score_max_reduction": 4.0,
    # leading — suit-score weights
    "lead_void_pre_qs_penalty": 6.0,
    "lead_void_post_qs_penalty": 1.5,
    "lead_lowest_live_reward": -4.0,
    "lead_rank_weight": 0.3,
    "lead_hearts_penalty": 3.0,
    "lead_spades_pre_qs_penalty": 5.0,
    # Spade-bait params kept in DEFAULT_PARAMS for future tuning, but
    # disabled (reward=0) — hurt tournament play in v27 even though it
    # helped against Expert and Random in isolation.
    "lead_spade_bait_low_count": 4.0,
    "lead_spade_bait_reward": 0.0,
    "lead_short_suit_weight": 0.2,
    # void-passing — disabled. Idea: when no high-danger pass candidates,
    # pass 3 cards from a short suit to create a forced void. Bench didn't
    # show consistent lift on mixed-field play. Kept for tuning.
    "pass_void_max_top_danger": 0.0,
    # moon defense triggers
    "defense_streak_min": 3.0,
    "defense_streak_pts_min": 4.0,
    "defense_qs_played_pts": 19.0,
    "defense_no_qs_pts": 9.0,
    "defense_no_qs_hearts_played": 7.0,
    # phase-2 model-aware adjustments
    "shoot_history_streak_min": 2.0,
    "shoot_history_pts_min": 3.0,
    "model_low_heart_swap_max_rank": 6.0,
    "model_shoot_signal_threshold": 0.3,
}


# ── Opponent modeling ─────────────────────────────────────────────────────


class OpponentStats:
    """Per-opponent rolling stats accumulated across the rounds of a game.

    All counters are observation-counts and event-counts; ratios are
    derived lazily so that tiny samples don't dominate. Reset per game,
    not per round, so signal accumulates across 13 rounds.
    """

    def __init__(self, tag: PlayerTagSession):
        self.tag = tag

        # Pass behavior: cards this opponent has passed *to me* (only on
        # rounds where they donated). Across rounds this builds a profile.
        self.passes_to_me: List[Card] = []
        self.pass_events: int = 0

        # Trick behavior:
        self.duck_options: int = 0     # times they had a "duck under winner" choice
        self.duck_max_count: int = 0   # times they took the maximum duck (Rob-style)
        self.duck_min_count: int = 0   # times they took the minimum duck

        self.qs_dump_options: int = 0  # times they were off-suit holding QS
        self.qs_dumps: int = 0         # times they actually dumped QS

        self.high_offsuit_dumps: int = 0  # off-suit plays of rank ≥ 11

        # Lead behavior:
        self.leads: int = 0
        self.high_leads: int = 0       # rank ≥ 11 lead
        self.spade_leads_pre_qs: int = 0  # bleed-style spade lead before QS gone

        # Trick wins (heart accumulation across the game; high count = often
        # ends up holding tricks).
        self.heart_tricks_won: int = 0
        self.qs_takes: int = 0

        # Moon-shoot history: did they ever shoot in a prior round of THIS game?
        self.shoots_attempted: int = 0
        self.shoots_succeeded: int = 0

    # ── derived ratios ─────────────────────────────────────────────────────
    def duck_aggressiveness(self) -> Optional[float]:
        """1.0 = always plays max duck (very Rob-like). 0.0 = always min.
        None = no observations yet."""
        if self.duck_options < 3:
            return None
        # Smoothed: assume neutral 0.5 prior with weight 2.
        return (self.duck_max_count + 1.0) / (self.duck_options + 2.0)

    def qs_dump_propensity(self) -> Optional[float]:
        if self.qs_dump_options == 0:
            return None
        return self.qs_dumps / self.qs_dump_options

    def avg_pass_rank(self) -> Optional[float]:
        """Avg rank of cards they pass us. <8 = passing low junk = potential
        moon-shooter. >11 = passing dangerous cards (defensive)."""
        if not self.passes_to_me:
            return None
        return sum(c.rank.to_int() for c in self.passes_to_me) / len(self.passes_to_me)

    def shoot_prep_signal(self) -> float:
        """0..1 — higher = more likely they're prepping a moon shoot.

        Blends low-card-passing with prior shoot history."""
        s = 0.0
        avg = self.avg_pass_rank()
        if avg is not None and avg < 7.0:
            s += 0.4
        if self.shoots_attempted > 0:
            s += 0.3 * self.shoots_attempted
        return min(s, 1.0)

    def is_aggressive_qs_dumper(self) -> bool:
        p = self.qs_dump_propensity()
        return p is not None and p >= 0.7

    def is_passive_ducker(self) -> bool:
        d = self.duck_aggressiveness()
        return d is not None and d >= 0.7


def _load_tuned_params() -> Dict[str, float]:
    """Optionally load tuned params from /tmp/tim_tuned_params.json.

    Falls back to DEFAULT_PARAMS if file missing or malformed.
    """
    import json
    import os
    p = os.environ.get("TIM_PARAMS_PATH", "/tmp/tim_tuned_params.json")
    try:
        with open(p) as f:
            blob = json.load(f)
        loaded = blob.get("params", blob)
        # Merge over defaults so missing keys keep their default value.
        merged = dict(DEFAULT_PARAMS)
        merged.update({k: float(v) for k, v in loaded.items() if k in DEFAULT_PARAMS})
        return merged
    except (FileNotFoundError, ValueError, KeyError):
        return DEFAULT_PARAMS


class TimClaudePlayer(Player):
    player_tag = "tim_claude_player"
    message_print_logging_enabled = False
    # Class-level params dict — env var TIM_PARAMS_PATH overrides defaults.
    params: Dict[str, float] = _load_tuned_params()
    # Persistent cross-game opponent profile. Keyed by player_tag (string),
    # so the same opponent class is recognized across games even though
    # PlayerTagSession IDs change every game.
    _shared_models: Dict[str, OpponentStats] = {}

    # ── lifecycle ──────────────────────────────────────────────────────────
    def __init__(self, player_tag_session: PlayerTagSession):
        super().__init__(player_tag_session)
        self.hand: List[Card] = []
        self.current_round: Optional[Round] = None
        self.current_trick: Optional[Trick] = None
        self.player_order: List[PlayerTagSession] = []

        # state per round
        self.played_cards: Set[Card] = set()
        self.opponent_voids: Dict[PlayerTagSession, Set[Suit]] = {}
        self.hearts_broken: bool = False
        self.cards_received: List[Card] = []
        self.cards_passed: List[Card] = []
        self.donating_player: Optional[PlayerTagSession] = None
        self.receiving_player: Optional[PlayerTagSession] = None
        self.shoot_committed: bool = False  # we are actively shooting
        self._last_trick_winner: Optional[PlayerTagSession] = None
        self._streak_count: int = 0

        # state per game
        self.cumulative_score: Dict[PlayerTagSession, int] = {}
        # Per-game session→model map. Resolves through _shared_models so
        # opponent stats persist across games against the same player_tag.
        self.models: Dict[PlayerTagSession, OpponentStats] = {}

    def initialize_for_game(self, game: Game) -> None:
        self.cumulative_score = {}
        self.models = {}  # session-level reset; shared profiles persist

    def handle_end_game(self, players_to_points, winner) -> None:
        pass

    def handle_new_round(self, round: Round) -> None:
        self.hand = round.cards_in_hand
        self.current_round = round
        self.player_order = round.player_order
        self.played_cards = set()
        self.opponent_voids = {p: set() for p in round.player_order if p != self.player_tag_session}
        # Lazy-init per-opponent models on first round.
        # Note: cross-game persistence (_shared_models) was tested and
        # caused major regression (Madison 67→33, Rob 35→16) because
        # accidental moon-shoots were remembered and triggered chronic
        # defense escalation. Reverted to per-game stats.
        for p in round.player_order:
            if p != self.player_tag_session and p not in self.models:
                self.models[p] = OpponentStats(p)
        self.hearts_broken = False
        self.cards_received = []
        self.cards_passed = []
        self.donating_player = None
        self.receiving_player = None
        self.shoot_committed = False
        self._last_trick_winner = None
        self._streak_count = 0

    def handle_finished_round(self, round: Round, round_points) -> None:
        for p, pts in round_points.items():
            self.cumulative_score[p] = self.cumulative_score.get(p, 0) + pts
        # Detect shoot attempts: any single player taking ≥20 raw round
        # points (before moon-flip) means they took most points; if exactly
        # one opponent has 26 (post-flip score) and others have 26, it's a
        # successful shoot. With our scoring API that always returns flipped
        # values, we approximate from round_points distribution.
        nonzero = [(p, v) for p, v in round_points.items() if v > 0]
        if len(nonzero) == 3:
            # Three players at 26 → one shooter (the zero) took everything.
            zero_players = [p for p, v in round_points.items() if v == 0]
            if len(zero_players) == 1 and zero_players[0] != self.player_tag_session:
                shooter = zero_players[0]
                if shooter in self.models:
                    self.models[shooter].shoots_attempted += 1
                    self.models[shooter].shoots_succeeded += 1

    def handle_new_trick(self, trick: Trick) -> None:
        self.current_trick = trick

    def handle_finished_trick(self, trick, winning_player) -> None:
        # Abort shoot-the-moon if any other player has taken points-cards.
        if self.shoot_committed and winning_player != self.player_tag_session:
            if any(m.card.get_point_value() > 0 for m in trick.moves):
                self.shoot_committed = False
        # Track consecutive-trick streaks per player (for shoot detection).
        if winning_player == self._last_trick_winner:
            self._streak_count += 1
        else:
            self._last_trick_winner = winning_player
            self._streak_count = 1
        # Update opponent model: which opponent took which points-cards.
        if winning_player in self.models:
            mdl = self.models[winning_player]
            for mv in trick.moves:
                if mv.card.suit == Suit.HEARTS:
                    mdl.heart_tricks_won += 1  # tracking total hearts taken
                if mv.card == QS:
                    mdl.qs_takes += 1

    def handle_move(self, player: PlayerTagSession, card: Card) -> None:
        self.played_cards.add(card)
        if card.suit == Suit.HEARTS:
            self.hearts_broken = True
        if card == QS:
            self.hearts_broken = True  # QS played → spades-effectively-broken too
        trick = self.current_trick
        if trick is None:
            return
        trick_suit = trick.get_suit()
        is_opp = player != self.player_tag_session
        if trick_suit is not None and card.suit != trick_suit and is_opp:
            self.opponent_voids.setdefault(player, set()).add(trick_suit)
        if is_opp and player in self.models:
            self._update_model_on_move(player, card, trick, trick_suit)

    def _update_model_on_move(
        self,
        player: PlayerTagSession,
        card: Card,
        trick: Trick,
        trick_suit: Optional[Suit],
    ) -> None:
        """Lightweight inference about opponent style from each move.

        We don't see their hand, only the card they played. So we use
        observable signals: lead choices, off-suit dumps, ducking when
        possible. Conservative — when we can't be sure their move was
        a "decision" we don't increment ratios.
        """
        m = self.models[player]
        # Lead?
        if trick_suit is None or len(trick.moves) == 1:  # this card is the lead
            m.leads += 1
            if card.rank.to_int() >= 11:
                m.high_leads += 1
            if card.suit == Suit.SPADES and QS not in self.played_cards and card != QS:
                m.spade_leads_pre_qs += 1
            return
        # Following: figure out current winner before this card.
        prior_moves = [mv for mv in trick.moves if mv.card != card]
        on_suit_prior = [mv.card for mv in prior_moves if mv.card.suit == trick_suit]
        if not on_suit_prior:
            return  # shouldn't happen if trick_suit known
        cur_winner_rank = max(c.rank.to_int() for c in on_suit_prior)
        # Off-suit play (dump)?
        if card.suit != trick_suit:
            if card.rank.to_int() >= 11:
                m.high_offsuit_dumps += 1
            if card == QS:
                m.qs_dumps += 1
                m.qs_dump_options += 1
            # Note: we don't know if they HAD QS but didn't dump it (no hand
            # visibility). qs_dump_options here only counts confirmed dumps,
            # which makes the ratio always 1.0 — so we instead just look at
            # absolute count via qs_dumps for the propensity signal.
            return
        # Following on-suit. Did they have a duck choice?
        # We can only tell when their card is below winner (a successful duck)
        # or equal-to/above (forced winner OR voluntary winner).
        if card.rank.to_int() < cur_winner_rank:
            # They ducked — count toward duck stats. Without their hand we
            # can't tell if their duck was max or min, but we can use a proxy:
            # if their card is close to the winner's rank, it's an aggressive
            # max-duck (Rob-style); if low, it's a passive min-duck.
            m.duck_options += 1
            gap = cur_winner_rank - card.rank.to_int()
            if gap <= 2:
                m.duck_max_count += 1
            elif gap >= 5:
                m.duck_min_count += 1

    # ── passing ────────────────────────────────────────────────────────────
    def get_cards_to_pass(
        self, pass_dir: PassDirection, receiving_player: PlayerTagSession
    ) -> List[Card]:
        self.receiving_player = receiving_player
        P = self.params
        moon_score = self._moon_potential(self.hand)
        my_score = self.cumulative_score.get(self.player_tag_session, 0)
        leader_score = min(self.cumulative_score.values()) if self.cumulative_score else 0
        behind = my_score - leader_score
        # Match original integer-division semantics for stable behavior.
        steps = max(0, behind) // 8
        reduction = min(steps * P["moon_score_per_8_behind"], P["moon_score_max_reduction"])
        threshold = P["moon_threshold_pre_pass"] - reduction
        if moon_score >= threshold:
            self.shoot_committed = True
            picks = self._pass_for_moon(self.hand)
        else:
            picks = self._pass_dangerous(self.hand, pass_dir)
            picks = self._maybe_pass_for_void(picks, self.hand, pass_dir)
            picks = self._adjust_pass_for_receiver(picks, self.hand)
        self.cards_passed = picks
        return picks

    def _maybe_pass_for_void(
        self, picks: List[Card], hand: List[Card], pass_dir: PassDirection
    ) -> List[Card]:
        """When the picked cards aren't very dangerous, prefer voiding a suit
        over passing slightly-dangerous cards. Creates a real strategic edge
        on weak hands — future discards become free.

        Risk: the donor may pass us back into that suit, especially LEFT.
        """
        P = self.params
        top_danger = self._danger_score_for(picks[0]) if picks else 0
        if top_danger >= P["pass_void_max_top_danger"]:
            return picks  # high-danger picks are too valuable to swap out
        by_suit = GroupCardsBySuit(hand)
        # Find a suit with exactly 3 cards (or fewer 1-2; need ≥3 to pass).
        # Don't void hearts (we want to keep low hearts for moon defense).
        # Don't void spades if we have QS — QS needs cover.
        void_candidates = []
        for suit, cards in by_suit.items():
            if suit == Suit.HEARTS:
                continue
            if suit == Suit.SPADES and QS in hand:
                continue
            if len(cards) == 3:
                void_candidates.append((suit, cards))
        if not void_candidates:
            return picks
        # Pick the suit with the lowest total rank (least valuable to keep).
        void_candidates.sort(key=lambda sc: sum(c.rank.to_int() for c in sc[1]))
        _, void_cards = void_candidates[0]
        return list(void_cards)

    def _danger_score_for(self, card: Card) -> float:
        """Standalone danger score for a single card (mirrors _pass_dangerous)."""
        P = self.params
        if card == QS: return P["danger_qs_naked"]
        if card == AS_: return P["danger_as_no_cover"]
        if card == KS: return P["danger_ks_no_cover"]
        if card == JS: return P["danger_js"]
        if card.suit == Suit.SPADES:
            return card.rank.to_int() * P["danger_low_spade_mult"]
        if card.suit == Suit.HEARTS:
            rank = card.rank.to_int()
            if rank == 14: return P["danger_ah"]
            if rank == 13: return P["danger_kh"]
            if rank == 12: return P["danger_qh"]
            if rank == 11: return P["danger_jh"]
            if rank == 10: return P["danger_th"]
            if rank == 9:  return P["danger_9h"]
            return P["danger_8h"]
        rank = card.rank.to_int()
        if rank == 14: return P["danger_a_cd"]
        if rank == 13: return P["danger_k_cd"]
        if rank == 12: return P["danger_q_cd"]
        if rank == 11: return P["danger_j_cd"]
        return P["danger_t_cd"]

    def _adjust_pass_for_receiver(
        self, picks: List[Card], hand: List[Card]
    ) -> List[Card]:
        """If the receiver has a moon-shoot prep signal, swap a low heart in
        for a high heart in our pass — denies their shoot setup AND seeds
        their pile with a hearts trick they don't want.

        Also: if receiver previously shot a moon, treat as confirmed shooter.
        """
        m = self._model_for_receiver()
        if m is None:
            return picks
        signal = m.shoot_prep_signal()
        if signal < self.params["model_shoot_signal_threshold"]:
            return picks
        # Find a high heart in our picks and a low heart in our hand to swap.
        hearts_picked = [c for c in picks if c.suit == Suit.HEARTS]
        if not hearts_picked:
            return picks
        # Sort picks: our highest-ranked heart in picks is the candidate to remove.
        high_h = SortCardsByRank(hearts_picked, reverse=True)[0]
        # Find lowest heart NOT in picks (and not QS).
        candidates = [c for c in hand if c.suit == Suit.HEARTS and c not in picks]
        if not candidates:
            return picks
        low_h = SortCardsByRank(candidates)[0]
        if low_h.rank.to_int() > self.params["model_low_heart_swap_max_rank"]:
            return picks
        new_picks = [c for c in picks if c != high_h] + [low_h]
        return new_picks

    def receive_passed_cards(
        self,
        cards: List[Card],
        pass_dir: PassDirection,
        donating_player: PlayerTagSession,
    ) -> None:
        self.cards_received = cards
        self.donating_player = donating_player
        # Update opponent model: this player passed me these cards.
        if donating_player in self.models:
            m = self.models[donating_player]
            m.passes_to_me.extend(cards)
            m.pass_events += 1
        # Re-evaluate moon offense after receive (we may have just been gifted).
        if not self.shoot_committed and self._moon_potential(self.hand) >= self.params["moon_threshold_post_receive"]:
            self.shoot_committed = True

    # ── playing ────────────────────────────────────────────────────────────
    def get_move(self, trick: Trick, legal_moves: List[Card]) -> Card:
        assert legal_moves
        try:
            return self._get_move_inner(trick, legal_moves)
        except Exception as e:
            # Never crash a session — fall back to lowest legal.
            print(f"[tim_claude_player] get_move error: {e!r}; falling back", flush=True)
            return SortCardsByRank(legal_moves)[0]

    def _get_move_inner(self, trick: Trick, legal_moves: List[Card]) -> Card:
        if len(legal_moves) == 1:
            return legal_moves[0]

        if self.shoot_committed:
            return self._shoot_move(trick, legal_moves)

        if self._should_block_moon():
            return self._block_moon_move(trick, legal_moves)

        if len(trick.moves) == 0:
            return self._lead_card(legal_moves)
        return self._follow_card(trick, legal_moves)

    def _block_moon_move(self, trick: Trick, legal_moves: List[Card]) -> Card:
        """Smarter defense than 'dump highest'. Only play high when it actually
        denies the shooter. Otherwise preserve high cards for a real win later.
        """
        trick_suit = trick.get_suit()
        if trick_suit is None or len(trick.moves) == 0:
            # Leading: lead a HIGH heart if we have one — it forces shooter to
            # spend a high heart or fail to take the trick.
            hearts = [c for c in legal_moves if c.suit == Suit.HEARTS]
            if hearts and self.hearts_broken:
                return SortCardsByRank(hearts, reverse=True)[0]
            return SortCardsByRank(legal_moves, reverse=True)[0]
        # Following: figure out if any of our cards can win the trick.
        on_suit = [c for c in legal_moves if c.suit == trick_suit]
        if on_suit:
            cur_max = max(m.card.rank.to_int() for m in trick.moves
                          if m.card.suit == trick_suit)
            winners = [c for c in on_suit if c.rank.to_int() > cur_max]
            if winners:
                # Play the SMALLEST winner — wins the trick cheaply.
                return SortCardsByRank(winners)[0]
            # Can't win on-suit. Play our LOWEST on-suit (don't waste highs).
            return SortCardsByRank(on_suit)[0]
        # Off-suit: dump our highest non-points-card to clear high cards.
        non_pts = [c for c in legal_moves
                   if c.suit != Suit.HEARTS and c != QS]
        if non_pts:
            return SortCardsByRank(non_pts, reverse=True)[0]
        return SortCardsByRank(legal_moves)[0]

    # ── pass selection helpers ─────────────────────────────────────────────
    def _model_for_receiver(self) -> Optional[OpponentStats]:
        if self.receiving_player is None:
            return None
        return self.models.get(self.receiving_player)

    def _pass_dangerous(self, hand: List[Card], pass_dir: PassDirection) -> List[Card]:
        P = self.params
        by_suit = GroupCardsBySuit(hand)
        spades = by_suit.get(Suit.SPADES, [])
        low_spades = [c for c in spades if c.rank.to_int() < 12]
        has_qs = QS in hand
        qs_well_protected = has_qs and len(low_spades) >= 3

        def danger(card: Card) -> float:
            if card == QS:
                return P["danger_qs_protected"] if qs_well_protected else P["danger_qs_naked"]
            if card == AS_:
                return P["danger_as_with_cover"] if len(low_spades) >= 2 else P["danger_as_no_cover"]
            if card == KS:
                return P["danger_ks_with_cover"] if len(low_spades) >= 2 else P["danger_ks_no_cover"]
            if card == JS:
                return P["danger_js"]
            if card.suit == Suit.SPADES:
                return card.rank.to_int() * P["danger_low_spade_mult"]
            if card.suit == Suit.HEARTS:
                rank = card.rank.to_int()
                if rank == 14: return P["danger_ah"]
                if rank == 13: return P["danger_kh"]
                if rank == 12: return P["danger_qh"]
                if rank == 11: return P["danger_jh"]
                if rank == 10: return P["danger_th"]
                if rank == 9:  return P["danger_9h"]
                if rank == 8:  return P["danger_8h"]
                return P["danger_low_heart_left_seed"] if (pass_dir == PassDirection.LEFT and rank <= 4) else P["danger_low_heart_default"]
            rank = card.rank.to_int()
            if rank == 14: return P["danger_a_cd"]
            if rank == 13: return P["danger_k_cd"]
            if rank == 12: return P["danger_q_cd"]
            if rank == 11: return P["danger_j_cd"]
            if rank == 10: return P["danger_t_cd"]
            return 0

        # base ranking by danger
        ranked = sorted(hand, key=danger, reverse=True)

        # Don't pass cards if doing so leaves <2 spades — we need cover.
        # Walk down `ranked`, skip a spade pass when it would over-strip.
        picks: List[Card] = []
        spades_left = len(spades)
        for c in ranked:
            if len(picks) == 3:
                break
            if c.suit == Suit.SPADES and spades_left <= 2 and c.rank.to_int() < 12:
                continue  # protect remaining low spades (cover for QS)
            picks.append(c)
            if c.suit == Suit.SPADES:
                spades_left -= 1
        if len(picks) < 3:
            for c in ranked:
                if c not in picks:
                    picks.append(c)
                    if len(picks) == 3:
                        break
        return picks[:3]

    def _pass_for_moon(self, hand: List[Card]) -> List[Card]:
        """We're shooting: dump our worst low cards, keep all hearts and high cards."""
        def keep_value(card: Card) -> float:
            # Higher = more valuable to keep.
            if card.suit == Suit.HEARTS:
                return 100 + card.rank.to_int()  # keep all hearts
            if card == QS or card == AS_ or card == KS:
                return 90
            return card.rank.to_int()

        ranked = sorted(hand, key=keep_value)  # ascending = worst first
        return ranked[:3]

    def _moon_potential(self, hand: List[Card]) -> int:
        """Heuristic: ≥0, 9+ = strong shoot candidate."""
        score = 0
        by_suit = GroupCardsBySuit(hand)
        hearts = by_suit.get(Suit.HEARTS, [])
        spades = by_suit.get(Suit.SPADES, [])

        score += len(hearts)  # raw hearts count
        high_hearts = sum(1 for c in hearts if c.rank.to_int() >= 11)
        score += high_hearts  # double-weight high hearts
        if Card("AH") in hearts:
            score += 1
        if QS in hand and len([c for c in spades if c.rank.to_int() < 12]) >= 2:
            score += 3
        if AS_ in hand:
            score += 1
        if KS in hand:
            score += 1
        # control of side suits: long suit with high cards
        for s in (Suit.CLUBS, Suit.DIAMONDS):
            cards = by_suit.get(s, [])
            if len(cards) >= 4 and any(c.rank.to_int() >= 13 for c in cards):
                score += 2
        # voiding a side suit also helps
        for s in (Suit.CLUBS, Suit.DIAMONDS):
            if not by_suit.get(s):
                score += 2
        return score

    # ── lead/follow ────────────────────────────────────────────────────────
    def _opponents_are_passive_duckers(self) -> bool:
        """True if at least 2 of 3 opponents have observable max-duck behavior.
        Used to bias leads toward absolute-lowest cards in such environments."""
        ducker_count = sum(
            1 for m in self.models.values() if m.is_passive_ducker()
        )
        return ducker_count >= 2

    def _lead_card(self, legal_moves: List[Card]) -> Card:
        by_suit = GroupCardsBySuit(legal_moves)
        qs_played = QS in self.played_cards

        # Score each leadable suit; lower is better (lower expected loss).
        scored: List[tuple] = []
        for suit, cards in by_suit.items():
            scored.append((self._lead_suit_score(suit, cards, qs_played), suit, cards))
        scored.sort(key=lambda x: x[0])
        _, _, best_cards = scored[0]
        # Lead lowest of chosen suit (defensive lead).
        return SortCardsByRank(best_cards)[0]

    def _lead_suit_score(self, suit: Suit, cards: List[Card], qs_played: bool) -> float:
        """Lower score = better suit to lead."""
        P = self.params
        score = 0.0
        lowest = SortCardsByRank(cards)[0]
        for voids in self.opponent_voids.values():
            if suit in voids and not qs_played:
                score += P["lead_void_pre_qs_penalty"]
            elif suit in voids:
                score += P["lead_void_post_qs_penalty"]
        if self._is_lowest_live(lowest, suit):
            score += P["lead_lowest_live_reward"]
        score += lowest.rank.to_int() * P["lead_rank_weight"]
        if suit == Suit.HEARTS:
            if not self.hearts_broken:
                score += 100
            score += P["lead_hearts_penalty"]
        if suit == Suit.SPADES and not qs_played and QS not in self.hand:
            # Bait-the-queen: if we hold many low spades, leading spades is
            # actually safe — opponent must eventually shed QS, and we have
            # cover. Negate the penalty when we have ≥4 low spades.
            low_spade_count = sum(
                1 for c in self.hand
                if c.suit == Suit.SPADES and c.rank.to_int() < 12
            )
            if low_spade_count >= P["lead_spade_bait_low_count"]:
                score -= P["lead_spade_bait_reward"]
            else:
                score += P["lead_spades_pre_qs_penalty"]
        score += len(cards) * P["lead_short_suit_weight"]
        return score

    def _follow_card(self, trick: Trick, legal_moves: List[Card]) -> Card:
        trick_suit = trick.get_suit()
        following_suit = legal_moves[0].suit == trick_suit
        is_last = len(trick.moves) == 3
        trick_pts = trick.get_current_point_value()
        sorted_legal = SortCardsByRank(legal_moves)

        if following_suit:
            winner_card = self._current_winner(trick)
            below = [c for c in sorted_legal if c.rank.to_int() < winner_card.rank.to_int()]

            if below:
                # First-trick safeguard: opponent won't dump QS or hearts on
                # the very first trick (illegal), so it's safe to play highest below.
                return below[-1]

            # We're forced to take this trick.
            players_after = trick.player_order[len(trick.moves) + 1 :]
            all_after_void = bool(players_after) and all(
                trick_suit in self.opponent_voids.get(p, set()) for p in players_after
            )

            # If we're last (or effectively last), we'll definitely take the
            # trick — dump our HIGHEST in suit (offload the most dangerous card,
            # since lower cards stay in hand for safer use later).
            if is_last or all_after_void:
                return sorted_legal[-1]
            # Otherwise a player after us might over-trump and save us — play
            # lowest forced-winner to maximize their chance of taking it.
            return sorted_legal[0]

        # Off-suit: we get to discard ANY card.
        return self._discard_off_suit(trick, legal_moves, trick_pts, is_last)

    def _discard_off_suit(
        self,
        trick: Trick,
        legal_moves: List[Card],
        trick_pts: int,
        is_last: bool,
    ) -> Card:
        # 1. QS dump if anyone after us could still take the trick.
        if QS in legal_moves:
            return QS

        hearts = [c for c in legal_moves if c.suit == Suit.HEARTS]
        spades_high = [c for c in legal_moves if c.suit == Suit.SPADES and c.rank.to_int() >= 13]
        # AS / KS dumps are valuable when QS still live.
        qs_live = QS not in self.played_cards and QS not in self.hand

        if trick_pts > 0:
            # Trick already has points; load up our worst card on it.
            # Highest heart is ideal (no risk of catching QS later).
            if hearts:
                return SortCardsByRank(hearts, reverse=True)[0]
            if qs_live and spades_high:
                return SortCardsByRank(spades_high, reverse=True)[0]
            return self._most_dangerous(legal_moves)

        # Trick has no points yet. Dump our most dangerous non-heart-non-QS.
        # Prefer dumping AS/KS (high QS-catchers) before high hearts since
        # the trick is currently safe.
        if qs_live and spades_high:
            return SortCardsByRank(spades_high, reverse=True)[0]
        # Then highest non-heart card.
        non_hearts = [c for c in legal_moves if c.suit != Suit.HEARTS and c != QS]
        if non_hearts:
            return self._most_dangerous(non_hearts)
        # Only hearts left: dump the highest (we'll be forced to take points later anyway).
        return SortCardsByRank(hearts, reverse=True)[0]

    @staticmethod
    def _most_dangerous(cards: List[Card]) -> Card:
        def danger(c: Card) -> float:
            if c == QS:
                return 100
            if c == AS_:
                return 50
            if c == KS:
                return 45
            if c.suit == Suit.HEARTS:
                return 30 + c.rank.to_int()
            return c.rank.to_int()
        return sorted(cards, key=danger, reverse=True)[0]

    @staticmethod
    def _current_winner(trick: Trick) -> Card:
        trick_suit = trick.get_suit()
        on_suit = [m.card for m in trick.moves if m.card.suit == trick_suit]
        return SortCardsByRank(on_suit, reverse=True)[0]

    # ── information helpers ────────────────────────────────────────────────
    def _is_lowest_live(self, card: Card, suit: Suit) -> bool:
        """Is `card` the lowest unplayed card of `suit` outside our hand?"""
        for r in ALL_RANKS_INT:
            if r >= card.rank.to_int():
                return True
            candidate = Card(f"{Rank(self._rank_str(r)).value}{suit.value}")
            if candidate in self.played_cards or candidate in self.hand:
                continue
            return False  # an opponent holds something lower
        return True

    def _higher_cards_live(self, card: Card, suit: Suit) -> int:
        count = 0
        for r in ALL_RANKS_INT:
            if r <= card.rank.to_int():
                continue
            candidate = Card(f"{Rank(self._rank_str(r)).value}{suit.value}")
            if candidate in self.played_cards or candidate in self.hand:
                continue
            count += 1
        return count

    def _opponents_might_hold_qs(self) -> bool:
        return QS not in self.played_cards and QS not in self.hand

    def _estimated_spades_out(self) -> int:
        played_spades = sum(1 for c in self.played_cards if c.suit == Suit.SPADES)
        my_spades = sum(1 for c in self.hand if c.suit == Suit.SPADES)
        return 13 - played_spades - my_spades

    @staticmethod
    def _rank_str(rank_int: int) -> str:
        for r in Rank:
            if r.to_int() == rank_int:
                return r.value
        raise ValueError(rank_int)

    # ── moon defense / offense ─────────────────────────────────────────────
    def _should_block_moon(self) -> bool:
        if self.current_round is None:
            return False
        pts = self.current_round.get_round_points()
        with_pts = [(p, v) for p, v in pts.items() if v > 0]
        if len(with_pts) != 1:
            return False
        shooter, points = with_pts[0]
        if shooter == self.player_tag_session:
            return False
        qs_played = QS in self.played_cards
        # Early signal: one opponent on a 3+ trick streak AND has any points
        # → likely consolidating a moon shoot. Block aggressively.
        P = self.params
        same_player_streak = self._last_trick_winner == shooter
        shooter_model = self.models.get(shooter)
        prior_shoot = shooter_model is not None and shooter_model.shoots_succeeded > 0
        streak_min = P["shoot_history_streak_min"] if prior_shoot else P["defense_streak_min"]
        pts_min = P["shoot_history_pts_min"] if prior_shoot else P["defense_streak_pts_min"]
        if same_player_streak and self._streak_count >= streak_min and points >= pts_min:
            return True
        hearts_played = sum(1 for c in self.played_cards if c.suit == Suit.HEARTS)
        if qs_played:
            return points >= P["defense_qs_played_pts"]
        return points >= P["defense_no_qs_pts"] and hearts_played >= P["defense_no_qs_hearts_played"]

    def _shoot_move(self, trick: Trick, legal_moves: List[Card]) -> Card:
        # Always try to win the trick. Lead high from longest suit; follow
        # with highest card; off-suit discard the lowest non-shooting card.
        if len(trick.moves) == 0:
            by_suit = GroupCardsBySuit(legal_moves)
            longest = max(by_suit.values(), key=lambda cs: (len(cs), max(c.rank.to_int() for c in cs)))
            return SortCardsByRank(longest, reverse=True)[0]
        trick_suit = trick.get_suit()
        following_suit = legal_moves[0].suit == trick_suit
        if following_suit:
            return SortCardsByRank(legal_moves, reverse=True)[0]
        # off-suit: dump lowest non-heart, keep hearts and high cards
        non_pts = [c for c in legal_moves if c.suit != Suit.HEARTS and c != QS]
        if non_pts:
            return SortCardsByRank(non_pts)[0]
        # only points left — dump lowest heart (smallest setback)
        return SortCardsByRank(legal_moves)[0]


if __name__ == "__main__":
    import time

    players = [TimClaudePlayer, RandomPlayer, RandomPlayer, RandomPlayer]
    total = 0
    won = 0
    t0 = time.time()
    with ManagedConnection("tim_claude_player") as conn:
        results = RunMultipleGames(conn, GameType.ANY, players, 10)
        for r in results:
            total += 1
            if "tim_claude_player" in str(r.winner):
                won += 1
    print(f"Won {won}/{total} ({won / total * 100:.1f}%) in {time.time() - t0:.1f}s")
