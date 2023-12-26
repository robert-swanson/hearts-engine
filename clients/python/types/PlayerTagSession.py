import re
from typing import NamedTuple, List


class PlayerTag:
    def __init__(self, tag: str):
        self.tag = tag

    def __repr__(self):
        return f"{self.tag}"

    def __str__(self):
        return self.tag

    def __eq__(self, other):
        return self.tag == other.tag

    def __hash__(self):
        return hash(self.tag)


class PlayerTagSession:
    def __init__(self, player_tag: PlayerTag, session_id: int):
        self.player_tag = player_tag
        self.session_id = session_id

    def __eq__(self, other):
        if not isinstance(other, PlayerTagSession):
            return False
        return self.player_tag == other.player_tag and self.session_id == other.session_id

    def __repr__(self):
        return f"{self.player_tag}({self.session_id}))"

    def __hash__(self):
        return hash((self.player_tag, self.session_id))


PLAYER_TAG_PATTERN = re.compile(r"(.*)\((.*)\)")


def MakePlayerTagSession(string: str) -> PlayerTagSession:
    match = re.match(PLAYER_TAG_PATTERN, string)
    assert match is not None, f"Could not parse player tag {string}"
    return PlayerTagSession(PlayerTag(match.group(1)), int(match.group(2)))


def MakePlayerTagSessions(str_list: List[str]) -> List[PlayerTagSession]:
    return [MakePlayerTagSession(s) for s in str_list]
