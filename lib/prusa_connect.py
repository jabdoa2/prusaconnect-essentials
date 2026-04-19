import datetime
import email.utils
import os
from enum import Enum
from typing import NamedTuple

from platformdirs import user_cache_dir

import cv2
import numpy as np
from prusa.connect.client import PrusaConnectClient
from prusa.connect.client.models import Camera, JobInfo


class GCodeFileType(Enum):
    PlainGCode = "PLAIN_GCODE"
    BGCode = "BGCODE"


class GCodeFile(NamedTuple):
    display_name: str
    file_type: GCodeFileType
    content_raw: bytes


def download_gcode_for_job_cached(
    client: PrusaConnectClient, job: JobInfo, team_id: int
) -> GCodeFile:
    cachedir = user_cache_dir("prusa_connect_essentials", "jabdoa", ensure_exists=True)

    assert job.id is not None
    assert job.hash is not None

    try:
        os.mkdir(os.path.join(cachedir, "gcode"))
    except FileExistsError:
        pass

    file_name = os.path.join(cachedir, "gcode", f"{team_id}-{job.id}-{job.hash}.cache")

    if job.display_name is None:
        raise AssertionError(f"Job has no display name: {job}")

    if job.display_name.lower().endswith(".bgcode"):
        gcode_type = GCodeFileType.BGCode
    else:
        gcode_type = GCodeFileType.PlainGCode

    # check cache
    if os.path.exists(file_name):
        print(f"Returning cached gcode for job {job.display_name}")
        with open(file_name, "rb") as f:
            content_raw = f.read()
    else:
        print(f"Downloading {job.display_name}")
        content_raw = client.download_team_file(team_id, job.hash)

    # store file to cache
    with open(file_name, "wb") as f:
        f.write(content_raw)

    return GCodeFile(
        display_name=job.display_name, file_type=gcode_type, content_raw=content_raw
    )


def get_camera_config(client: PrusaConnectClient, printer_id: str) -> Camera | None:
    # find camera
    cameras = client.api_request("GET", f"/app/printers/{printer_id}/cameras")

    if not cameras["cameras"]:
        return None

    camera = Camera.model_validate(cameras["cameras"][0])
    print(camera)
    print(cameras["cameras"][0])
    print(f"Will use camera your first camera {camera.name} with id: {camera.id}.")
    return camera


def download_prusa_connect_frame(
    client: PrusaConnectClient, camera: Camera, max_age_seconds: int
) -> cv2.typing.MatLike | None:
    print("Downloading snapshot from PrusaConnect")
    # use raw call to get image age as well
    response = client.api_request(
        "GET", f"/app/cameras/{camera.id}/snapshots/last", raw=True
    )
    image_data = response.content
    image_taken = email.utils.parsedate_to_datetime(response.headers["last-modified"])
    image_age = (
        datetime.datetime.now(datetime.timezone(datetime.timedelta(seconds=0)))
        - image_taken
    )
    if image_age > datetime.timedelta(seconds=max_age_seconds):
        print(
            f"Snapshot is too old ({image_age}). Make sure your camera is working properly."
        )
        return None
    if False:
        with open("snapshot.jpg", "wb") as f:
            f.write(image_data)

    numpy_buffer = np.frombuffer(image_data, np.uint8)
    img = cv2.imdecode(numpy_buffer, cv2.IMREAD_COLOR)
    return img


def press_dialog_button(
    client: PrusaConnectClient, printer_id: str, dialog_id: int, button_action: str
):
    params = {
        "command": "DIALOG_ACTION",
        "kwargs": {
            "button": button_action,
            "dialog_id": dialog_id,
        },
    }
    print(f"/app/printers/{printer_id}/commands/sync")
    print(params)
    client.api_request("POST", f"/app/printers/{printer_id}/commands/sync", json=params)
