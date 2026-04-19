import threading
import time

import cv2
from prusa.connect.client.models import Camera


class RTSPConnectError(AssertionError):
    pass


def get_url_for_camera(camera: Camera) -> str | None:
    assert camera.config is not None
    if not camera.config.network_info:
        print("Missing network_info for camera")
        return None

    if not camera.config.network_info.wifi_ipv4:
        print("Could not get wifi ip of camera.")
        return None

    rtsp_url = f"rtsp://{camera.config.network_info.wifi_ipv4}/live"
    return rtsp_url


def download_rtsp_frame(camera: Camera) -> cv2.typing.MatLike | None:
    rtsp_url = get_url_for_camera(camera)
    if not rtsp_url:
        raise RTSPConnectError("Could not get RTSP url")
    print(f"Will get Frame from {rtsp_url}")
    cap = cv2.VideoCapture(rtsp_url)
    ret, frame = cap.read()
    if not ret:
        print("Failed to get RTSP frame")
        return None
    cap.release()
    return frame


class RTSPStream:
    def __init__(self, camera: Camera):
        self.frame = None
        self.timestamp = None
        self.lock = threading.Lock()
        self.running = True
        rtsp_url = get_url_for_camera(camera)
        if not rtsp_url:
            raise RTSPConnectError("Could not get RTSP url")
        self.cap = cv2.VideoCapture(rtsp_url)
        if not self.cap.isOpened():
            raise RTSPConnectError("Could not open RTSP stream")
        threading.Thread(target=self.update, daemon=True).start()

    def update(self):
        while self.running:
            ret, frame = self.cap.read()
            if ret:
                with self.lock:
                    self.frame = frame
                    self.timestamp = time.time()

    def get_latest(self):
        while True:
            with self.lock:
                if self.frame is not None:
                    return self.frame, self.timestamp

    def stop(self):
        self.running = False
        self.cap.release()
