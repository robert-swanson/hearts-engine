import re
from typing import Dict, List, TypeVar, Type, Optional

from clients.python.api.Game import Game
from clients.python.api.types.Card import Card, CondensedDeckRepr
from clients.python.api.types.PassDirection import PassDirection
from clients.python.api.types.PlayerTagSession import PlayerTagSession
from clients.python.util.table_game.CardValidation import UNIQUE_CARDS_VALIDATOR, CardsValidator, _is_valid_card_str


class TableGameCLI:
    def __init__(self, game: Game):
        self.game = game
        self.card_selection = []

    def _get_round(self):
        return self.game.rounds[-1] if len(self.game.rounds) > 0 else None

    def _get_trick(self):
        round = self._get_round()
        return round.tricks[-1] if round is not None and len(round.tricks) > 0 else None

    def _show_hand(self):
        round = self._get_round()
        if round is not None:
            print(round.cards_in_hand)

    def _set_hand(self):
        hand_size = self.input("Hand Size", type_cls=int)
        self._get_round().cards_in_hand = self.ask_for_cards("Set hand", [UNIQUE_CARDS_VALIDATOR], hand_size)

    def _print_player_possible_cards(self):
        players = self.game.player_order
        self_player = [p for p in players if p.player_tag == self.game.table_player][0]
        player_to_possible_cards: Dict[PlayerTagSession, List[Card]] = {player: Card.make_deck() for player in players}
        player_to_guaranteed_cards: Dict[PlayerTagSession, List[Card]] = {player: [] for player in players}

        def eliminate_cards(player, cards):
            for card in cards:
                if card in player_to_possible_cards[player]:
                    player_to_possible_cards[player].remove(card)

        def guarantee_cards(player, cards):
            [eliminate_cards(p, cards) for p in players]
            player_to_guaranteed_cards[player].extend(cards)

        def num_cards_in_players_hand(player):
            curr_trick = self._get_trick()
            if curr_trick is None:
                return 13
            else:
                player_has_moved = player in [m.player for m in curr_trick.moves]
                return 13 - self._get_trick().trick_idx + (1 if player_has_moved else 0)

        # Process passes and hand
        round = self._get_round()
        guarantee_cards(self_player, round.cards_in_hand)
        if round.pass_direction != PassDirection.KEEPER:
            guarantee_cards(round.receiving_player, round.donating_cards)
            guarantee_cards(self_player, round.received_cards)

        # Process tricks
        for trick in round.tricks:
            trick_suit = trick.moves[0].card.suit if len(trick.moves) > 0 else None
            for move in trick.moves:
                [eliminate_cards(p, [move.card]) for p in players]
                if move.card.suit != trick_suit:
                    player_to_possible_cards[move.player] = [card for card in player_to_possible_cards[move.player] if
                                                             card.suit != trick_suit]

        # Process of elimination
        change_made = True
        while change_made:
            change_made = False
            for player in players:
                for card in player_to_possible_cards[player]:
                    if not any([card in player_to_possible_cards[p] for p in players if p != player]):
                        guarantee_cards(player, [card])
                        change_made = True
                num_cards = num_cards_in_players_hand(player)
                known_cards = len(player_to_guaranteed_cards[player])
                possible_cards = len(player_to_possible_cards[player])
                if known_cards == num_cards:
                    if len(player_to_guaranteed_cards[player]) > 0:
                        eliminate_cards(player, player_to_possible_cards[player])
                        change_made = True
                elif known_cards + possible_cards == num_cards:
                    guarantee_cards(player, player_to_possible_cards[player])
                    change_made = True

        for player in players:
            if player == self_player:
                continue

            guaranteed = player_to_guaranteed_cards[player]
            possible = player_to_possible_cards[player]

            print(f"{player} ({num_cards_in_players_hand(player)} cards): Known {CondensedDeckRepr(guaranteed)} | Possible {CondensedDeckRepr(possible)}")

    def _check_card_cmds(self, input_str: str):
        input_str = input_str.lower().strip()

        cmd_to_func = {
            "show hand": lambda: self._show_hand(),
            "set hand": self._set_hand,
            "show selection": lambda: print(self.card_selection),
            "clear selection": self.card_selection.clear,
            "show possible cards": self._print_player_possible_cards,
        }

        cmd_to_func["help"] = lambda: print("\n".join(cmd_to_func.keys()) + "\n")

        if input_str in cmd_to_func:
            print("\033[F\033[K", end="")
            print("> " + input_str)
            cmd_to_func[input_str]()
            return True

    T = TypeVar("T")

    def input(self, prompt: str, type_cls: Type[T] = str) -> T:
        input_str = input(prompt)

        if self._check_card_cmds(input_str):
            return self.input(prompt, type_cls)
        else:
            return type_cls(input_str)

    def ask_for_card(self, prompt: str, validators: List[CardsValidator],
                     validate_with: Optional[List[Card]] = None) -> Card:
        if validate_with is None:
            validate_with = []
        while True:
            card_str = self.input(prompt + " ").upper()
            if not _is_valid_card_str(card_str, validators, validate_with):
                continue
            return Card(card_str)

    CARD_LIST_PATTERN = r"^(\w{2}[\s\t\,]*)+$"
    SUIT_GROUP_PATTERN = rf"([CDHS]):\s*(.*)"

    def ask_for_cards(self, prompt: str, validators: List[CardsValidator], num_cards: int,
                      validate_with: Optional[List[Card]] = None) -> List[Card]:
        if validate_with is None:
            validate_with = []
        self.card_selection = []
        while len(self.card_selection) < num_cards:
            cards_line = self.input(f"{prompt}, card {len(self.card_selection) + 1}/{num_cards}: ")
            cards_line = cards_line.upper().strip()
            line_cards = []

            suit_group_match = re.match(self.SUIT_GROUP_PATTERN, cards_line)
            if suit_group_match is not None:
                suit = suit_group_match.group(1)
                cards_line = suit_group_match.group(2)
            else:
                suit = ""

            for card_str in re.split(r'[\s\t,]+', cards_line):
                card_str = card_str.strip(" \t") + suit
                if not _is_valid_card_str(card_str, validators, validate_with + line_cards + self.card_selection):
                    break
                line_cards.append(Card(card_str))
            else:
                if len(self.card_selection) > num_cards:
                    print(f"Expected {num_cards} cards, got {len(self.card_selection)}")
                    continue
                self.card_selection.extend(line_cards)

        return self.card_selection

    def ask_for_player(self, prompt: str, players: List[PlayerTagSession]) -> PlayerTagSession:
        while True:
            player_str = self.input(prompt + " ")
            for player in players:
                if player_str == str(player) or player_str == str(player.player_tag):
                    return player
            print(f"Invalid player '{player_str}' must be one of {players}")

    @staticmethod
    def instruct(prompt: str) -> None:
        print(prompt)
