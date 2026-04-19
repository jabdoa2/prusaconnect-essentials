from abc import abstractmethod, ABC

from prusa.connect.client import PrusaConnectClient
from prusa.connect.client.models import Camera

from lib.direct_camera import RTSPStream, RTSPConnectError
from lib.prusa_connect import download_prusa_connect_frame


class CameraHandler(ABC):
    @abstractmethod
    def capture(self, max_age_seconds: int):
        pass

    def stop(self):
        pass


class RTSPCameraHandler(CameraHandler):
    def __init__(self, rtsp_stream: RTSPStream):
        self.rtsp_stream = rtsp_stream

    def capture(self, max_age_seconds: int):
        frame, ts = self.rtsp_stream.get_latest()

        return frame

    def stop(self):
        self.rtsp_stream.stop()


class PrusaConnectCameraHandler(CameraHandler):
    def __init__(self, client: PrusaConnectClient, camera: Camera):
        self.client = client
        self.camera = camera

    def capture(self, max_age_seconds: int):
        download_prusa_connect_frame(self.client, self.camera, max_age_seconds)


def connect_camera(client: PrusaConnectClient, camera: Camera) -> CameraHandler:
    try:
        rtsp_handler = RTSPStream(camera)
        return RTSPCameraHandler(rtsp_handler)
    except RTSPConnectError as e:
        print(f"Failed to connect to RTSP: {e}. Will fallback to using PrusaConnect.")
        return PrusaConnectCameraHandler(client, camera)
