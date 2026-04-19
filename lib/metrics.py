import re
import socket
import threading
from collections import defaultdict
from typing import NamedTuple

METRIC_PORT = 8500


class MetricMessage(NamedTuple):
    name: str
    values: dict[str, str | int | float | bool]


def parse_kv_string(s: str) -> dict:
    i = 0
    n = len(s)
    result = {}

    def skip_ws():
        nonlocal i
        while i < n and s[i].isspace():
            i += 1

    def parse_key():
        nonlocal i
        start = i
        while i < n and s[i] not in "=\t\n\r ,":
            i += 1
        if start == i:
            raise ValueError(f"Expected key at position {i}")
        return s[start:i]

    def parse_quoted():
        nonlocal i
        assert s[i] == '"'
        i += 1  # skip opening quote
        chars = []

        while i < n:
            c = s[i]
            if c == "\\":
                i += 1
                if i >= n:
                    raise ValueError("Unterminated escape")
                chars.append(s[i])
            elif c == '"':
                i += 1
                return "".join(chars)
            else:
                chars.append(c)
            i += 1

        raise ValueError("Unterminated quoted string")

    def parse_bare():
        nonlocal i
        start = i
        while i < n and s[i] != ",":
            i += 1
        return s[start:i].strip()

    def parse_value():
        nonlocal i
        if i < n and s[i] == '"':
            return parse_quoted(), True
        else:
            raw = parse_bare()
            return raw, False

    skip_ws()

    while i < n:
        # parse key
        key = parse_key()

        skip_ws()
        if i >= n or s[i] != "=":
            raise ValueError(f"Expected '=' after key '{key}'")
        i += 1

        skip_ws()

        # parse value
        value, was_quoted = parse_value()

        if not was_quoted:
            if value in ["t", "T", "true", "True", "TRUE"]:
                value = True
            elif value in ["f", "F", "false", "False", "FALSE"]:
                value = False
            elif value.endswith("i"):
                value = int(value[:-1])
            else:
                value = float(value)
        result[key] = value

        skip_ws()

        if i < n:
            if s[i] == ",":
                i += 1
                skip_ws()
            else:
                raise ValueError(f"Expected ',' at position {i}")

    return result


class MetricsParser:
    def __init__(self):
        self._buffer = ""
        self._initialized = False

    def parse_message(self, message: str) -> list[MetricMessage]:
        results = []
        if not message.startswith("<"):
            print("WARNING: Message did not start as expected: ", message)
            return []
        if not message.endswith("\n"):
            print("WARNING: Message did not end as expected: ", message)
            return []

        parts = message[:-1].split("\n")
        messages_raw = parts[1:]

        for message_str in messages_raw:
            match = re.match(r"^(?P<name>[^ ]+) (?P<values>.*) -?\d+$", message_str)
            if not match:
                print("WARNING: Values not understood:", message, message_str)
                continue

            value_dict = parse_kv_string(match["values"])
            results.append(MetricMessage(name=match["name"], values=value_dict))
        return results


class MetricListener:
    def __init__(self):
        self.lock = threading.Lock()
        self.crashed = None  # type: Exception | None
        self.subscription_event = threading.Event()
        self.subscription_metric_name = None  # type: str | None
        self.subscription_metric_key = None  # type: str | None
        self.running = True
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.current_value = defaultdict(dict)  # type: dict[str, dict[str, int | str | float | bool]]
        threading.Thread(target=self.listen, daemon=True).start()

    def listen(self):
        try:
            self.server_socket.bind(("0.0.0.0", METRIC_PORT))
        except socket.error as e:
            self.crashed = e
            raise e

        parser = MetricsParser()

        while self.running:
            message_bytes, address = self.server_socket.recvfrom(4096)
            messages = parser.parse_message(message_bytes.decode())
            for message in messages:
                for key, value in message.values.items():
                    self.current_value[message.name][key] = value
                    if (
                        message.name == self.subscription_metric_name
                        and self.subscription_metric_key == key
                    ):
                        # to prevent races check again after locking
                        with self.lock:
                            if (
                                message.name == self.subscription_metric_name
                                and self.subscription_metric_key == key
                            ):
                                self.subscription_event.set()
        self.server_socket.close()

    def get_value(
        self, metric_name: str, value_key: str
    ) -> int | str | float | bool | None:
        if self.crashed:
            raise self.crashed
        return self.current_value[metric_name].get(value_key)

    def wait_for_update(
        self, metric_name: str, value_key: str, old_value: int | str | float | bool
    ) -> int | str | float | bool:
        if self.crashed:
            raise self.crashed

        current_value = self.current_value[metric_name].get(value_key)
        if old_value != current_value:
            return current_value

        self.subscribe(metric_name, value_key)
        while True:
            self.subscription_event.wait()
            self.subscription_event.clear()
            current_value = self.current_value[metric_name].get(value_key)
            if old_value != current_value:
                self.unsubscribe(metric_name, value_key)
                return current_value

    def subscribe(
        self,
        metric_name: str,
        value_key: str,
    ):
        with self.lock:
            self.subscription_event.clear()
            self.subscription_metric_name = metric_name
            self.subscription_metric_key = value_key

    def unsubscribe(
        self,
        metric_name: str,
        value_key: str,
    ):
        with self.lock:
            self.subscription_event.clear()
            self.subscription_metric_name = None
            self.subscription_metric_key = None

    def stop(self):
        self.running = False
        self.server_socket.close()
