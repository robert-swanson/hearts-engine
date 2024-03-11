from pathlib import Path
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


ENV_FILEPATH = sys.argv[1] if len(sys.argv) > 1 else "./config.env"
ENV = EnvReader(ENV_FILEPATH)

SERVER_IP = ENV.get("SERVER_ADDR")
SERVER_PORT = int(ENV.get("SERVER_PORT"))
LOG_DIR = Path(ENV.get("LOG_DIR"))
