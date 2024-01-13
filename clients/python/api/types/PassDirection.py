from enum import Enum
from typing import List

from clients.python.api.types.PlayerTagSession import PlayerTagSession


class PassDirection(Enum):
    LEFT = "Left"
    RIGHT = "Right"
    ACROSS = "Across"
    KEEPER = "Keeper"

    def _find_other(self, player_order: List[PlayerTagSession], this_player: PlayerTagSession):
        this_idx = player_order.index(this_player)
        if self == PassDirection.LEFT:
            return player_order[(this_idx - 1) % len(player_order)]
        elif self == PassDirection.RIGHT:
            return player_order[(this_idx + 1) % len(player_order)]
        elif self == PassDirection.ACROSS:
            return player_order[(this_idx + 2) % len(player_order)]
        elif self == PassDirection.KEEPER:
            return this_player
        else:
            raise ValueError(f"Unknown pass direction {self}")

    def _invert(self):
        if self == PassDirection.LEFT:
            return PassDirection.RIGHT
        elif self == PassDirection.RIGHT:
            return PassDirection.LEFT
        elif self == PassDirection.ACROSS:
            return PassDirection.ACROSS
        elif self == PassDirection.KEEPER:
            return PassDirection.KEEPER
        else:
            raise ValueError(f"Unknown pass direction {self}")

    def get_receiving_player(self, player_order: List[PlayerTagSession], this_player: PlayerTagSession):
        return self._find_other(player_order, this_player)

    def get_donating_player(self, player_order: List[PlayerTagSession], this_player: PlayerTagSession):
        return self._invert()._find_other(player_order, this_player)
