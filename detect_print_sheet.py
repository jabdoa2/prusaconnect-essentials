from prusa.connect.client import PrusaConnectClient
from prusa.connect.client.models import PrinterState, JobInfo, Camera
import sys
import time
from typing import Tuple

from lib.direct_camera import download_rtsp_frame
from lib.gcode_handling import parse_allowed_build_plate_values, convert_bgcode_to_gcode
from lib.prusa_connect import (
    get_camera_config,
    download_prusa_connect_frame,
    press_dialog_button,
)
from lib.tag_detection import identify_sheet_id

INTERVAL_SECONDS_WAIT_FOR_JOB = 10
MAX_AXIS_Z_FOR_NEW_JOB = 10

INTERVAL_WAIT_FOR_JOB_START = 5
DETECTION_Z = 100

USE_RTSP = True


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
                gcode = convert_bgcode_to_gcode(bgcode_bytes)
            else:
                gcode = bgcode_bytes.decode()

            return parse_allowed_build_plate_values(gcode), printer.job

        time.sleep(INTERVAL_SECONDS_WAIT_FOR_JOB)


def handle_job(
    client: PrusaConnectClient,
    printer_id: str,
    camera: Camera,
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

        if USE_RTSP:
            img = download_rtsp_frame(camera)
        else:
            img = None
        if img is None:
            img = download_prusa_connect_frame(client, camera, 30)

        if img is None:
            print("Could not load image. Will retry!")
            continue

        tag_id = identify_sheet_id(img)
        if tag_id in allowed_sheets:
            print(
                f"Correct sheet for for material found (ID: {tag_id}). Resuming print!"
            )
            press_dialog_button(client, printer_id, dialog_id, button_action)
            time.sleep(30)
            return True
        else:
            print("Wrong plate for material. Not continuing print.")
            return False
    return False


def main(printer_id: str):
    # Credentials are automatically loaded from your environment or default local file
    client = PrusaConnectClient()

    camera = get_camera_config(client, printer_id)
    if not camera:
        raise AssertionError(
            "Could not find any cameras for your printer. Please add one!"
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
