from abc import ABC
from typing import List, Optional, Dict, Tuple, NamedTuple, Set

from clients.python.types.Card import Card, Suit
from clients.python.types.PassDirection import PassDirection
from clients.python.types.PlayerTagSession import PlayerTagSession, PlayerTag


class Game:
    def __init__(self, player_order: List[PlayerTagSession]):
        self.player_order = player_order
        self.rounds: List[Round] = []
        self.winner: Optional[PlayerTagSession] = None


class Round:
    def __init__(self, round_idx: int, pass_direction: PassDirection, player_order: List[PlayerTagSession], cards_in_hand: List[Card]):
        self.round_idx = round_idx
        self.pass_direction = pass_direction
        self.player_order = player_order
        self.cards_in_hand = cards_in_hand

        self.donating_cards: List[Card] = []
        self.received_cards: List[Card] = []
        self.tricks: List[Trick] = []

    def get_round_points(self) -> Dict[PlayerTagSession, int]:
        player_to_points = {player: 0 for player in self.player_order}
        for trick in self.tricks:
            if trick.winner is not None:
                player_to_points[trick.winner] += trick.get_current_point_value()
        return player_to_points

    def get_played_cards(self) -> Set[Card]:
        return {move.card for trick in self.tricks for move in trick.moves}


class Move(NamedTuple):
    player: PlayerTagSession
    card: Card

    def __repr__(self):
        return self.card.__repr__()


class Trick:
    def __init__(self, trick_idx: int, player_order: List[PlayerTagSession]):
        self.trick_idx = trick_idx
        self.player_order = player_order

        self.moves: List[Move] = []
        self.winner: Optional[PlayerTagSession] = None

    def __repr__(self):
        if self.winner is None:
            return f"[{self.moves}]"
        else:
            return f"[{self.moves}] won by {self.winner}"

    def get_suit(self) -> Optional[Suit]:
        if len(self.moves) == 0:
            return None
        else:
            return self.moves[0].card.suit

    def get_current_point_value(self) -> int:
        return sum(move.card.get_point_value() for move in self.moves)


class Player(ABC):
    player_tag: PlayerTag = None
    message_logging_enabled: bool = False

    def __init__(self, player_tag_session: PlayerTagSession):
        self.player_tag_session = player_tag_session

    # Game
    def initialize_for_game(self, game: Game) -> None:
        pass

    def handle_end_game(self, players_to_points: dict[PlayerTagSession, int], winner: PlayerTagSession) -> None:
        pass

    # Round
    def handle_new_round(self, round: Round) -> None:
        pass

    def handle_finished_round(self, round: Round, round_points: Dict[PlayerTagSession, int]) -> None:
        pass

    def get_cards_to_pass(self, pass_dir: PassDirection, receiving_player: PlayerTagSession) -> List[Card]:
        pass

    def receive_passed_cards(self, cards: List[Card], pass_dir: PassDirection, donating_player: PlayerTagSession) -> None:
        pass

    # Trick
    def handle_new_trick(self, trick: Trick) -> None:
        pass

    def handle_finished_trick(self, trick: Trick, winning_player: PlayerTagSession) -> None:
        pass

    # Moves
    def handle_move(self, player: PlayerTagSession, card: Card) -> None:
        """Handle a move from any player (including this one)"""
        pass

    def get_move(self, trick: Trick, legal_moves: List[Card]) -> Card:
        pass
