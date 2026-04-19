import datetime
import queue
import socket
import threading
from typing import NamedTuple


LOG_PORT = 8501


class LogLine(NamedTuple):
    pri: int
    version: int
    mac: str
    hostname: str
    app_name: str
    msg: str
    received_at: datetime.datetime


class LogParser:
    def __init__(self):
        self._buffer = ""
        self._initialized = False

    def parse_message(self, message: str) -> LogLine | None:
        if not message.startswith("<"):
            print("WARNING: Message did not start as expected: ", message)
            return None

        parts = message.split(" ", 7)
        if len(parts) != 8:
            print("WARNING: Message not understood: ", message)
            return None

        return LogLine(
            pri=int(parts[0][1:-3]),
            version=int(parts[0][-3]),
            mac=parts[2],
            hostname=parts[3],
            app_name=parts[4],
            msg=parts[7],
            received_at=datetime.datetime.now(),
        )


class LogListener:
    def __init__(self):
        self.lock = threading.Lock()
        self.crashed = None  # type: Exception | None
        self.queue = queue.Queue()
        self.running = True
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        threading.Thread(target=self.listen, daemon=True).start()

    def listen(self):
        try:
            self.server_socket.bind(("0.0.0.0", LOG_PORT))
        except socket.error as e:
            self.crashed = e
            raise e

        parser = LogParser()

        while self.running:
            message_bytes, address = self.server_socket.recvfrom(4096)
            message = parser.parse_message(message_bytes.decode())
            self.queue.put(message)

        self.server_socket.close()

    def get_next_line(self) -> LogLine:
        return self.queue.get()

    def stop(self):
        self.running = False
