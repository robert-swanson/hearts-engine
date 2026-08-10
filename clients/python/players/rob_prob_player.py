import os
import random
import sys
import time
from pathlib import Path
from typing import List, Dict, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from clients.python.api import Game
from clients.python.api.Trick import Trick
from clients.python.api.networking.ManagedConnection import ManagedConnection
from clients.python.api.networking.SessionHelpers import RunMultipleGames, MakeAndRunMultipleSessions, WaitForAllSessionsToFinish
from clients.python.api.Player import Player
from clients.python.api.Round import Round
from clients.python.api.types.Card import Card, Suit, Rank, SortCardsByRank, GroupCardsBySuit
from clients.python.players.rob_player import RobPlayer
from clients.python.util.Constants import GameType
from clients.python.util.probability_table import ProbabilityTable, Deal
from clients.python.api.types.PassDirection import PassDirection
from clients.python.api.types.PlayerTagSession import PlayerTagSession, PlayerTag


# Per-trick risk posture: the maximum win probability we tolerate on trick i.
# Index 0 (trick 0) is 1.0 (we never dodge the opening trick), and the array is
# meant to be non-increasing. This is the knob tune_acceptable_failures.py
# optimizes; it overrides the default at runtime via the env var below (a
# comma-separated list of 13 floats) so the tuner can try candidates without
# editing this file. Falls back to the hand-tuned default when unset/malformed.
DEFAULT_ACCEPTABLE_FAILURES = [1.0, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1, 0.05, 0.025, 0.0125, 0.00625]
ACCEPTABLE_FAILURES_ENV = "ROB_PROB_ACCEPTABLE_FAILURES"


def _load_acceptable_failures() -> List[float]:
    raw = os.environ.get(ACCEPTABLE_FAILURES_ENV)
    if not raw:
        return list(DEFAULT_ACCEPTABLE_FAILURES)
    try:
        vals = [float(x) for x in raw.split(",") if x.strip() != ""]
    except ValueError:
        print(f"WARN: could not parse {ACCEPTABLE_FAILURES_ENV}={raw!r}; using default",
              file=sys.stderr)
        return list(DEFAULT_ACCEPTABLE_FAILURES)
    if len(vals) != len(DEFAULT_ACCEPTABLE_FAILURES):
        print(f"WARN: {ACCEPTABLE_FAILURES_ENV} has {len(vals)} values, "
              f"expected {len(DEFAULT_ACCEPTABLE_FAILURES)}; using default", file=sys.stderr)
        return list(DEFAULT_ACCEPTABLE_FAILURES)
    return vals


ACCEPTABLE_FAILURES = _load_acceptable_failures()
if os.environ.get(ACCEPTABLE_FAILURES_ENV):
    print(f"rob_prob_player: acceptable_failures = {ACCEPTABLE_FAILURES}", file=sys.stderr)


