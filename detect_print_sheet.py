from prusa.connect.client import PrusaConnectClient
from prusa.connect.client.models import PrinterState, JobInfo
import cv2
import numpy as np
import sys
import time
import pybgcode
import tempfile
import os
import datetime
import email.utils
from typing import Tuple
from pybgcode import EResult

from lib.tag_detection import identify_sheet_id

INTERVAL_SECONDS_WAIT_FOR_JOB = 10
MAX_AXIS_Z_FOR_NEW_JOB = 10

INTERVAL_WAIT_FOR_JOB_START = 5
DETECTION_Z = 100

USE_RTSP = True


def convert_bgcode(file_in, file_out):
    in_f = pybgcode.open(file_in, "rb")
    out_f = pybgcode.open(file_out, "w")

    assert in_f
    assert out_f

    assert pybgcode.is_open(in_f)
    assert pybgcode.is_open(out_f)

    res = pybgcode.from_binary_to_ascii(in_f, out_f, True)
    assert res == EResult.Success


def download_rtsp_frame(camera: dict) -> cv2.typing.MatLike | None:
    if not USE_RTSP:
        return None

    wifi_ip = camera.get("config", {}).get("network_info", {}).get("wifi_ipv4")
    if not wifi_ip:
        print("Could not get wifi ip of camera.")
        return None

    rtsp_url = f"rtsp://{wifi_ip}/live"
    print(f"Will get Frame from {rtsp_url}")
    cap = cv2.VideoCapture(rtsp_url)
    ret, frame = cap.read()
    if not ret:
        print("Failed to get RTSP frame")
        return None
    cap.release()
    return frame


