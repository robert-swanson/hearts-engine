import importlib
import sys
from pathlib import Path
from typing import Dict, Optional, Type

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from clients.python.api.Player import Player
from clients.python.TableGameFlow import TableGame


def _discover_strategies() -> Dict[str, Type[Player]]:
    """Scan the players directory and return {keyword: PlayerClass} for all importable players."""
    strategies: Dict[str, Type[Player]] = {}
    players_dir = Path(__file__).parents[2] / 'players'
    skip = {'debugger_player.py', '__init__.py'}

    for f in sorted(players_dir.glob('*.py')):
        if f.name in skip:
            continue
        module_name = f'clients.python.players.{f.stem}'
        try:
            mod = importlib.import_module(module_name)
        except Exception as e:
            print(f"  (skipping {f.name}: {e})")
            continue

        for obj in vars(mod).values():
            if (isinstance(obj, type) and issubclass(obj, Player)
                    and obj is not Player
                    and getattr(obj, 'player_tag', None)):
                tag: str = obj.player_tag
                if tag not in strategies:
                    strategies[tag] = obj
                    # Also register a short alias: drop trailing _player
                    short = tag[:-len('_player')] if tag.endswith('_player') else tag
                    if short not in strategies:
                        strategies[short] = obj

    return strategies


def _setup_players(strategies: Dict[str, Type[Player]]):
    print("\nAvailable AI strategies:")
    seen = set()
    for key, cls in strategies.items():
        if cls not in seen:
            tag = cls.player_tag
            short = tag[:-len('_player')] if tag.endswith('_player') else tag
            print(f"  {short:<20} ({cls.__name__})")
            seen.add(cls)

    print("\nFor each seat enter a player name (human) or a strategy keyword (AI).")
    print("Human names can be anything that doesn't match a strategy keyword.\n")

    player_configs = []
    used_tags = set()

    for seat in range(1, 5):
        while True:
            entry = input(f"Seat {seat}: ").strip()
            if not entry:
                print("  Name cannot be empty.")
                continue

            cls: Optional[Type[Player]] = strategies.get(entry) or strategies.get(entry.lower())
            if cls is not None:
                tag = cls.player_tag
                if tag in used_tags:
                    # Disambiguate duplicate strategy by appending seat number
                    tag = f"{tag}_{seat}"
                used_tags.add(tag)
                player_configs.append((tag, cls))
                print(f"  → AI: {cls.__name__} (tag: {tag})")
            else:
                if entry in used_tags:
                    print(f"  Name '{entry}' is already taken, choose another.")
                    continue
                used_tags.add(entry)
                player_configs.append((entry, None))
                print(f"  → Human: {entry}")
            break

    return player_configs


if __name__ == '__main__':
    strategies = _discover_strategies()
    player_configs = _setup_players(strategies)
    print()
    TableGame(player_configs).run_game()
