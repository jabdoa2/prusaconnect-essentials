import os
import sys
import time
from enum import Enum
from typing import Tuple

from prusa.connect.client import PrusaConnectClient
from prusa.connect.client.models import JobInfo, PrinterState

from handler.detect_print_sheet import DetectPrintSheet
from handler.timelapse_handler import TimelapseHandler
from handler.user_handler import (
    UserHandler,
    UserHandlerContext,
    UserHandlerResult,
    DebugUserHandler,
)
from lib.camera_handler import connect_camera, CameraHandler
from lib.gcode_handling import (
    convert_gcode_file_like_prusa_marlin,
    parse_gcode,
    group_gcode_lines_like_marlin,
)
from lib.logs import LogListener
from lib.metrics import MetricListener
from lib.prusa_connect import (
    get_camera_config,
    download_gcode_for_job_cached,
    GCodeFile,
    press_dialog_button,
)

INTERVAL_SECONDS_WAIT_FOR_JOB = 5


def wait_for_new_job(
    client: PrusaConnectClient, printer_id: str
) -> Tuple[JobInfo, GCodeFile]:
    print(f"Waiting for new job on printer {printer_id}")
    while True:
        printer = client.printers.get(printer_id)
        if (
            printer.state not in [PrinterState.STOPPED, PrinterState.FINISHED]
            and printer.job
            and printer.team_id
        ):
            gcode_file = download_gcode_for_job_cached(
                client, printer.job, printer.team_id
            )

            return printer.job, gcode_file

        time.sleep(INTERVAL_SECONDS_WAIT_FOR_JOB)


def get_user_handlers() -> dict[str, UserHandler]:
    user_handlers = {
        "check_build_plate": DetectPrintSheet(),
        "timelapse_snapshot": TimelapseHandler(),
        "test_call": DebugUserHandler(),
    }
    return user_handlers  # ty: ignore[invalid-return-type]


class HandlerStatus(Enum):
    INITIAL = 0
    WAIT_FOR_METRICS = 1
    RETRY_HANDLER = 2
    NEW_LINE = 3


