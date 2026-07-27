from collections import defaultdict
from typing import List, Optional, Dict, Tuple, Type

from clients.python.api.Game import Game
from clients.python.api.Player import Player
from clients.python.api.Round import Round
from clients.python.api.Trick import Trick, Move
from clients.python.api.types.Card import Card, Suit
from clients.python.api.types.PassDirection import PassDirection
from clients.python.api.types.PlayerTagSession import PlayerTagSession, PlayerTag
from clients.python.util.table_game.TableGameCLI import TableGameCLI, UndoMove, DEFER
from clients.python.util.table_game.CardValidation import BlacklistedCardsValidator, UNIQUE_CARDS_VALIDATOR


class TableSetupError(RuntimeError):
    """Raised when dealing/passing produced an inconsistent model of who holds
    what — a card recorded twice (in one hand, or in two different hands) or a
    hand that isn't exactly 13 cards. This is unrecoverable for the round: there
    is no way to "undo" a dealing/passing entry, so the safest thing is to halt
    loudly, with the exact conflict named, rather than let AI decisions run on
    a corrupted hand — which is how a single bad entry turns into wrong scores
    for the rest of the game (see the crash this guards against: an AI silently
    holding a duplicate card played it a second time several tricks later)."""


def verify_hands_sound(ai_hands: Dict[PlayerTagSession, List[Card]]) -> None:
    """Check that ``ai_hands`` is a valid partition: each hand has exactly 13
    cards with no internal duplicate, and no card is claimed by two hands.

    Called right after dealing + passing finishes, before any trick is dealt,
    so a bad entry is caught at the earliest possible point — immediately and
    with a specific, actionable message — instead of silently corrupting play
    until some AI's own bookkeeping (e.g. ``ProbabilityTable``) trips over the
    duplicate mid-game with a confusing, unrelated-looking error.
    """
    owner_of: Dict[Card, PlayerTagSession] = {}
    for pts, hand in ai_hands.items():
        counts: Dict[Card, int] = {}
        for c in hand:
            counts[c] = counts.get(c, 0) + 1
        dupes = sorted((str(c) for c, n in counts.items() if n > 1))
        if dupes:
            raise TableSetupError(
                f"{pts.player_tag} would hold {dupes} more than once after dealing/passing. "
                f"A dealt or passed card must have been entered incorrectly; this table cannot "
                f"safely continue — please start a new one."
            )
        if len(hand) != 13:
            raise TableSetupError(
                f"{pts.player_tag} has {len(hand)} cards after dealing/passing (expected 13). "
                f"A dealt or passed card must have been entered incorrectly; this table cannot "
                f"safely continue — please start a new one."
            )
        for c in hand:
            prior = owner_of.get(c)
            if prior is not None and prior != pts:
                raise TableSetupError(
                    f"{c} is recorded as held by both {prior.player_tag} and {pts.player_tag}. "
                    f"A dealt or passed card must have been entered incorrectly; this table cannot "
                    f"safely continue — please start a new one."
                )
            owner_of[c] = pts


