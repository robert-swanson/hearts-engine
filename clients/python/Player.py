class Player:
    def __init__(self, player_tag: str):
        self.player_tag = player_tag

    def __repr__(self):
        return f"Player({self.player_tag})"

    def __str__(self):
        return self.player_tag
