from abc import ABC, abstractmethod
from typing import List, Dict

from clients.python.api.Game import Game
from clients.python.api.Round import Round
from clients.python.api.Trick import Trick
from clients.python.api.types.Card import Card
from clients.python.api.types.PassDirection import PassDirection
from clients.python.api.types.PlayerTagSession import PlayerTagSession, PlayerTag


class Player(ABC):
    player_tag: PlayerTag = None
    message_print_logging_enabled: bool = False

    def __init__(self, player_tag_session: PlayerTagSession):
        self.player_tag_session = player_tag_session
        assert self.player_tag is not None, "Player must have a player_tag"
        assert self.player_tag_session.player_tag == self.player_tag, "PlayerTagSession must have the same player_tag as the Player"

    # Game
    def initialize_for_game(self, game: Game) -> None:
        """
        Signals the start of the game
        :param game: Reference object that points to the rounds as well as will ultimately contain the game results
        """
        pass

    def handle_end_game(self, players_to_points: dict[PlayerTagSession, int], winner: PlayerTagSession) -> None:
        """
        Signals the end of the game and includes information about the game results
        :param players_to_points: A dictionary that maps each player to their score
        :param winner: The player who won the game
        """
        pass

    # Round
    def handle_new_round(self, round: Round) -> None:
        """
        Signals the start of a new round
        :param round: A reference object that contains the round number, the pass direction, the player order, and the cards in hand, as well as references to its tricks
        """
        pass

    def handle_finished_round(self, round: Round, round_points: Dict[PlayerTagSession, int]) -> None:
        """
        Signals the end of a round and includes information about the round results
        :param round: A reference object (same as passed by `handle_new_round`) that can be queried for information about the round
        :param round_points: A dictionary that maps each player to their non-cumulative score for the round
        """
        pass

    @abstractmethod
    def get_cards_to_pass(self, pass_dir: PassDirection, receiving_player: PlayerTagSession) -> List[Card]:
        """
        Signals the start of the passing phase and requests the player to select cards to pass
        :param pass_dir: The direction the cards will be passed
        :param receiving_player: The player who will receive the cards
        :return: A list of 3 cards to pass
        """
        pass

    def receive_passed_cards(self, cards: List[Card], pass_dir: PassDirection, donating_player: PlayerTagSession) -> None:
        """
        Signals the end of the passing phase and includes the cards that were passed
        :param cards: A list of the 3 cards that were passed to the player
        :param pass_dir: The direction the cards were passed
        :param donating_player: The player who passed the cards
        """
        pass

    # Trick
    def handle_new_trick(self, trick: Trick) -> None:
        """
        Signals the start of a new trick
        :param trick: A reference object that contains the player order as well as pointers to moves as they are made
        """
        pass

    def handle_finished_trick(self, trick: Trick, winning_player: PlayerTagSession) -> None:
        """
        Signals the end of a trick and includes information about the trick results
        :param trick: A reference object (same as passed by `handle_new_trick`) that can be queried for information about the trick
        :param winning_player: The player who won the trick (and will start next trick)
        """
        pass

    # Moves
    def handle_move(self, player: PlayerTagSession, card: Card) -> None:
        """
        Signals that a move was made by a player (including self)
        :param player: The player who made the move
        :param card: The card that was played
        """
        pass

    @abstractmethod
    def get_move(self, trick: Trick, legal_moves: List[Card]) -> Card:
        """
        Signals that it is the player's turn and requests the player to select a card to play
        :param trick: A reference object that contains the player order as well as pointers to moves as they are made
        :param legal_moves: A list of the cards that the player is allowed to play
        :return: The card to play
        """
        pass
