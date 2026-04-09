import apriltag
import cv2

MINIMUM_APRILTAG_DECISION_MARGIN = 50

def find_sheet_tags(img: cv2.typing.MatLike) -> list[apriltag.Detection]:
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    options = apriltag.DetectorOptions(families="tag16h5")
    detector = apriltag.Detector(options)
    results = detector.detect(gray)
    return results

def identify_sheet_id(img: cv2.typing.MatLike) -> int | None:
    results = find_sheet_tags(img)
    valid_results = [
        result
        for result in results
        if result.decision_margin > MINIMUM_APRILTAG_DECISION_MARGIN
           and result.hamming <= 1
    ]
    if not valid_results:
        print(results)
        print(
            f"No valid code found. Found {len(results)} uncertain tags. Skipping!"
        )
        return None
    if len(valid_results) > 1:
        print(results)
        print(
            f"Found {len(valid_results)} codes. Make sure that there is only one. Skipping!"
        )
        return None
    print(
        f"Found exactly one code with ID {valid_results[0].tag_id} with decision_margin={valid_results[0].decision_margin} (higher is better)"
    )
    return valid_results[0].tag_id

