class PlayerTag:
    def __init__(self, tag: str):
        self.tag = tag

    def __repr__(self):
        return f"Player({self.tag})"

    def __str__(self):
        return self.tag