def handle_job(
    client: PrusaConnectClient,
    printer_id: str,
    job: JobInfo,
    gcode_file: GCodeFile,
    camera_handler: CameraHandler,
    log_listener: LogListener,
    metric_listener: MetricListener,
):
    if job.display_name is None:
        print("ERROR: Job is missing a display_name. Will retry later.")
        return

    gcode_str = convert_gcode_file_like_prusa_marlin(gcode_file)
    print(f"Parsing {job.display_name} (type: {gcode_file.file_type})")
    gcode_lines = parse_gcode(gcode_str, gcode_file.file_type)
    gcode_blocks = group_gcode_lines_like_marlin(gcode_lines)

    user_handler_context = UserHandlerContext(
        base_path=os.path.dirname(os.path.realpath(__file__)),
        printer_id=printer_id,
        job_info=job,
        camera_handler=camera_handler,
        metric_listener=metric_listener,
    )
    user_handlers = get_user_handlers()
    current_status = HandlerStatus.INITIAL
    current_handler_result = None

    sdpos = metric_listener.get_value("sdpos", "v")
    is_printing = metric_listener.get_value("is_printing", "v")
    print_filename = metric_listener.get_value("print_filename", "v")
    # wait until we get an initial sdpos metric
    tries = 10
    while (
        not isinstance(sdpos, int) or is_printing is None or print_filename is None
    ) and tries > 0:
        print(
            "Did not yet get a metric for sdpos, is_printing, print_filename. Waiting 1s."
        )
        time.sleep(1)
        sdpos = metric_listener.get_value("sdpos", "v")
        is_printing = metric_listener.get_value("is_printing", "v")
        print_filename = metric_listener.get_value("print_filename", "v")
        tries -= 1

    if not isinstance(sdpos, int):
        print(
            "Did not get a sdpos within 10s. Please check metrics setup and IP. Will stop now."
        )
        return

    print(f"Starting at sdpos {sdpos}")

    gcode_block_index = 0
    # advance gcode pointer to the initial sdpos. Everything before that is ignored.
    while (
        gcode_block_index < len(gcode_blocks) - 1
        and sdpos >= gcode_blocks[gcode_block_index + 1].sdpos_start
    ):
        gcode_block_index += 1

    # make sure we process the current line so we move the index one back
    gcode_block_index -= 1

    while True:
        if current_status != HandlerStatus.WAIT_FOR_METRICS:
            # we got a user handler to retry. we want to run even if sdpos did not change
            sdpos = metric_listener.get_value("sdpos", "v")
        else:
            # TODO: use waiters here to improve latency further (for all three metrics)
            time.sleep(1)
            sdpos = metric_listener.get_value("sdpos", "v")

        is_printing = metric_listener.get_value("is_printing", "v")
        print_filename = metric_listener.get_value("print_filename", "v")

        if not isinstance(sdpos, int):
            print("ERROR: sdpos needs to be int. Will wait for a working metric.")
            continue
        if not isinstance(is_printing, bool):
            print(
                "ERROR: is_printing needs to be bool. Will wait for a working metric."
            )
            continue
        if not isinstance(print_filename, str):
            print(
                "ERROR: print_filename needs to be str. Will wait for a working metric."
            )
            continue

        if not is_printing:
            print(
                f"Printer is no longer printing (is_printing={is_printing}). We are done here."
            )
            return

        if (
            print_filename != job.display_name[0 : len(print_filename)]
            or not print_filename
        ):
            print(
                f"Printer is no longer printing our file {print_filename} != {job.display_name}. We are done here."
            )

        # process all lines till our current pos
        while (
            gcode_block_index < len(gcode_blocks) - 1
            and sdpos >= gcode_blocks[gcode_block_index + 1].sdpos_start
        ):
            # process instructions for lines which are comments only (not M0)
            gcode_block_index += 1
            current_handler_result = None
            current_block = gcode_blocks[gcode_block_index]
            print("Handling G-Code Line (async):", current_block)
            for async_line in current_block.async_method_call_lines:
                if async_line.handler_name in user_handlers:
                    print(
                        f"Running user handler {async_line.handler_name} ({async_line.handler_params})"
                    )
                    result = user_handlers[async_line.handler_name].call(
                        user_handler_context, **async_line.handler_params
                    )
                    print(f"User handler returned {result}")
                    if result != UserHandlerResult.SUCCESS:
                        print(
                            "WARNING: Will not retry the handler (as the printer is not paused)"
                        )
                else:
                    print(
                        f"ERROR: Invalid handler {async_line.handler_name}. Will ignore it."
                    )

        current_block = gcode_blocks[gcode_block_index]
        print("Processing G-Code Line (2):", current_block)

        # handle commands after an M0
        if current_block.sync_method_call_line:
            # only run handler until it succeeded
            if current_handler_result in (
                None,
                UserHandlerResult.RETRY,
                UserHandlerResult.FAILED,
            ):
                # check if the printer is paused with a dialog in PrusaConnect
                printer = client.printers.get(printer_id)
                dialog_info = getattr(printer, "dialog_info", None)
                if printer.state != PrinterState.PAUSED:
                    print(
                        "Printer is not paused (yet) according to PrusaConnect. Will retry in 1s."
                    )
                    current_status = HandlerStatus.RETRY_HANDLER
                    time.sleep(1)
                elif not dialog_info:
                    print(
                        "Printer is not showing a dialog according to PrusaConnect. Will retry in 1s."
                    )
                    current_status = HandlerStatus.RETRY_HANDLER
                    time.sleep(1)
                elif (
                    dialog_info["key"] != "QUICK_PAUSE"
                    or "Resume" not in dialog_info["buttons"]
                ):
                    print(
                        f"WARNING: Dialog does not match our expections: {dialog_info}. Will retry in 5s"
                    )
                    current_status = HandlerStatus.RETRY_HANDLER
                    time.sleep(5)
                else:
                    handler_name = current_block.sync_method_call_line.handler_name
                    handler_kwargs = current_block.sync_method_call_line.handler_params
                    if handler_name in user_handlers:
                        print(f"Running user handler {handler_name} ({handler_kwargs})")
                        current_handler_result = user_handlers[handler_name].call(
                            user_handler_context, **handler_kwargs
                        )
                        print(f"User handler returned {current_handler_result}")
                        if current_handler_result in (
                            UserHandlerResult.RETRY,
                            UserHandlerResult.FAILED,
                        ):
                            current_status = HandlerStatus.RETRY_HANDLER
                            print("Will retry handler in 1s.")
                            time.sleep(1)
                        elif current_handler_result == UserHandlerResult.SUCCESS:
                            current_status = HandlerStatus.WAIT_FOR_METRICS
                            print("Will continue the print via PrusaConnect.")
                            press_dialog_button(
                                client, printer_id, int(dialog_info["id"]), "Resume"
                            )
                    else:
                        current_status = HandlerStatus.WAIT_FOR_METRICS
                        current_handler_result = UserHandlerResult.CONFIG_INVALID
                        print(f"ERROR: Invalid handler {handler_name}. Will ignore it.")
        else:
            current_status = HandlerStatus.WAIT_FOR_METRICS

        if gcode_block_index >= len(gcode_blocks) - 1:
            print("Reached end of gcode according to sdpos. We are done here.")
            return


def main(printer_id):
    import logging

    logging.basicConfig(level=logging.DEBUG)

    client = PrusaConnectClient()

    camera = get_camera_config(client, printer_id)
    if not camera:
        raise AssertionError(f"No camera found for your printer {printer_id}")
    while True:
        job, gcode = wait_for_new_job(client, printer_id)
        print(f"Handle new job {job.id}")
        metric_listener = MetricListener()
        log_listener = LogListener()
        camera_handler = connect_camera(client, camera)
        handle_job(
            client,
            printer_id,
            job,
            gcode,
            camera_handler,
            log_listener,
            metric_listener,
        )
        metric_listener.stop()
        log_listener.stop()
        camera_handler.stop()


if __name__ == "__main__":
    main(sys.argv[1])
