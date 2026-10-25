"""
detector.py - finds furniture in a photo using an open-vocabulary YOLO model.

Why not regular YOLO?
  Regular YOLO models are trained on the COCO dataset, which has 80 fixed
  classes. COCO has "tv", "bed" and "refrigerator", but NO bookshelf, dresser,
  wardrobe or water heater, which are the most dangerous things in a quake.
  Open-vocabulary models pair the YOLO detector with a text encoder, so we can
  type the names of the objects we want and it searches for those words.

Two models from Ultralytics can do this, and this file supports both:
  * YOLOE (default): newer (2025), more accurate at "zero-shot" detection,
    and its text encoder (MobileCLIP) downloads from GitHub.
  * YOLO-World: the original open-vocabulary YOLO. Uses OpenAI's CLIP text
    encoder. Set MODEL_FILE = "yolov8s-worldv2.pt" below to use it instead.

The first run downloads the model weights automatically (about 25 MB for the
detector plus a few hundred MB for the text encoder, once).
"""

from functools import lru_cache

import numpy as np

from .hazards import CATALOG, all_prompts

# "m" = medium model (about 60 MB). Tested on 14 real room photos (Oct 24):
# it found the door in the living-room sample that the small model called a
# cabinet, and it mixed up fewer things. About 0.3 s per photo on a laptop CPU.
# Options: "yoloe-11s-seg.pt" (smaller, twice as fast, more mistakes),
# "yoloe-11m-seg.pt", "yoloe-11l-seg.pt" (bigger, no clear gain in our test),
# or "yolov8s-worldv2.pt" for YOLO-World.
MODEL_FILE = "yoloe-11m-seg.pt"

# Ignore detections the model is less sure about than this (0 to 1).
# Open-vocabulary scores run lower than normal YOLO, so this is fairly low.
MIN_CONFIDENCE = 0.12


@lru_cache(maxsize=1)
def _load_model():
    """Load the detection model once and reuse it (loading takes a few seconds).

    lru_cache remembers the return value, so every later call is instant.
    """
    # Imported here (not at the top) so the physics tests run without
    # needing the heavy machine-learning libraries installed.
    from ultralytics import YOLOE, YOLOWorld

    prompts, keys = all_prompts()
    if "world" in MODEL_FILE:
        model = YOLOWorld(MODEL_FILE)
        model.set_classes(prompts)  # tell the model which words to look for
    else:
        model = YOLOE(MODEL_FILE)
        # YOLOE wants the words already turned into "text embeddings"
        # (lists of numbers that capture their meaning), so we compute those.
        model.set_classes(prompts, model.get_text_pe(prompts))
    return model, keys


def detect(image_bgr: np.ndarray):
    """Run detection on an OpenCV image (BGR color order).

    Returns a list of dicts, one per object:
        {"key": "bookshelf", "prompt": "bookcase", "confidence": 0.61,
         "box": [x1, y1, x2, y2]}      # pixel corners, top-left origin
    """
    model, keys = _load_model()
    results = model.predict(
        image_bgr,
        conf=MIN_CONFIDENCE,
        iou=0.5,
        # agnostic_nms: if "bookshelf" and "bookcase" both fire on the same
        # object, keep only the more confident box instead of both.
        agnostic_nms=True,
        verbose=False,
    )[0]

    detections = []
    for box, cls, conf in zip(results.boxes.xyxy.tolist(),
                              results.boxes.cls.tolist(),
                              results.boxes.conf.tolist()):
        class_index = int(cls)
        key = keys[class_index]
        if key is None:
            continue  # a distractor ("chandelier", "stove"...): not a hazard
        if conf < CATALOG[key].get("min_confidence", MIN_CONFIDENCE):
            continue  # this kind of object needs a more confident detection
        detections.append({
            "key": key,
            "prompt": results.names[class_index],
            "confidence": round(float(conf), 3),
            "box": [round(v, 1) for v in box],
        })
    return detections
