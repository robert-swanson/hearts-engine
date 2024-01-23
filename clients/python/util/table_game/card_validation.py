from abc import ABC
from typing import List, Collection, Optional

from clients.python.api.types.Card import Card


class CardsValidator(ABC):
    def is_valid(self, cards: List[Card]) -> bool:
        pass


class UniqueCardsValidator(CardsValidator):
    def is_valid(self, cards: List[Card]) -> bool:
        redundant_cards = [card for card in cards if cards.count(card) > 1]
        if len(redundant_cards) > 0:
            print(f"Duplicate card(s): {set(redundant_cards)}")
        return len(redundant_cards) == 0


class BlacklistedCardsValidator(CardsValidator):
    def __init__(self, blacklisted_cards: Collection[Card]):
        self.blacklisted_cards = blacklisted_cards

    def is_valid(self, cards: List[Card]) -> bool:
        blacklisted_cards = [card for card in cards if card in self.blacklisted_cards]
        if len(blacklisted_cards) > 0:
            print(f"Unexpected card(s): {blacklisted_cards}")
        return len(blacklisted_cards) == 0


UNIQUE_CARDS_VALIDATOR = UniqueCardsValidator()


def _is_valid_card_str(card_str: str, validators: List[CardsValidator],
                       validate_with: Optional[List[Card]] = None) -> bool:
    try:
        card = Card(card_str)
    except Exception as e:
        print(f"Error parsing '{card_str}': {e}")
        return False
    for validator in validators:
        validate_with = validate_with if validate_with is not None else []
        if not validator.is_valid([card] + validate_with):
            return False
    return True