def download_prusa_connect_frame(
    client: PrusaConnectClient, camera: dict
) -> cv2.typing.MatLike | None:
    print("Downloading snapshot from PrusaConnect")
    # use raw call to get image age as well
    response = client.api_request(
        "GET", f"/app/cameras/{camera['id']}/snapshots/last", raw=True
    )
    image_data = response.content
    image_taken = email.utils.parsedate_to_datetime(response.headers["last-modified"])
    image_age = (
        datetime.datetime.now(datetime.timezone(datetime.timedelta(seconds=0)))
        - image_taken
    )
    if image_age > datetime.timedelta(seconds=30):
        print(
            f"Snapshot is too old ({image_age}). Make sure your camera is working properly."
        )
        return None
    if False:
        with open("snapshot.jpg", "wb") as f:
            f.write(image_data)

    nparr = np.frombuffer(image_data, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    return img


def parse_allowed_build_plate_values(gcode_str) -> list[int]:
    search_string = "; allowed_build_plates="

    allowed_build_plate_lines = [
        line for line in gcode_str.split("\n") if line.startswith(search_string)
    ]
    if not allowed_build_plate_lines:
        print(
            "WARNING: Did not find any allowed_build_plates lines in gcode. Will assume nothing is allowed."
        )
        return []

    if len(allowed_build_plate_lines) > 1:
        print(
            "WARNING: Found more than one allowed_build_plates lines. Will use first line."
        )

    allowed_build_plate_str_values = allowed_build_plate_lines[0][
        len(search_string) :
    ].split(",")
    try:
        allowed_build_plate_values = [
            int(value) for value in allowed_build_plate_str_values
        ]
    except ValueError:
        print(
            f"Failed to parse allowed_build_plates values to int: {allowed_build_plate_str_values}"
        )
        return []

    return allowed_build_plate_values


def wait_for_new_job(
    client: PrusaConnectClient, printer_id: str
) -> Tuple[list[int], JobInfo]:
    print(f"Waiting for new job on printer {printer_id}")
    while True:
        printer = client.printers.get(printer_id)
        if (
            printer.job
            and printer.job.hash
            and printer.team_id
            and printer.axis_z is not None
            and (
                (
                    printer.axis_z <= MAX_AXIS_Z_FOR_NEW_JOB
                    and printer.state == PrinterState.PRINTING
                )
                or (
                    printer.axis_z == DETECTION_Z
                    and printer.state == PrinterState.PAUSED
                )
            )
        ):
            print(f"Downloading {printer.job.display_name}")
            bgcode_bytes = client.download_team_file(printer.team_id, printer.job.hash)

            if printer.job.display_name and printer.job.display_name.lower().endswith(
                ".bgcode"
            ):
                with tempfile.TemporaryDirectory() as tmpdirname:
                    with open(os.path.join(tmpdirname, "job.bgcode"), "wb") as f:
                        f.write(bgcode_bytes)

                    convert_bgcode(
                        os.path.join(tmpdirname, "job.bgcode"),
                        os.path.join(tmpdirname, "job.gcode"),
                    )

                    with open(os.path.join(tmpdirname, "job.gcode"), "r") as f:
                        gcode = f.read()
            else:
                gcode = bgcode_bytes.decode()

            return parse_allowed_build_plate_values(gcode), printer.job

        time.sleep(INTERVAL_SECONDS_WAIT_FOR_JOB)


def handle_job(
    client: PrusaConnectClient,
    printer_id: str,
    camera: dict,
    allowed_sheets: list[int],
    job_id: int,
) -> bool:
    while True:
        time.sleep(5)
        printer = client.printers.get(printer_id)
        if (
            not printer.job
            or printer.job.id != job_id
            or printer.state in (PrinterState.FINISHED, PrinterState.STOPPED)
        ):
            print("Printer is no longer printing our job. We are done here.")
            return False

        if printer.axis_z is not None and printer.axis_z > max(
            DETECTION_Z, MAX_AXIS_Z_FOR_NEW_JOB
        ):
            print("Job is past our detection Z.")
            return False

        if printer.state != PrinterState.PAUSED:
            print(f"Printer is {printer.state} != PAUSED. Skipping!")
            continue

        if printer.axis_z != DETECTION_Z:
            print(f"Z axis is not at {printer.axis_z} != {DETECTION_Z}. Skipping!")
            continue

        dialog_info = getattr(printer, "dialog_info", None)
        if not dialog_info:
            print("No dialog open. Skipping!")
            continue

        if (
            dialog_info["key"] != "QUICK_PAUSE"
            or "Resume" not in dialog_info["buttons"]
        ):
            print(f"Wrong dialog open: {dialog_info}. Skipping!")
            continue

        print("Found dialog")
        dialog_id = int(dialog_info["id"])
        button_action = "Resume"

        img = download_rtsp_frame(camera)
        if img is None:
            img = download_prusa_connect_frame(client, camera)

        if img is None:
            print("Could not load image. Will retry!")
            continue

        tag_id = identify_sheet_id(img)
        if tag_id in allowed_sheets:
            print(
                f"Correct sheet for for material found (ID: {tag_id}. Resuming print!"
            )
            params = {"command": "DIALOG_ACTION", "kwargs": {
                "button": button_action,
                "dialog_id": dialog_id,
            }}
            print(f"/app/printers/{printer_id}/commands/sync")
            print(params)
            client.api_request(
                "POST", f"/app/printers/{printer_id}/commands/sync", json=params
            )
            time.sleep(30)
            return True
        else:
            print("Wrong plate for material. Not continuing print.")
            return False


def main(printer_id: str):
    # Credentials are automatically loaded from your environment or default local file
    client = PrusaConnectClient()

    # find camera
    cameras = client.api_request("GET", f"/app/printers/{printer_id}/cameras")

    if not cameras["cameras"]:
        raise AssertionError(
            "Could not find any cameras for your printer. Please add one!"
        )

    camera = cameras["cameras"][0]
    print(
        f"Will use camera your first camera {cameras['cameras'][0]['name']} with id: {camera['id']}."
    )

    while True:
        allowed_sheets, job_info = wait_for_new_job(client, printer_id)
        print(
            f"Found new job {job_info.display_name} (ID {job_info.id}) on printer. Allowed sheets are: {allowed_sheets}"
        )
        assert job_info.id is not None
        handle_job(client, printer_id, camera, allowed_sheets, job_info.id)


if __name__ == "__main__":
    main(sys.argv[1])
