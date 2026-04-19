import os
import cv2

from handler.user_handler import UserHandler, UserHandlerContext, UserHandlerResult


def ensure_timelapse_directory(context: UserHandlerContext) -> str:
    timelapse_base_dir = os.path.join(context.base_path, "timelapse")
    try:
        os.mkdir(timelapse_base_dir)
    except FileExistsError:
        pass
    timelapse_printer_dir = os.path.join(timelapse_base_dir, context.printer_id)
    try:
        os.mkdir(timelapse_printer_dir)
    except FileExistsError:
        pass
    timelapse_dir = os.path.join(timelapse_printer_dir, str(context.job_info.id))
    try:
        os.mkdir(timelapse_dir)
    except FileExistsError:
        pass

    return timelapse_dir


class TimelapseHandler(UserHandler):
    def call(self, context: UserHandlerContext, *args, **kwargs) -> UserHandlerResult:
        timelapse_dir = ensure_timelapse_directory(context)
        next_index = len(os.listdir(timelapse_dir))
        frame = context.camera_handler.capture(30)
        cv2.imwrite(os.path.join(timelapse_dir, f"timelapse_{next_index}.jpg"), frame)

        return UserHandlerResult.SUCCESS