def _rebuild_all_players(
        game: 'TableGame',
        current_round: 'TableRound',
        current_trick: 'TableTrick',
) -> Dict[PlayerTagSession, Player]:
    """Tear down all AI players and replay full game history to restore their state."""
    new_players: Dict[PlayerTagSession, Player] = {}

    for pts, cls in game.ai_configs.items():
        p = cls(pts)
        p.initialize_for_game(game)

        for past_round in game.rounds[:-1]:
            saved = list(past_round.ai_hands[pts])
            past_round.ai_hands[pts].clear()
            past_round.ai_hands[pts].extend(past_round.ai_hands_at_tricks_start[pts])

            past_round.cards_in_hand = past_round.ai_hands[pts]
            p.handle_new_round(past_round)
            if past_round.pass_direction != PassDirection.KEEPER:
                donor = past_round.pass_direction.get_donating_player(past_round.player_order, pts)
                p.receive_passed_cards(past_round.ai_received_cards[pts], past_round.pass_direction, donor)

            for trick in past_round.tricks:
                p.handle_new_trick(trick)
                for move in trick.moves:
                    p.handle_move(trick, move.player, move.card)
                    if move.player == pts and move.card in past_round.ai_hands[pts]:
                        past_round.ai_hands[pts].remove(move.card)
                p.handle_finished_trick(trick, trick.winner)

            p.handle_finished_round(past_round, past_round.get_round_points())
            past_round.ai_hands[pts].clear()
            past_round.ai_hands[pts].extend(saved)

        # Current round: reset to post-pass snapshot, replay tricks up to current
        current_round.ai_hands[pts].clear()
        current_round.ai_hands[pts].extend(current_round.ai_hands_at_tricks_start[pts])

        current_round.cards_in_hand = current_round.ai_hands[pts]
        p.handle_new_round(current_round)
        if current_round.pass_direction != PassDirection.KEEPER:
            donor = current_round.pass_direction.get_donating_player(current_round.player_order, pts)
            p.receive_passed_cards(current_round.ai_received_cards[pts], current_round.pass_direction, donor)

        for trick in current_round.tricks[:-1]:
            p.handle_new_trick(trick)
            for move in trick.moves:
                p.handle_move(trick, move.player, move.card)
                if move.player == pts and move.card in current_round.ai_hands[pts]:
                    current_round.ai_hands[pts].remove(move.card)
            p.handle_finished_trick(trick, trick.winner)

        p.handle_new_trick(current_trick)
        for move in current_trick.moves:
            p.handle_move(current_trick, move.player, move.card)
            if move.player == pts and move.card in current_round.ai_hands[pts]:
                current_round.ai_hands[pts].remove(move.card)

        new_players[pts] = p

    return new_players


class TableGame(Game):
    def __init__(self, player_configs: List[tuple]):
        """
        player_configs: list of 4 (name_str, player_cls_or_None) tuples.
        Pass None as the class for human seats.
        """
        assert len(player_configs) == 4, "Must have exactly 4 players"
        player_tag_sessions = [
            PlayerTagSession(PlayerTag(name), i + 1)
            for i, (name, _) in enumerate(player_configs)
        ]
        super().__init__(player_tag_sessions)

        self.ai_configs: Dict[PlayerTagSession, Type[Player]] = {
            pts: cls
            for pts, (_, cls) in zip(player_tag_sessions, player_configs)
            if cls is not None
        }
        self.ai_players: Dict[PlayerTagSession, Player] = {}

        # First AI is the "table player" used by the CLI for card-tracking features
        first_ai = next((pts for pts in player_tag_sessions if pts in self.ai_configs), None)
        self.table_player: Optional[PlayerTag] = first_ai.player_tag if first_ai else None

        self.cli = TableGameCLI(self)

    def run_game(self):
        labels = [
            f"{pts.player_tag} (AI)" if pts in self.ai_configs else str(pts.player_tag)
            for pts in self.player_order
        ]
        print(f"Starting game: {', '.join(labels)}")

        self.ai_players = {pts: cls(pts) for pts, cls in self.ai_configs.items()}
        for p in self.ai_players.values():
            p.initialize_for_game(self)

        pass_direction = self.cli.ask_for_pass_direction("Starting pass direction", PassDirection.LEFT)
        players_to_points: Dict[PlayerTagSession, int] = defaultdict(int)

        while True:
            table_round = TableRound(self.ai_players, self.ai_configs, self.cli, self.player_order,
                                     len(self.rounds), pass_direction)
            self.rounds.append(table_round)
            table_round.run_round(self)
            self.ai_players = table_round.ai_players  # may have been rebuilt by undo

            pass_direction = pass_direction.next_pass_direction()

            round_points = table_round.get_round_points()
            for name, points in round_points.items():
                players_to_points[name] += points

            print("Current rankings:")
            for rank, (name, points) in enumerate(sorted(players_to_points.items(), key=lambda kv: kv[1]), 1):
                tag = f"{name.player_tag} (AI)" if name in self.ai_configs else str(name.player_tag)
                print(f"\t{rank}. {tag} — {points} pts")

            if max(players_to_points.values()) >= 100:
                break


