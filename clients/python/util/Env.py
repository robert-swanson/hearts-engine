from pathlib import Path
import os
import sys

class EnvReader:
    def __init__(self, env_file_path: str):
        self.env_file_path = env_file_path
        self.env_dict = {}
        self.read_env_file()

    def read_env_file(self):
        with open(self.env_file_path, "r") as f:
            for line in f.readlines():
                line = line.strip()
                if line.startswith("#") or len(line) == 0:
                    continue
                key, value = line.split("=")
                self.env_dict[key] = value

    def get(self, key: str) -> str:
        assert key in self.env_dict, f"Key {key} not found in env file {self.env_file_path}"
        return self.env_dict[key]


def _resolve_env_filepath() -> str:
    """Locate the config .env file.

    Priority:
      1. HEARTS_CONFIG_ENV environment variable — lets the SDK be imported
         in-process by hosts that own argv (e.g. uvicorn, where sys.argv[1]
         is the ASGI app target like "main:app", not a config file).
      2. sys.argv[1], but only if it points at an existing file (preserves the
         long-standing `python player.py path/to/config.env` invocation).
      3. ./config.env fallback.
    """
    override = os.environ.get("HEARTS_CONFIG_ENV")
    if override:
        return override
    if len(sys.argv) > 1 and os.path.isfile(sys.argv[1]):
        return sys.argv[1]
    return "./config.env"


ENV_FILEPATH = _resolve_env_filepath()
ENV = EnvReader(ENV_FILEPATH)

SERVER_IP = ENV.get("SERVER_ADDR")
# Ports default to the documented standard ports when the env file doesn't set
# them: the generated tournament_server.env no longer carries ports (issue #99
# — config.env is their single home), but it is still a valid env file for
# clients that read it for SERVER_ADDR / credentials.
SERVER_PORT = int(ENV.env_dict.get("SERVER_PORT", 40405))
TOURNAMENT_PORT = int(ENV.env_dict.get("TOURNAMENT_PORT",
                                       ENV.env_dict.get("SERVER_PORT", 40406)))
LOG_DIR = Path(ENV.env_dict.get("LOG_DIR", "./log"))
