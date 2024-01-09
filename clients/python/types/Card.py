from enum import Enum
from typing import NamedTuple, Dict, Collection, List


class Suit(Enum):
    HEARTS = "H"
    DIAMONDS = "D"
    SPADES = "S"
    CLUBS = "C"

    def __gt__(self, other):
        return self.value > other.value

    def __lt__(self, other):
        return self.value < other.value


class Rank(Enum):
    TWO = "2"
    THREE = "3"
    FOUR = "4"
    FIVE = "5"
    SIX = "6"
    SEVEN = "7"
    EIGHT = "8"
    NINE = "9"
    TEN = "T"
    JACK = "J"
    QUEEN = "Q"
    KING = "K"
    ACE = "A"

    def to_int(self) -> int:
        return {
            Rank.TWO: 2,
            Rank.THREE: 3,
            Rank.FOUR: 4,
            Rank.FIVE: 5,
            Rank.SIX: 6,
            Rank.SEVEN: 7,
            Rank.EIGHT: 8,
            Rank.NINE: 9,
            Rank.TEN: 10,
            Rank.JACK: 11,
            Rank.QUEEN: 12,
            Rank.KING: 13,
            Rank.ACE: 14
        }[self]

    def __gt__(self, other):
        return self.to_int() > other.to_int()

    def __lt__(self, other):
        return self.to_int() < other.to_int()


class Card:
    def __init__(self, card_str: str):
        assert len(card_str) == 2, f"Card str must be 2 chars"
        self.rank = Rank(card_str[0])
        self.suit = Suit(card_str[1])

    def __repr__(self):
        return f"{self.rank.value}{self.suit.value}"


def SortCardsByRank(cards: Collection[Card], reverse=False) -> List[Card]:
    return sorted(cards, key=lambda card: (card.rank, card.suit), reverse=reverse)


def SortCardsBySuit(cards: Collection[Card], reverse=False) -> List[Card]:
    return sorted(cards, key=lambda card: (card.suit, card.rank), reverse=reverse)
