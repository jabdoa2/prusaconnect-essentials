from abc import abstractmethod, ABC
from enum import Enum
from typing import NamedTuple

from prusa.connect.client.models import JobInfo

from lib.camera_handler import CameraHandler
from lib.metrics import MetricListener


class UserHandlerResult(Enum):
    SUCCESS = 0
    FAILED = 1
    RETRY = 2
    CONFIG_INVALID = 3


class UserHandlerContext(NamedTuple):
    base_path: str
    printer_id: str
    job_info: JobInfo
    camera_handler: CameraHandler
    metric_listener: MetricListener


class UserHandler(ABC):
    @abstractmethod
    def call(self, context: UserHandlerContext, *args, **kwargs) -> UserHandlerResult:
        pass


class DebugUserHandler(UserHandler):
    def call(self, context: UserHandlerContext, *args, **kwargs) -> UserHandlerResult:
        print(f"DEBUG USER HANDLER GOT CALLED WITH: {args} {kwargs}")
        return UserHandlerResult.SUCCESS