class RobProbPlayer(Player):
    player_tag = "rob_prob_player"
    message_print_logging_enabled = False
    move_logging_enabled = False # <---- flip for debugging

    def __init__(self, player_tag_session: PlayerTagSession):
        super().__init__(player_tag_session)
        self.current_round: Optional[Round] = None
        self.probability_table: Optional[ProbabilityTable] = None

    def log(self, m: str):
        if self.move_logging_enabled:
            print(m)

    # Game
    def initialize_for_game(self, game: Game) -> None:
        pass

    def handle_end_game(self, players_to_points: dict[PlayerTagSession, int], winner: PlayerTagSession) -> None:
        pass

    # Round
    def handle_new_round(self, round: Round) -> None:
        self.starting_hand = round.cards_in_hand
        self.current_round = round
        self.probability_table = ProbabilityTable(self.current_round.player_order)
        for card in self.starting_hand:
            self.probability_table.assign(self.player_tag_session, card)

    def handle_finished_round(self, round: Round, round_points: Dict[PlayerTagSession, int]) -> None:
        pass

    def get_cards_to_pass(self, pass_dir: PassDirection, receiving_player: PlayerTagSession) -> List[Card]:
        cards_to_pass = []

        # First, get rid of AS, KS, QS if we have any.
        cards_to_pass += [c for c in self.starting_hand if c in [Card(Rank.ACE, Suit.SPADES), Card(Rank.KING, Suit.SPADES), Card(Rank.QUEEN, Suit.SPADES)]]

        suit_cards = sorted(GroupCardsBySuit(SortCardsByRank(self.starting_hand, reverse=True)).items(), key=lambda kv: len(kv[1]))
        present_suits = [sc[0] for sc in suit_cards]
        voided_suits = [s for s in Suit if s not in present_suits]

        # Then see if there are any suits we can void.
        for suit, cards in suit_cards:
            if len(voided_suits) >= 1:
                # If we already have a voided suit, lets save the rest of our passing cards for high rank.
                break
            # If we can void, or almost void a suit, do so.
            if suit != Suit.SPADES and suit != Suit.HEARTS and len(cards_to_pass) + len(cards) <= 3 + 1:
                if (len(cards_to_pass) + len(cards) <= 3):
                    voided_suits.append(suit)
                num_suit_cards_to_pass = min(len(cards), 3 - len(cards_to_pass))
                cards_to_pass += cards[:num_suit_cards_to_pass]
                

        ranked_cards = SortCardsByRank(self.starting_hand, reverse=True)
        cards_to_pass += [c for c in ranked_cards if c not in cards_to_pass][:(3-len(cards_to_pass))]

        assert len(cards_to_pass) == 3

        # Update probabilities
        receiving_player = pass_dir.get_receiving_player(self.current_round.player_order, self.player_tag_session)
        for card in cards_to_pass:
            self.probability_table.reassign(receiving_player, card)

        return cards_to_pass

    def receive_passed_cards(self, cards: List[Card], pass_dir: PassDirection, donating_player: PlayerTagSession) -> None:
        # Update probabilities
        for card in cards:
            self.probability_table.assign(self.player_tag_session, card)
    # Trick
    def handle_new_trick(self, trick: Trick) -> None:
        pass

    def handle_finished_trick(self, trick: Trick, winning_player: PlayerTagSession) -> None:
        pass

    # Moves
    def handle_move(self, trick: Trick, player: PlayerTagSession, card: Card,
                    report_latency_ms=None, decided_move_latency_ms=None) -> None:
        trick_suit = trick.get_suit()
        if trick_suit is not None and trick_suit != card.suit:
            # Player couldn't follow suit, so they hold no card of the trick suit.
            for rank in Rank:
                self.probability_table.rule_out(player, Card(rank, trick_suit))
        self.probability_table.play(player, card)

    def get_move(self, trick: Trick, legal_moves: List[Card], move_request_latency_ms=None) -> Card:
        assert len(legal_moves) > 0, "Must have at least one legal move"
        if len(legal_moves) == 1:
            return legal_moves[0]
        if self.is_worried_about_shooting_the_moon():
            self.log("Is worried about moon shot")
            return self.get_move_likely_to_win_trick(trick, legal_moves)
        else:
            risk_tolerance = ACCEPTABLE_FAILURES[trick.trick_idx]
            # Take the trick if playing last, no points are played, and we have a reasonable card to lead with.
            if len(trick.moves) == 3 and sum([m.card.get_point_value() for m in trick.moves]) == 0:
                min_rank = min([c.rank.to_int() for c in self.current_round.cards_in_hand])
                if min_rank <= 6: 
                    risk_tolerance = 1.0
            return self.get_move_unlikely_to_win_trick(self.current_round, trick, self.player_tag_session, legal_moves, risk_tolerance)


    def get_move_unlikely_to_win_trick(self, round: Round, trick: Trick, this_player: PlayerTagSession, legal_moves: List[Card], max_acceptable_win_probability: float) -> Card:
        class MoveAnalysis:
            move: Card
            dump_value: float
            win_probability: float
            min_score: int
            notes = ""

        moves_analysis: List[MoveAnalysis] = []
        points_played = sum([m.card.get_point_value() for m in trick.moves])
        queen_played = Card(Rank.QUEEN, Suit.SPADES) in round.get_played_cards()
        has_high_spade = len({Card(Rank.QUEEN, Suit.SPADES),Card(Rank.KING, Suit.SPADES),Card(Rank.ACE, Suit.SPADES)}.intersection(round.cards_in_hand)) > 0

        suit_to_num_in_hand = {s: len([c for c in round.cards_in_hand if c.suit == s]) for s in Suit}
        suit_to_num_unplayed_others = {s: len([r for r in Rank if Card(r, s) not in round.get_played_cards() and not Card(r,s) in round.cards_in_hand]) for s in Suit}
        if len(trick.moves) == 0 and len({c.suit for c in round.cards_in_hand}) == 1:
            self.log("Leading with single suit hand: play lowest")
            return SortCardsByRank(legal_moves)[0]

        played = round.get_played_cards()
        for move in legal_moves:
            moves_analysis.append(MoveAnalysis())
            a = moves_analysis[-1]
            a.move = move
            a.min_score = points_played + move.get_point_value()

            trick_suit = trick.get_suit() or move.suit
            # Determine the value of getting rid of this card.
            a.dump_value = move.rank.to_int()
            if move.suit == Suit.SPADES and not queen_played and has_high_spade:
                if move.rank.to_int() <= Rank.JACK.to_int():
                    a.dump_value = move.rank.to_int()/20.0
                    a.notes += "removing dump value due to spade risk, "
                elif move == Card(Rank.QUEEN, Suit.SPADES):
                    a.dump_value = 100
                elif move == Card(Rank.KING, Suit.SPADES):
                    a.dump_value = 50
                elif move == Card(Rank.ACE, Suit.SPADES):
                    a.dump_value = 60
            else:
                cards_after_void = max(0, suit_to_num_unplayed_others[move.suit] - (suit_to_num_in_hand[move.suit] - 1)*2 - (3-len(trick.moves)))
                a.notes += f"cards_after_void={cards_after_void}, unplayed_others={suit_to_num_unplayed_others[move.suit]}, num_in_hand={suit_to_num_in_hand[move.suit]}, trick_left={3-len(trick.moves)}, "

                a.dump_value += cards_after_void * 2

            current_winning_rank = max([0] + [m.card.rank.to_int() for m in trick.moves if m.card.suit == trick_suit])
            if move.suit != trick_suit or move.rank.to_int() < current_winning_rank:
                a.win_probability = 0.0
                a.notes += "below existing"
            elif len(trick.moves) == 3:
                a.win_probability = 1.0  # last move would definitely win
                a.notes += "last move win"
            else:
                suit_cards = [Card(r, trick_suit) for r in Rank]
                unplayed_suit = [c for c in suit_cards if c not in played and c != move]

                player_idx = round.player_order.index(this_player)
                players_after = [round.player_order[(player_idx + i) % 4]
                                 for i in range(1, 4 - len(trick.moves))]

                def could_win(deal: Deal) -> bool:
                    # I win unless a player still to act holds a higher card of the led suit.
                    potential_takers = players_after
                    for c in unplayed_suit:
                        player: Optional[PlayerTagSession] = deal[c]
                        if player is not None and player in potential_takers:
                            if c.rank > move.rank:
                                return False
                            else:
                                potential_takers.remove(player)
                                if len(potential_takers) == 0:
                                    return True
                    return True


                def random_would_win(deal: Deal) -> bool:
                    # For use in situations where its not obvious that a player would play lowest card.
                    # Assume other players will choose a random card from their hand.
                    players_to_cards: Dict[PlayerTagSession, List[Card]] = {p: [] for p in round.player_order}
                    for c in unplayed_suit:
                        p = deal[c]
                        if p:
                            players_to_cards[p].append(c)

                    any_points_played = False
                    for player in players_after:
                        cards = players_to_cards[player]
                        if any_points_played and cards:
                            if cards[0].rank > move.rank:
                                return False
                        else:
                            if cards and random.choice(cards).rank > move.rank:
                                return False
                            elif deal[Card(Rank.QUEEN, Suit.SPADES)] == player:
                                any_points_played  = True
                            else:
                                for rank in Rank:
                                    if deal[Card(rank, Suit.HEARTS)] == player:
                                        any_points_played = True
                                        break

                    return True


                if a.min_score > 0 or trick_suit == Suit.HEARTS or (trick_suit == Suit.SPADES and move.rank.to_int() >= Rank.QUEEN.to_int() and not queen_played):
                    a.win_probability = self.probability_table.estimate(could_win, n=100)
                    a.notes += "carlo=could_win"
                else:
                    a.win_probability = self.probability_table.estimate(random_would_win, n=100)
                    a.notes += "carlo=random_win"

                if a.win_probability > 0 and a.win_probability < 1:
                    # Odds of saftey cut in half by each point
                    points_at_risk = points_played + move.get_point_value()
                    if move == Card(Rank.KING, Suit.SPADES) or move == Card(Rank.QUEEN, Suit.SPADES):
                        points_at_risk = min(points_at_risk, 13)
                    if (move.suit == Suit.HEARTS):
                        points_at_risk += 3-len(trick.moves)
                    if points_at_risk:
                        a.notes += f", original prob={a.win_probability:.2%}"
                        a.win_probability = 1.0 - ((1.0 - a.win_probability) / (2 ** points_at_risk))

        # Choose Move
        moves_under_risk = [a for a in moves_analysis if a.win_probability <= max_acceptable_win_probability]
        rv = None
        self.log(f"{len(moves_under_risk)} moves under risk {max_acceptable_win_probability:.0%}")
        self.log("Move\tWin Probability\tDump Value\tNotes")
        ranked_moves = []
        if moves_under_risk:
            # From moves under risk: Avoid points if we can, choose highest dump value, then lowest win probability.
            ranked_moves = sorted(moves_under_risk, key=lambda a: (a.min_score * (a.win_probability > 0), 100-a.dump_value, a.win_probability))
            for move in ranked_moves:
                self.log(f"{move.move}\t{move.win_probability:.1%}\t\t\t{move.dump_value}\t\t{move.notes}")
            if self.move_logging_enabled:
                moves_over_risk = [m for m in moves_analysis if m.win_probability > max_acceptable_win_probability]
                for move in sorted(moves_over_risk, key=lambda a: (a.win_probability, 100-a.dump_value, a.min_score)):
                    self.log(f"{move.move} (X)\t{move.win_probability:.1%}\t\t\t{move.dump_value}\t\t{move.notes}")
        else:
            # Choose move that isn't certainly going to win, with lowest score, then lowest win probability, then highest dump value
            ranked_moves = sorted(moves_analysis, key=lambda a: (a.win_probability == 1.0, a.min_score, a.win_probability, 100-a.dump_value))
            if self.move_logging_enabled:
                for move in ranked_moves:
                    self.log(f"{move.move}\t{move.win_probability:.1%}\t\t\t{move.dump_value}\t\t{move.notes}")
        return ranked_moves[0].move


    @staticmethod
    def get_move_likely_to_win_trick(trick: Trick, legal_moves: List[Card]) -> Card:
        return SortCardsByRank(legal_moves)[-1]

    def is_worried_about_shooting_the_moon(self) -> bool:
        player_points = self.current_round.get_round_points()
        num_players_with_points = len([p for p, pts in player_points.items() if pts > 0])

        if num_players_with_points != 1:
            return False

        queen_played = Card(Rank.QUEEN, Suit.SPADES) in self.current_round.get_played_cards()
        points = list(player_points.values())[0]

        return queen_played and points > 18 or not queen_played and points > 8


if __name__ == '__main__':
    players = [RobProbPlayer, RobPlayer, RobPlayer, RobPlayer]
    total_games = 0
    games_won = 0
    start_time = time.time()

    with ManagedConnection() as connection:
        game_results = RunMultipleGames(connection, GameType.ANY, players, 10)
        for game_result in game_results:
            if "rob_player" in str(game_result.winner):
                games_won += 1
            total_games += 1

    print(f"Games won: {games_won}/{total_games} ({games_won / total_games * 100}%)")
    print(f"Time: {time.time() - start_time}")

if __name__ == '__main__':
    with ManagedConnection() as connection:

        for i in range(10):
            MakeAndRunMultipleSessions(connection, GameType.ANY, RobProbPlayer, 2, lobby_code="ROB_{i}")
            time.sleep(3)
        WaitForAllSessionsToFinish()
