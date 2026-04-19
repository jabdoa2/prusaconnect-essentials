from handler.user_handler import UserHandler, UserHandlerContext, UserHandlerResult
from lib.tag_detection import identify_sheet_id


class DetectPrintSheet(UserHandler):
    def __init__(self):
        self._model = None

    def call(self, context: UserHandlerContext, *args, **kwargs) -> UserHandlerResult:
        allowed_build_plates = kwargs.get("allowed_build_plates")
        check_empty = kwargs.get("check_empty", False)
        empty_sheet_detection_threshold = kwargs.get(
            "empty_sheet_detection_threshold", 0.5
        )

        if allowed_build_plates is None and not check_empty:
            print(
                "Invalid config. No build plate ids to check and check_empty set to False."
            )
            return UserHandlerResult.CONFIG_INVALID

        print("Capturing frame")
        frame = context.camera_handler.capture(30)
        if allowed_build_plates is not None:
            print("Running tag detection")
            tag_id = identify_sheet_id(frame)

            if tag_id is None:
                print("No sheet detected. Will retry!")
                return UserHandlerResult.RETRY

            if tag_id not in allowed_build_plates:
                print("Incorrect build sheet detected.")
                return UserHandlerResult.FAILED

            print("Correct build sheet detected.")

        if check_empty:
            # local import to prevent tensorflow import at every start
            from lib.empty_sheet_detection import (
                load_empty_sheet_detection_model,
                check_if_sheet_is_empty,
                DetectionResult,
            )

            if not self._model:
                self._model = load_empty_sheet_detection_model()

            detection_result = check_if_sheet_is_empty(
                self._model, frame, empty_sheet_detection_threshold
            )
            if detection_result == DetectionResult.UNDECIDED:
                print("Model is undecided if the sheet if empty. Will retry!")
                return UserHandlerResult.RETRY

            if detection_result == DetectionResult.NOT_CLEAR:
                print("Print sheet is not clear.")
                return UserHandlerResult.FAILED

            print("Print sheet is clear.")

        return UserHandlerResult.SUCCESS
