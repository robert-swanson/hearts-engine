from collections import defaultdict
from typing import List, Optional, Dict, Tuple

from clients.python.api.Game import PrivilegedGame
from clients.python.api.Player import Player
from clients.python.api.Round import Round
from clients.python.api.Trick import Trick, Move
from clients.python.api.networking.PlayerGameSession import Player_T
from clients.python.api.types.Card import Card, Suit
from clients.python.api.types.PassDirection import PassDirection
from clients.python.api.types.PlayerTagSession import PlayerTagSession, PlayerTag
from clients.python.util.table_game.TableGameCLI import TableGameCLI
from clients.python.util.table_game.CardValidation import BlacklistedCardsValidator, UNIQUE_CARDS_VALIDATOR


class TablePrivateGame(PrivilegedGame):
    def __init__(self, player_cls: Player_T, player_order: List[str]):
        self.table_player = PlayerTag(player_cls.player_tag)
        player_order = [PlayerTag(player_tag) for player_tag in player_order]
        assert self.table_player in player_order, f"Must have {self.table_player} in player order list: {player_order}"
        assert len(player_order) == 4, "Must have 4 players"
        player_tag_session_order = [PlayerTagSession(player_tag, i + 1) for i, player_tag in enumerate(player_order)]
        super().__init__(player_tag_session_order)
        self.player_cls = player_cls
        self.cli = TableGameCLI(self)

    def run_game(self):
        print(f"Starting game with players: {self.player_order}")
        player = self.player_cls(self.player_order[0])
        player.initialize_for_game(self)

        pass_direction = self.cli.ask_for_pass_direction("Starting pass direction", PassDirection.LEFT)
        players_to_points: Dict[PlayerTagSession, int] = defaultdict(int)

        while True:
            table_round = TableRound(player, self.cli, self.player_order, len(self.rounds), pass_direction)
            self.rounds.append(table_round)
            table_round.run_round()
            pass_direction = pass_direction.next_pass_direction()

            round_points = table_round.get_round_points()
            for name, points in round_points.items():
                players_to_points[name] += points

            print(f"Current rankings: ")
            rankings = sorted(players_to_points.items(), key=lambda kv: kv[1])
            for i, (name, points) in enumerate(rankings):
                print(f"\t{i + 1}. {name.player_tag} - {points} pts")

            if rankings[-1][1] >= 100:
                break


class TableRound(Round):
    def __init__(self, player: Player, cli: TableGameCLI, player_order: List[PlayerTagSession], round_idx: int,
                 pass_direction: PassDirection):
        cards = cli.ask_for_cards("Starting hand", [UNIQUE_CARDS_VALIDATOR], 13)
        super().__init__(round_idx, pass_direction, player_order, cards)
        self.player = player
        self.cli = cli

    def get_trick_order(self, last_winner: Optional[PlayerTagSession]) -> List[PlayerTagSession]:
        first_player = self.cli.ask_for_player("Who has the 2 of clubs?", self.player_order) if last_winner is None else last_winner
        start_idx = self.player_order.index(first_player)
        return self.player_order[start_idx:] + self.player_order[:start_idx]

    def get_round_points(self) -> Dict[PlayerTagSession, int]:
        player_to_points: Dict[PlayerTagSession, int] = {}
        for player in self.player_order:
            player_to_points[player] = 0
        for trick in self.tricks:
            hearts = len([move for move in trick.moves if move.card.suit == Suit.HEARTS])
            had_qs = any([move.card == Card("QS") for move in trick.moves])
            player_to_points[trick.winner] += hearts + (13 if had_qs else 0)
        return player_to_points

    def run_round(self):
        self.player.handle_new_round(self)

        if self.pass_direction != PassDirection.KEEPER:
            self.receiving_player = self.pass_direction.get_receiving_player(self.player_order,
                                                                        self.player.player_tag_session)
            self.donating_player = self.pass_direction.get_donating_player(self.player_order, self.player.player_tag_session)
            self.donating_cards = self.player.get_cards_to_pass(self.pass_direction, self.receiving_player)
            self.cli.instruct(f"Pass {self.donating_cards} {self.pass_direction} to {self.receiving_player}")

            validators = [UNIQUE_CARDS_VALIDATOR, BlacklistedCardsValidator(self.received_cards)]
            self.received_cards = self.cli.ask_for_cards(f"What cards were received from {self.donating_player}?", validators, 3, self.cards_in_hand)
            self.cards_in_hand = [c for c in self.cards_in_hand + self.received_cards if c not in self.donating_cards]
            self.player.receive_passed_cards(self.received_cards, self.pass_direction, self.donating_player)

        played_cards = []
        last_winner = None
        if Card("2C") in self.cards_in_hand:
            last_winner = self.player.player_tag_session

        for trick_idx in range(13):
            trick_order = self.get_trick_order(last_winner)
            table_trick = TableTrick(self.player, self.cli, trick_idx, trick_order, self.cards_in_hand, played_cards)
            self.tricks.append(table_trick)
            table_trick.run_trick()
            self.cards_in_hand = table_trick.hand

            played_cards.extend([move.card for move in table_trick.moves])
            last_winner = table_trick.get_winner()

        round_points = self.get_round_points()
        self.player.handle_finished_round(self, round_points)
        print(f"Round points: {','.join([f'{player.player_tag}: {points}' for player, points in round_points.items()])}\n")


class TableTrick(Trick):
    def __init__(self, player: Player, cli: TableGameCLI, trick_idx: int, player_order: List[PlayerTagSession], hand: List[Card],
                 played_cards: List[Card]):
        self.trick_idx = trick_idx
        self.player_order: List[PlayerTagSession] = player_order
        self.player = player
        self.hand = hand
        self.played_cards = played_cards
        self.cli = cli
        Trick.__init__(self, trick_idx, player_order)

    def compute_legal_moves(self) -> List[Card]:
        legal_moves = self.hand
        if len(self.moves) > 0:
            suit = self.moves[0].card.suit
            legal_moves = [card for card in legal_moves if card.suit == suit]
            if not legal_moves:
                legal_moves = self.hand

        hearts_broken = any([card.suit == Suit.HEARTS for card in self.played_cards])
        if not hearts_broken:
            legal_moves = [card for card in legal_moves if card.suit != Suit.HEARTS]

        if self.trick_idx == 0:
            legal_moves = [card for card in legal_moves if card != Card("QS")]

        return legal_moves

    def get_winner(self) -> PlayerTagSession:
        suit = self.moves[0].card.suit
        winning_move = max([move for move in self.moves if move.card.suit == suit], key=lambda move: move.card.rank)
        return winning_move.player

    def run_trick(self):
        self.player.handle_new_trick(self)
        for player in self.player_order:
            if player == self.player.player_tag_session:
                legal_moves = self.compute_legal_moves()
                card = self.player.get_move(self, legal_moves)
                self.cli.instruct(f"Play {card}")
                self.hand.remove(card)
            else:
                validators = [BlacklistedCardsValidator(self.played_cards), BlacklistedCardsValidator(self.hand)]
                card = self.cli.ask_for_card(f"What card did {player} play?", validators)

            self.played_cards.append(card)
            self.moves.append(Move(player, card))
            self.player.handle_move(player, card)

        self.winner = self.get_winner()
        self.player.handle_finished_trick(self, self.winner)
        print(f"Trick {self.trick_idx} won by {self.winner}\n")