class TableRound(Round):
    def __init__(self, ai_players: Dict[PlayerTagSession, Player],
                 ai_configs: Dict[PlayerTagSession, Type[Player]],
                 cli: TableGameCLI, player_order: List[PlayerTagSession],
                 round_idx: int, pass_direction: PassDirection):
        self.ai_players = dict(ai_players)
        self.ai_configs = ai_configs
        self.cli = cli

        # Hands are dealt interleaved with passing in run_round (see
        # _setup_hands_and_pass) so the operator handles one physical hand at a
        # time. These are populated as that walk proceeds.
        self.ai_hands: Dict[PlayerTagSession, List[Card]] = {}
        # A snapshot of every AI hand exactly as dealt, before any pass mutates
        # it. Used to validate the cards a *human* reports passing: a human passes
        # from their own dealt hand, so a passed card can never be one an AI was
        # dealt. Validating against the live (mid-pass) ai_hands instead would let
        # a card an AI has already given away become selectable — and be
        # mis-entered as a human pass — landing it in two hands at once.
        self.ai_hands_dealt: Dict[PlayerTagSession, List[Card]] = {}

        super().__init__(round_idx, pass_direction, player_order, [])

        self.ai_hands_at_tricks_start: Dict[PlayerTagSession, List[Card]] = {}
        self.ai_received_cards: Dict[PlayerTagSession, List[Card]] = {}
        self.ai_donating_cards: Dict[PlayerTagSession, List[Card]] = {}
        self._human_passes_seen: List[Card] = []

    def get_trick_order(self, last_winner: Optional[PlayerTagSession]) -> List[PlayerTagSession]:
        if last_winner is not None:
            first = last_winner
        else:
            # The 2 of clubs leads the first trick. Every AI hand is known, so if
            # an AI holds it we lead with that AI outright. Otherwise it must be a
            # human — and only the humans are possible holders, so never offer an
            # AI (which we can prove doesn't have it). With a single human at the
            # table that human is the only possible holder, so skip the question
            # entirely and lead with them (they'll simply be asked to play the 2C).
            first = next((pts for pts, hand in self.ai_hands.items() if Card("2C") in hand), None)
            if first is None:
                humans = [p for p in self.player_order if p not in self.ai_hands]
                if len(humans) == 1:
                    first = humans[0]
                else:
                    candidates = humans or self.player_order
                    first = self.cli.ask_for_player("Who has the 2 of clubs?", candidates)
        start_idx = self.player_order.index(first)
        return self.player_order[start_idx:] + self.player_order[:start_idx]

    def get_round_points(self) -> Dict[PlayerTagSession, int]:
        player_to_points: Dict[PlayerTagSession, int] = {p: 0 for p in self.player_order}
        for trick in self.tricks:
            if trick.winner is None:
                continue
            hearts = sum(1 for m in trick.moves if m.card.suit == Suit.HEARTS)
            had_qs = any(m.card == Card("QS") for m in trick.moves)
            player_to_points[trick.winner] += hearts + (13 if had_qs else 0)

        # Shoot the moon: a player who takes all 26 points scores 0 while every
        # other player is charged the full 26 (matches the server's scoreRound).
        for shooter, points in player_to_points.items():
            if points == 26:
                return {p: (0 if p == shooter else 26) for p in self.player_order}
        return player_to_points

    def _pass_chain_order(self) -> List[PlayerTagSession]:
        """Players in pass-chain order for dealing + passing.

        We follow the "passes to" links so that, whenever possible, a player's
        donor is handled before them — letting the operator deal a hand, pass it,
        and receive the incoming cards in a single physical pickup. The walk
        starts at a human (so the first AI reached receives from that human, whose
        pass may already be known), then continues through every cycle so no
        player is missed. With four players LEFT/RIGHT form one cycle and ACROSS
        two; either way every player appears exactly once.
        """
        receiver_of = {
            p: self.pass_direction.get_receiving_player(self.player_order, p)
            for p in self.player_order
        }
        humans = [p for p in self.player_order if p not in self.ai_players]
        first = humans[0] if humans else self.player_order[0]
        starts = [first] + [p for p in self.player_order if p != first]
        order: List[PlayerTagSession] = []
        visited = set()
        for start in starts:
            cur = start
            while cur not in visited:
                visited.add(cur)
                order.append(cur)
                cur = receiver_of[cur]
        return order

    def _ask_human_pass(self, donor: PlayerTagSession, receiver: PlayerTagSession, allow_defer: bool):
        """Ask what a *human* donor passed to ``receiver`` (or defer).

        A human passes from their own dealt hand, so a passed card can never be a
        card any AI was dealt, nor one already reported as another human's pass.
        Blacklisting the *dealt* AI hands (a stable snapshot) rather than the
        live, mid-pass ai_hands is what keeps this sound regardless of the order
        receivers are resolved in. Returns the 3 cards, or ``DEFER`` if the
        operator chose to enter them later.
        """
        forbidden = [c for hand in self.ai_hands_dealt.values() for c in hand]
        forbidden += self._human_passes_seen
        validators = [UNIQUE_CARDS_VALIDATOR, BlacklistedCardsValidator(forbidden)]
        received = self.cli.ask_for_cards(
            f"What did {donor.player_tag} pass to {receiver.player_tag}?",
            validators, 3, allow_defer=allow_defer)
        if received is DEFER:
            return DEFER
        self._human_passes_seen.extend(received)
        return received

    def _apply_received(self, receiver: PlayerTagSession, received: List[Card], donor: PlayerTagSession):
        """Fold the cards ``receiver`` got into its hand (its own donation has
        already been removed) and notify the AI."""
        self.ai_received_cards[receiver] = list(received)
        self.ai_hands[receiver].extend(received)  # donated already removed
        self.ai_players[receiver].receive_passed_cards(received, self.pass_direction, donor)

    def _setup_hands_and_pass(self):
        """Deal every AI hand and resolve passing, interleaved in pass-chain order
        so the operator handles one physical hand at a time. Human passes whose
        cards aren't in hand yet can be deferred (``DEFER``) and are collected at
        the end, once every hand is entered and every AI pass is known."""
        deferred: List[Tuple[PlayerTagSession, PlayerTagSession]] = []  # (receiver, donor)
        passed: set = set()  # AIs whose pass has been decided

        for pts in self._pass_chain_order():
            if pts not in self.ai_players:
                continue  # humans hold their own cards — nothing to enter

            # 1. Deal this AI's hand, cross-validated against every card already
            #    *dealt* to another AI. This must use the dealt snapshot, not the
            #    live ai_hands: by this point earlier AIs have had their donated
            #    cards removed from their live hand, so a live-hand blacklist
            #    would stop greying them and let the operator enter one here —
            #    and since the donation is added to its receiver separately, that
            #    card would then be counted in two hands ("X would hold [...]
            #    more than once"). Dealt hands are disjoint by construction, so
            #    they are the correct, stable thing to validate against.
            already = [c for hand in self.ai_hands_dealt.values() for c in hand]
            validators = [UNIQUE_CARDS_VALIDATOR, BlacklistedCardsValidator(already)]
            hand = self.cli.ask_for_cards(f"Starting hand for {pts.player_tag}", validators, 13)
            self.ai_hands[pts] = hand
            self.ai_hands_dealt[pts] = list(hand)
            self.cards_in_hand = self.ai_hands[pts]
            self.ai_players[pts].handle_new_round(self)

            if self.pass_direction == PassDirection.KEEPER:
                continue

            # 2. Decide + instruct this AI's pass, removing the donated cards from
            #    its hand at once so the model never counts a card in two hands.
            receiving = self.pass_direction.get_receiving_player(self.player_order, pts)
            donating = self.ai_players[pts].get_cards_to_pass(self.pass_direction, receiving)
            self.ai_donating_cards[pts] = list(donating)
            for c in donating:
                if c in self.ai_hands[pts]:
                    self.ai_hands[pts].remove(c)
            self.cli.instruct(f"{pts.player_tag}: pass {list(donating)} to {receiving.player_tag}")
            passed.add(pts)

            # 3. Resolve what this AI received from its donor.
            donor = self.pass_direction.get_donating_player(self.player_order, pts)
            if donor in self.ai_players:
                if donor in passed:
                    self._apply_received(pts, list(self.ai_donating_cards[donor]), donor)
                else:
                    deferred.append((pts, donor))  # donor AI not dealt yet (cycle start)
            else:
                received = self._ask_human_pass(donor, pts, allow_defer=True)
                if received is DEFER:
                    deferred.append((pts, donor))
                else:
                    self._apply_received(pts, received, donor)

        # Collect everything left: deferred human passes (asked now, with every
        # hand known) and any AI-to-AI receive that outran its donor.
        for pts, donor in deferred:
            if donor in self.ai_players:
                received = list(self.ai_donating_cards[donor])
            else:
                received = self._ask_human_pass(donor, pts, allow_defer=False)
            self._apply_received(pts, received, donor)

        # Dealing/passing is fully resolved now — verify the model is sound
        # *before* any trick is dealt, rather than let a corrupted hand run
        # through AI decisions and surface as a confusing crash mid-game.
        verify_hands_sound(self.ai_hands)

        if self.ai_hands:
            self.cards_in_hand = next(iter(self.ai_hands.values()))

    def run_round(self, game: 'TableGame'):
        self._setup_hands_and_pass()

        for pts in self.ai_hands:
            self.ai_hands_at_tricks_start[pts] = list(self.ai_hands[pts])

        played_cards: List[Card] = []
        last_winner: Optional[PlayerTagSession] = None

        for trick_idx in range(13):
            trick_order = self.get_trick_order(last_winner)
            table_trick = TableTrick(self.ai_players, self.cli, trick_idx, trick_order,
                                     self.ai_hands, played_cards)
            self.tricks.append(table_trick)
            table_trick.run_trick(game, self)
            self.ai_players = table_trick.ai_players  # may have been rebuilt by undo

            # `played_cards` is the same list the trick appends each move to as
            # it plays, so it already holds this trick's cards — don't re-add them.
            last_winner = table_trick.get_winner()

        round_points = self.get_round_points()
        for p in self.ai_players.values():
            p.handle_finished_round(self, round_points)
        print(f"Round points: {', '.join(f'{p.player_tag}: {pts}' for p, pts in round_points.items())}\n")


