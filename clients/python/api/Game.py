from typing import List, Optional

from clients.python.api.Round import Round
from clients.python.api.types.PlayerTagSession import PlayerTagSession


class Game:
    def __init__(self, player_order: List[PlayerTagSession]):
        self.player_order = player_order
        self.rounds: List[Round] = []
        self.winner: Optional[PlayerTagSession] = None


