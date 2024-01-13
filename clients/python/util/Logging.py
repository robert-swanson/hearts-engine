import json
import threading
from datetime import datetime
from pathlib import Path

from clients.python.api.types.PlayerTagSession import PlayerTag
from clients.python.util.Constants import Tags, CLIENT_LOG_DIRNAME, SESSION_LOG_DIRNAME, CONNECTION_LOG_DIRNAME
from clients.python.util.Env import LOG_DIR


class Logger:
    def __init__(self, log_path: Path):
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_file = open(log_path, "w")
        self.logging_lock = threading.Lock()

    def log(self, log_msg: str, also_print=False):
        with self.logging_lock:
            self.log_file.write(log_msg + "\n")
            self.log_file.flush()
            if also_print:
                print(log_msg)


class MessageLogger(Logger):
    def log_message(self, prefix: str, msg: json, verbose=False, also_print=False):
        if self.should_log_message(msg):
            print_str = f"{prefix:20}{msg[Tags.SESSION_ID]}.{msg[Tags.SEQ_NUM]}\t {msg[Tags.TYPE]:20}"
            if verbose:
                print_str +=  f"\t\t\t{msg}"
            self.log(print_str, also_print)

    @staticmethod
    def should_log_message(json_data: json) -> bool:
        if Tags.SESSION_ID not in json_data:
            return False
        return True


class SessionLogger(MessageLogger):
    def __init__(self, player_tag: PlayerTag, session_id: int):
        log_path = (LOG_DIR / CLIENT_LOG_DIRNAME / SESSION_LOG_DIRNAME / str(player_tag) /
                    datetime.now().strftime("%Y-%m-%d") / datetime.now().strftime("%H:%M") / f"{session_id}_message.log")
        super().__init__(log_path)


class ConnectionLogger(MessageLogger):
    def __init__(self):
        log_path = (LOG_DIR / CLIENT_LOG_DIRNAME / CONNECTION_LOG_DIRNAME / datetime.now().strftime("%Y-%m-%d") /
                    f"{datetime.now().strftime('%H:%M:%S')}_connection.log")
        super().__init__(log_path)