class TableTrick(Trick):
    def __init__(self, ai_players: Dict[PlayerTagSession, Player], cli: TableGameCLI,
                 trick_idx: int, player_order: List[PlayerTagSession],
                 ai_hands: Dict[PlayerTagSession, List[Card]], played_cards: List[Card]):
        self.trick_idx = trick_idx
        self.player_order: List[PlayerTagSession] = player_order
        self.ai_players = dict(ai_players)
        self.ai_hands = ai_hands  # live references — mutated in place as AI plays
        self.played_cards = played_cards
        self.cli = cli
        self._move_buffer: List[Move] = []
        Trick.__init__(self, trick_idx, player_order)

    def _flush_buffer(self):
        """Report all buffered human moves to every AI, then clear the buffer."""
        for move in self._move_buffer:
            for p in self.ai_players.values():
                p.handle_move(self, move.player, move.card)
        self._move_buffer.clear()

    def compute_legal_moves(self, hand: List[Card]) -> List[Card]:
        """Legal moves for the player to move, mirroring the server's rules
        (see ``server/game/trick.h::legalMovesForPlayer``)."""
        legal = list(hand)
        leading = not self.moves

        # Must follow the led suit when able.
        if not leading:
            suit = self.moves[0].card.suit
            in_suit = [c for c in legal if c.suit == suit]
            if in_suit:
                legal = in_suit

        # Hearts can't be *led* until they've been broken — but they may always
        # be discarded when following a suit you're void in (that's how hearts
        # get broken). This restriction therefore only applies to the lead.
        if leading:
            hearts_broken = any(c.suit == Suit.HEARTS for c in self.played_cards)
            if not hearts_broken:
                non_hearts = [c for c in legal if c.suit != Suit.HEARTS]
                if non_hearts:
                    legal = non_hearts

        if self.trick_idx == 0:
            if leading:
                # The very first trick of a round must be led with the 2 of clubs.
                two_of_clubs = Card("2C")
                return [two_of_clubs] if two_of_clubs in legal else legal
            # No point cards (hearts or the Queen of Spades) may be played on the
            # first trick unless a player has nothing else that's legal.
            non_points = [c for c in legal if c.suit != Suit.HEARTS and c != Card("QS")]
            if non_points:
                legal = non_points

        return legal

    def get_winner(self) -> PlayerTagSession:
        suit = self.moves[0].card.suit
        return max((m for m in self.moves if m.card.suit == suit), key=lambda m: m.card.rank).player

    def run_trick(self, game: 'TableGame', round_ref: 'TableRound'):
        for p in self.ai_players.values():
            p.handle_new_trick(self)

        i = 0
        while i < len(self.player_order):
            seat = self.player_order[i]

            if seat in self.ai_players:
                # Flush buffered human moves so this AI (and all others) see them before deciding
                self._flush_buffer()
                ai = self.ai_players[seat]
                hand = self.ai_hands[seat]
                legal = self.compute_legal_moves(hand)
                card = ai.get_move(self, legal)
                self.cli.instruct(f"{seat.player_tag}: play {card}")
                hand.remove(card)
                # AI move is reported immediately to all AIs — not buffered
                self.played_cards.append(card)
                self.moves.append(Move(seat, card))
                for p in self.ai_players.values():
                    p.handle_move(self, seat, card)
                i += 1

            else:
                all_ai_hands = [h for h in self.ai_hands.values()]
                validators = [BlacklistedCardsValidator(self.played_cards)] + \
                             [BlacklistedCardsValidator(h) for h in all_ai_hands]
                try:
                    card = self.cli.ask_for_card(f"What card did {seat.player_tag} play?",
                                                 validators, allow_undo=True)
                except UndoMove:
                    if self._move_buffer:
                        # Fast path: move not yet seen by any AI — just pop the buffer
                        last = self._move_buffer.pop()
                        self.moves.pop()
                        self.played_cards.remove(last.card)
                        print(f"Undoing {last.player.player_tag}'s {last.card}.")
                    else:
                        # Slow path: move was already flushed before an AI decision — full rebuild
                        popped_ai: List[Move] = []
                        while self.moves and self.moves[-1].player in self.ai_players:
                            m = self.moves.pop()
                            self.played_cards.remove(m.card)
                            self.ai_hands[m.player].append(m.card)
                            popped_ai.append(m)

                        if not self.moves:
                            for m in reversed(popped_ai):
                                self.ai_hands[m.player].remove(m.card)
                                self.played_cards.append(m.card)
                                self.moves.append(m)
                            print("Nothing to undo before the AI's last decision.")
                        else:
                            last_human = self.moves.pop()
                            self.played_cards.remove(last_human.card)
                            print(f"Undoing {last_human.player.player_tag}'s {last_human.card}. "
                                  f"Rebuilding AI state...")
                            new_players = _rebuild_all_players(game, round_ref, self)
                            game.ai_players = new_players
                            round_ref.ai_players = new_players
                            self.ai_players = new_players

                    i = len(self.moves)
                    continue

                # Human move: record but defer reporting to AIs until next flush
                self.played_cards.append(card)
                self.moves.append(Move(seat, card))
                self._move_buffer.append(Move(seat, card))
                i += 1

        # Flush any trailing human moves before closing the trick
        self._flush_buffer()
        self.winner = self.get_winner()
        for p in self.ai_players.values():
            p.handle_finished_trick(self, self.winner)
        print(f"Trick {self.trick_idx} won by {self.winner.player_tag}\n")
