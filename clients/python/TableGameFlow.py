from collections import defaultdict
from typing import List, Optional, Dict, Type

from clients.python.api.Game import Game
from clients.python.api.Player import Player
from clients.python.api.Round import Round
from clients.python.api.Trick import Trick, Move
from clients.python.api.types.Card import Card, Suit
from clients.python.api.types.PassDirection import PassDirection
from clients.python.api.types.PlayerTagSession import PlayerTagSession, PlayerTag
from clients.python.util.table_game.TableGameCLI import TableGameCLI, UndoMove
from clients.python.util.table_game.CardValidation import BlacklistedCardsValidator, UNIQUE_CARDS_VALIDATOR


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
                    p.handle_move(move.player, move.card)
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
                p.handle_move(move.player, move.card)
                if move.player == pts and move.card in current_round.ai_hands[pts]:
                    current_round.ai_hands[pts].remove(move.card)
            p.handle_finished_trick(trick, trick.winner)

        p.handle_new_trick(current_trick)
        for move in current_trick.moves:
            p.handle_move(move.player, move.card)
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

        # Ask for each AI's starting hand; cross-validate against already-entered AI hands
        self.ai_hands: Dict[PlayerTagSession, List[Card]] = {}
        for pts in player_order:
            if pts in ai_players:
                already_dealt = [c for hand in self.ai_hands.values() for c in hand]
                validators = [UNIQUE_CARDS_VALIDATOR, BlacklistedCardsValidator(already_dealt)]
                cards = cli.ask_for_cards(f"Starting hand for {pts.player_tag}", validators, 13)
                self.ai_hands[pts] = cards

        first_hand = next(iter(self.ai_hands.values()), [])
        super().__init__(round_idx, pass_direction, player_order, first_hand)

        self.ai_hands_at_tricks_start: Dict[PlayerTagSession, List[Card]] = {}
        self.ai_received_cards: Dict[PlayerTagSession, List[Card]] = {}
        self.ai_donating_cards: Dict[PlayerTagSession, List[Card]] = {}

    def get_trick_order(self, last_winner: Optional[PlayerTagSession]) -> List[PlayerTagSession]:
        if last_winner is not None:
            first = last_winner
        else:
            # Check if any AI holds 2C; otherwise ask the CLI.
            # Use `or` so ask_for_player is only called when next() returns None
            # (Python evaluates all arguments before calling next(), so passing
            # ask_for_player() directly as the default would always invoke it).
            first = (
                next((pts for pts, hand in self.ai_hands.items() if Card("2C") in hand), None)
                or self.cli.ask_for_player("Who has the 2 of clubs?", self.player_order)
            )
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
        return player_to_points

    def run_round(self, game: 'TableGame'):
        # Notify each AI of round start, pointing round.cards_in_hand at their own hand
        for pts, p in self.ai_players.items():
            self.cards_in_hand = self.ai_hands[pts]
            p.handle_new_round(self)

        # Restore cards_in_hand to first AI for CLI card-tracking features
        if self.ai_hands:
            self.cards_in_hand = next(iter(self.ai_hands.values()))

        if self.pass_direction != PassDirection.KEEPER:
            # Phase 1: get every AI's chosen pass cards and show instructions to the go-between
            for pts, p in self.ai_players.items():
                receiving = self.pass_direction.get_receiving_player(self.player_order, pts)
                donating_cards = p.get_cards_to_pass(self.pass_direction, receiving)
                self.ai_donating_cards[pts] = donating_cards
                self.cli.instruct(f"{pts.player_tag}: pass {donating_cards} to {receiving.player_tag}")

            # Phase 2: resolve what each AI receives
            for pts, p in self.ai_players.items():
                donating = self.pass_direction.get_donating_player(self.player_order, pts)

                if donating in self.ai_players:
                    # Donor is an AI — we already know exactly what they're passing
                    received = list(self.ai_donating_cards[donating])
                    print(f"[auto] {donating.player_tag} passes {received} to {pts.player_tag}")
                else:
                    # Donor is human — ask the go-between; blacklist all cards held by any AI
                    all_ai_cards = [c for hand in self.ai_hands.values() for c in hand]
                    validators = [UNIQUE_CARDS_VALIDATOR, BlacklistedCardsValidator(all_ai_cards)]
                    received = self.cli.ask_for_cards(
                        f"What did {donating.player_tag} pass to {pts.player_tag}?", validators, 3)

                self.ai_received_cards[pts] = received
                new_hand = [c for c in self.ai_hands[pts] + received if c not in self.ai_donating_cards[pts]]
                self.ai_hands[pts].clear()
                self.ai_hands[pts].extend(new_hand)
                p.receive_passed_cards(received, self.pass_direction, donating)

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

            played_cards.extend(m.card for m in table_trick.moves)
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
                p.handle_move(move.player, move.card)
        self._move_buffer.clear()

    def compute_legal_moves(self, hand: List[Card]) -> List[Card]:
        legal = list(hand)
        if self.moves:
            suit = self.moves[0].card.suit
            in_suit = [c for c in legal if c.suit == suit]
            if in_suit:
                legal = in_suit

        hearts_broken = any(c.suit == Suit.HEARTS for c in self.played_cards)
        if not hearts_broken:
            non_hearts = [c for c in legal if c.suit != Suit.HEARTS]
            if non_hearts:
                legal = non_hearts

        if self.trick_idx == 0:
            legal = [c for c in legal if c != Card("QS")] or legal

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
                    p.handle_move(seat, card)
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
