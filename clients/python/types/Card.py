from enum import Enum
from typing import NamedTuple


class Suit(Enum):
    HEARTS = "H"
    DIAMONDS = "D"
    SPADES = "S"
    CLUBS = "C"


class Rank(Enum):
    TWO = "2"
    THREE = "3"
    FOUR = "4"
    FIVE = "5"
    SIX = "6"
    SEVEN = "7"
    EIGHT = "8"
    NINE = "9"
    TEN = "10"
    JACK = "J"
    QUEEN = "Q"
    KING = "K"
    ACE = "A"


class Card(NamedTuple):
    rank: Rank
    suit: Suit

    def __repr__(self):
        return f"{self.rank.value}{self.suit.value}"
