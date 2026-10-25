"""
measure.py - turns pixel sizes into real-world inches.

A photo has no built-in scale: a bookshelf could be 300 pixels tall because it
is big, or because the camera is close. To convert pixels to inches we need a
"ruler" in the picture: something whose real size we already know.

Strategy, from best to worst:
  1. A door. US interior doors are almost always 80 inches tall. If a door is
     fully in view, pixels_per_inch = door_height_px / 80.
  2. Everything else. Each detected object has a typical real height (from
     hazards.py). Each one gives its own guess of pixels_per_inch. We take the
     MEDIAN of those guesses. The median ignores outliers, so one strange
     object (a tiny bookshelf, a mis-detection) can't wreck the scale.
  3. Nothing usable: fall back to typical heights for every object.

Known limitation (good to mention in your technical-challenge answer):
  Objects farther from the camera look smaller (perspective). One scale for the
  whole photo is an approximation. A depth-estimation model could fix this
  (see the 2.0 ideas in the README). The user can also type in a measured
  height, which the app always trusts over the estimate.
"""

import statistics

from .hazards import CATALOG, DOOR_HEIGHT_IN

# A box touching the photo edge is probably cut off, so its height is wrong.
EDGE_MARGIN_PX = 3


def _is_clipped(box, img_w, img_h) -> bool:
    """True if the box touches the top or bottom edge of the photo."""
    x1, y1, x2, y2 = box
    return y1 <= EDGE_MARGIN_PX or y2 >= img_h - EDGE_MARGIN_PX


def estimate_scale(detections, img_w: int, img_h: int):
    """Work out pixels per inch for the photo.

    Returns (pixels_per_inch or None, method) where method is one of
    "door", "median-of-objects" or "none".
    """
    # 1. Look for a fully visible door, choosing the most confident one.
    doors = [d for d in detections
             if d["key"] == "door" and not _is_clipped(d["box"], img_w, img_h)]
    if doors:
        door = max(doors, key=lambda d: d["confidence"])
        door_px = door["box"][3] - door["box"][1]
        if door_px > 0.25 * img_h:  # a tiny "door" is more likely a cabinet door
            return door_px / DOOR_HEIGHT_IN, "door"

    # 2. Median of every unclipped object's own guess.
    guesses = []
    for d in detections:
        if _is_clipped(d["box"], img_w, img_h):
            continue
        height_px = d["box"][3] - d["box"][1]
        typical = CATALOG[d["key"]]["typical_height"]
        guesses.append(height_px / typical)
    if guesses:
        return statistics.median(guesses), "median-of-objects"

    return None, "none"


def measure_object(det, pixels_per_inch):
    """Estimate one object's height and width in inches.

    The estimate is kept within 0.5x to 1.6x of the object's typical height,
    so a bad scale can't claim a bookshelf is 20 feet tall.
    """
    info = CATALOG[det["key"]]
    typical = info["typical_height"]
    x1, y1, x2, y2 = det["box"]
    if not pixels_per_inch:
        # No scale at all: assume typical size, keep the box's shape.
        aspect = (x2 - x1) / max(1.0, (y2 - y1))
        return float(typical), float(typical * aspect)

    height = (y2 - y1) / pixels_per_inch
    width = (x2 - x1) / pixels_per_inch
    clamped = min(max(height, 0.5 * typical), 1.6 * typical)
    if clamped != height:
        width *= clamped / height  # keep proportions
    return round(clamped, 1), round(width, 1)
