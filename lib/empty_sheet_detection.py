from enum import Enum

import numpy as np
import tensorflow as tf
from tensorflow.lite.python.interpreter import SignatureRunner

TF_MODEL_FILE_PATH = "build_plates.tflite"
CLASS_NAMES = ["clear", "not_clear"]

EmptySheetModel = SignatureRunner


class DetectionResult(Enum):
    CLEAR = 0
    NOT_CLEAR = 1
    UNDECIDED = 2


def load_empty_sheet_detection_model() -> EmptySheetModel:
    interpreter = tf.lite.Interpreter(model_path=TF_MODEL_FILE_PATH)
    classify_lite = interpreter.get_signature_runner("serving_default")
    return classify_lite


def check_if_sheet_is_empty(
    model: EmptySheetModel, img: np.ndarray, threshold: float = 0.5
) -> DetectionResult:

    img_array = tf.keras.utils.img_to_array(img)  # ty: ignore[unresolved-attribute]
    img_array = tf.image.resize(img_array, (384, 384))
    img_array = tf.expand_dims(img_array, 0)  # Create a batch

    predictions_lite = model(keras_tensor_513=img_array)["output_0"]
    score_lite = tf.nn.softmax(predictions_lite)

    score = np.max(score_lite)
    detected_class = CLASS_NAMES[np.argmax(score_lite)]
    print(
        "This image most likely belongs to {} with a {:.2f} percent confidence.".format(
            detected_class, 100 * score
        )
    )

    if score < threshold:
        return DetectionResult.UNDECIDED
    if detected_class == "clear":
        return DetectionResult.CLEAR
    return DetectionResult.NOT_CLEAR
