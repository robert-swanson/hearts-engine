import time
from random import shuffle
from typing import List, Dict

from clients.python.api.Trick import Trick
from clients.python.api.networking.ManagedConnection import ManagedConnection
from clients.python.api.networking.SessionHelpers import MakeAndRunMultipleSessions, RunGame, MakeSession, MakeAndRunSession, WaitForAllSessionsToFinish, \
    RunMultipleGames
from clients.python.api.Player import Player
from clients.python.api.Round import Round
from clients.python.api.Game import Game
from clients.python.api.types.Card import Card, GroupCardsBySuit, Rank, SortCardsByRank
from clients.python.players.random_player import RandomPlayer
from clients.python.players.rob_player import RobPlayer
from clients.python.util.Constants import GameType
from clients.python.api.types.PassDirection import PassDirection
from clients.python.api.types.PlayerTagSession import PlayerTagSession


class TimPlayer(Player):
    player_tag = "tim_ai"

    def __init__(self, player_tag_session: PlayerTagSession):
        super().__init__(player_tag_session)
        self.hand = []
        self.shooting_the_moon = False

    # Game
    def initialize_for_game(self, game: Game) -> None:
        print("New Game", game.player_order)
        pass

    def handle_end_game(self, players_to_points: dict[PlayerTagSession, int], winner: PlayerTagSession) -> None:
        print("Game end:",players_to_points)
        pass

    # Round
    def handle_new_round(self, round: Round) -> None:
        self.shooting_the_moon = False
        self.hand = round.cards_in_hand

    def handle_finished_round(self, round: Round, round_points: Dict[PlayerTagSession, int]) -> None:
        pass

    def get_cards_to_pass(self, pass_dir: PassDirection, receiving_player: PlayerTagSession) -> List[Card]:
        # TODO: Make sure to get rid of queen, or Keep queen if I have many spades
        sortedCards = SortCardsByRank(self.hand, True)
        passingCards = sortedCards[:3]
        print(f"Passing cards {passingCards}, of hand {self.hand}")
        return passingCards

    def receive_passed_cards(self, cards: List[Card], pass_dir: PassDirection, donating_player: PlayerTagSession) -> None:
        pass

    # Trick
    def handle_new_trick(self, trick: Trick) -> None:
        pass

    def handle_finished_trick(self, trick: Trick, winning_player: PlayerTagSession) -> None:
        pass

    # Moves
    def handle_move(self, player: PlayerTagSession, card: Card) -> None:
        pass

    def get_move(self, trick: Trick, legal_moves: List[Card]) -> Card:
        if trick.get_suit() == None: 
            return self.play_first_card_in_trick(trick,legal_moves)
        elif self.has_trick_suite(trick):
            return self.play_card_fixed_suite(trick, legal_moves)
        else:
            return self.play_card_any_suite(trick, legal_moves)
    
    def has_trick_suite(self, trick: Trick) -> bool:
        if trick.get_suit() is None:
            raise ValueError("The suit of the trick is None. has_trick_suite should not be called")
        
        # Check if any card in the hand matches the trick's suit
        for card in self.hand:
            if card.suit == trick.get_suit():
                return True  # Found a card that matches the trick's suit
                
        return False  # No card in the hand matches the trick's suit
    
    def play_first_card_in_trick(self, trick:Trick, legal_moves:List[Card]) -> Card:
        # # TODO: If 
        # groupedCards = GroupCardsBySuit(legal_moves)
        # if self.has_queen():
        #     # remove spades from options, we don't want to draw out spades
        sortedCards = SortCardsByRank(legal_moves, False)
        chosenCard = sortedCards[0]
        # print(f"Playing first card in trick,{chosenCard.rank}{chosenCard.suit} ")
        return sortedCards[0]
        

    def play_card_fixed_suite(self, trick:Trick, legal_moves:List[Card]) -> Card:
        #TODO: If the last player, dump the highest card beneath existing threshold instead of the lowest
        # if len(trick.moves)==3:

        # Play lowest rank card to avoid winning the trick
        sortedCards = SortCardsByRank(legal_moves, False)
        chosenCard = sortedCards[0]
        # print(f"Playing fixed suite card,{chosenCard.rank}{chosenCard.suit} ")
        return sortedCards[0]
        

    def play_card_any_suite(self, trick:Trick, legal_moves:List[Card]) -> Card:
        # TODO: If we have a queen, don't ditch spades
        # Ditch highest rank card 
        sortedCards = self.sort_cards_by_points(legal_moves, True)
        chosenCard = sortedCards[0]
        # print(f"Playing any suite card,{chosenCard.rank}{chosenCard.suit} ")
        return sortedCards[0]
        # TODO: ditch a card that clears out a suite


    def get_card_score(self, card:Card) -> float:
        rankPoints =  card.rank.to_int() / 14 / 2
        return card.get_point_value() + rankPoints
    def has_queen(self) -> bool:
        for card in self.hand:
            if card.get_point_value == 13:
                return True
        return False
        # Sort the cards by their point values (in ascending order by default)
    def sort_cards_by_points(self, cards: List[Card], reverse=False) -> List[Card]:
        sorted_cards = sorted(cards, key=lambda card: self.get_card_score(card), reverse=reverse)
        return sorted_cards

if __name__ == '__main__':
    players = [TimPlayer, RandomPlayer, RandomPlayer, RandomPlayer]
    total_games = 0
    games_won = 0
    start_time = time.time()

    with ManagedConnection("tim_player") as connection:
        games = RunMultipleGames(connection, GameType.ANY, players, 16)
        for game_result in games:
            if "tim_ai" in str(game_result[0].winner):
                games_won += 1
            total_games += 1

    print(f"Games won: {games_won}/{total_games} ({games_won / total_games * 100}%)")
    print(f"Time: {time.time() - start_time}")

# To play against another computer
# if __name__ == '__main__':
#     with ManagedConnection() as connection:
#         for i in range(10):
#             sessions = MakeAndRunMultipleSessions(connection, GameType.ANY, TimPlayer, 2)
#             time.sleep(3)
#         WaitForAllSessionsToFinish()
#         print(sessions[0].game_results.winner)