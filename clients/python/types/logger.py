import json
import threading

from clients.python.types.Constants import Tags

logging_lock = threading.Lock()


def log(message):
    with logging_lock:
        print(message)


def should_log_message(json_data: json) -> bool:
    if Tags.SESSION_ID not in json_data:
        return False
    return True


def log_message(prefix: str, msg: json, verbose=False):
    if should_log_message(msg) and False:
        if verbose:
            log(f"{prefix:15}{msg[Tags.SESSION_ID]}.{msg[Tags.SEQ_NUM]}\t {msg[Tags.TYPE]:20}\t\t\t{msg}")
        else:
            log(f"{prefix:15}{msg[Tags.SESSION_ID]}.{msg[Tags.SEQ_NUM]}")
