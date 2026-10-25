"""
analyze.py - the QuakeReady pipeline. This is where all the pieces meet:

    photo --> detector.py --> clean up boxes --> measure.py (inches)
          --> shaking.py (USGS) --> physics.py (tip threshold, risk)
          --> fall zones (does it land on the bed? block the door?)
          --> rocking.py (24 simulated quakes: how often does it FALL?)
          --> sorted fix list + room score + planner.py (best fixes for $X)

evaluate() is split out from analyze_photo() so that when the user edits an
item in the app (types a real height, marks it "strapped", deletes a wrong
detection) we can redo the physics instantly without running the AI again.
"""

import base64

import cv2
import numpy as np

from . import physics, planner, rocking, shaking
from .detector import detect
from .hazards import CATALOG, FLOOR_ITEMS
from .measure import estimate_scale, measure_object

MAX_SIDE_PX = 1280  # shrink big phone photos; detection doesn't need more


# ---------------------------------------------------------------- helpers

def _area(box):
    x1, y1, x2, y2 = box
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


def _intersection(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    return _area([x1, y1, x2, y2])


def clean_detections(detections, img_w, img_h):
    """Remove the detector's most common mistakes.

    * A box covering almost the whole photo is usually the model "seeing" the
      entire room as one object. Drop it.
    * Two boxes of the same type where one sits mostly inside the other are
      usually the same object detected twice. Keep the more confident one.
    * Free-standing furniture (hazards.FLOOR_ITEMS) should reach down toward
      the floor. A shaky detection (confidence under 0.5) whose bottom edge
      is in the top 40% of the photo is probably a chandelier or an upper
      kitchen cabinet. Confident detections are trusted, because a photo
      taken from low down can make real furniture look high.
    * A "wall shelf" that is nearly as tall as it is wide isn't a floating
      shelf: it's a bookcase or a desk hutch, which can tip.
    * A very tall, narrow "cabinet" or "wardrobe" that runs from near the top
      of the photo to the floor is usually a door. We relabel it, because
      doors matter twice: they're escape routes and our best ruler.
    """
    image_area = img_w * img_h
    kept = []
    for d in detections:
        x1, y1, x2, y2 = d["box"]
        if _area(d["box"]) >= 0.85 * image_area:
            continue
        if d["key"] in FLOOR_ITEMS and y2 < 0.4 * img_h and d["confidence"] < 0.5:
            continue
        if d["key"] == "wall_shelf" and (y2 - y1) > 0.6 * (x2 - x1):
            d = dict(d, key="bookshelf")
        tall = (y2 - y1) > 0.6 * img_h and (y2 - y1) > 2.4 * (x2 - x1)
        if d["key"] in ("cabinet", "wardrobe") and tall and y1 < 0.25 * img_h:
            d = dict(d, key="door")
        kept.append(d)
    kept.sort(key=lambda d: d["confidence"], reverse=True)

    result = []
    for det in kept:
        duplicate = False
        for better in result:
            if better["key"] != det["key"]:
                continue
            overlap = _intersection(det["box"], better["box"])
            smaller = min(_area(det["box"]), _area(better["box"]))
            if smaller > 0 and overlap / smaller > 0.7:
                duplicate = True
                break
        if not duplicate:
            result.append(det)
    return result


# ------------------------------------------------------------ fall zones

def fall_zone(item):
    """Where in the PHOTO the object could land, as a simple shape.

    Tipping furniture usually stands against a wall, so it falls forward,
    toward the camera. On the floor in the photo that looks like an oval in
    front of its base. The oval's size comes from the object's own height in
    pixels, because the top lands about one height away (physics.fall_reach_in).
    The floor is seen at a slant, so distances toward the camera look shorter;
    we squash the oval's vertical radius by half to roughly account for that.

    Wall-hung items fall straight down, so their zone is the strip below them.
    """
    x1, y1, x2, y2 = item["box"]
    w, h = x2 - x1, y2 - y1
    if item["kind"] == "wall":
        return {"type": "rect", "x1": x1 - 0.15 * w, "y1": y1,
                "x2": x2 + 0.15 * w, "y2": y2 + 2.5 * h}
    reach_px = h  # one full height
    return {"type": "ellipse", "cx": (x1 + x2) / 2, "cy": y2,
            "rx": w / 2 + 0.35 * reach_px, "ry": 0.5 * reach_px}


def _point_in_zone(x, y, zone):
    if zone["type"] == "rect":
        return zone["x1"] <= x <= zone["x2"] and zone["y1"] <= y <= zone["y2"]
    # Only the half of the oval in front of the base (lower in the photo).
    if y < zone["cy"] - 0.15 * zone["ry"]:
        return False
    dx = (x - zone["cx"]) / zone["rx"]
    dy = (y - zone["cy"]) / zone["ry"]
    return dx * dx + dy * dy <= 1


def _footprint(target):
    """The part of a target's box that touches the floor (where people are)."""
    x1, y1, x2, y2 = target["box"]
    share = 0.15 if target["key"] == "door" else 0.4
    return [x1, y2 - share * (y2 - y1), x2, y2]


def zone_hits(item, targets, zone):
    """Which targets does this item's fall zone cover?

    We sprinkle a 10 x 6 grid of test points over each target's footprint and
    count how many land inside the zone. More than 8% counts as a hit.
    """
    hits = []
    for target in targets:
        if target["id"] == item["id"]:
            continue
        fx1, fy1, fx2, fy2 = _footprint(target)
        xs = np.linspace(fx1, fx2, 10)
        ys = np.linspace(fy1, fy2, 6)
        inside = sum(_point_in_zone(x, y, zone) for x in xs for y in ys)
        if inside / 60 > 0.08:
            hits.append({"id": target["id"], "key": target["key"],
                         "reason": CATALOG[target["key"]]["target_reason"]})
    return hits


# ------------------------------------------------------------ main logic

def build_items(detections, pixels_per_inch):
    """Turn raw detections into "items" with real-world sizes and facts."""
    items = []
    for i, det in enumerate(detections):
        info = CATALOG[det["key"]]
        height_in, width_in = measure_object(det, pixels_per_inch)
        items.append({
            "id": i,
            "key": det["key"],
            "label": info["label"],
            "kind": info["kind"],
            "box": det["box"],
            "confidence": det["confidence"],
            "height_in": height_in,
            "width_in": width_in,
            "depth_in": info["depth"],
            "com_ratio": info["com_ratio"],
            "severity": info["severity"],
            "fix": info.get("fix"),
            "fix_cost": info.get("fix_cost", 0),
            "secured": False,
            "edited": False,
        })
    return items


def evaluate(items, pga_g, floor=1, total_floors=1, scenario="design",
             quake_type=rocking.DEFAULT_QUAKE, budget=25):
    """Run the physics on every item. Safe to call again after user edits.

    pga_g is the USGS maximum-considered PGA; scenario picks how much of it.
    quake_type ("cascadia" or "seattle") picks the kind of shaking for the
    rocking simulation. budget (dollars) is for the "what to buy first" plan.
    """
    ground = physics.scenario_pga(pga_g, scenario)
    demand = physics.floor_acceleration_g(ground, floor, total_floors)
    targets = [it for it in items if it["kind"] == "target"]

    # Pass 1: the quick static check (does it start to tip?) and fall zones.
    for item in items:
        # Reset results from any earlier run.
        for k in ("threshold_g", "ratio", "level", "score", "zone", "hits", "explain", "sim"):
            item.pop(k, None)
        if item["kind"] == "target":
            continue

        if item["kind"] == "tip":
            capacity = physics.tip_threshold_g(item["depth_in"], item["height_in"],
                                               item["com_ratio"])
        else:  # wall-hung
            capacity = physics.WALL_HOOK_RELEASE_G
        level, ratio = physics.risk_level(demand, capacity)

        zone = fall_zone(item)
        hits = zone_hits(item, targets, zone) if level != "low" else []

        if item["secured"]:
            level, hits = "secured", []

        item.update({"threshold_g": round(capacity, 3), "ratio": round(ratio, 2),
                     "level": level, "zone": zone, "hits": hits})

    # Pass 2: rock everything through 24 simulated earthquakes (rocking.py).
    sim = rocking.simulate_room(items, demand, quake_type)

    # Pass 3: scores and explanations, now that we know how often each falls.
    for item in items:
        if item["kind"] == "target":
            continue
        item["sim"] = sim["per_item"].get(item["id"])
        p_fall = item["sim"]["p_fall"] if item["sim"] else None
        item["score"] = 0 if item["secured"] else physics.item_score(
            item["ratio"], item["severity"], bool(item["hits"]), p_fall)
        item["explain"] = _explain(item, item["threshold_g"], demand, item["ratio"], item["level"])

    hazards = [it for it in items if it["kind"] != "target"]
    to_fix = sorted((it for it in hazards if it["level"] in ("high", "medium")),
                    key=lambda it: it["score"], reverse=True)
    return {
        "items": items,
        "ground_g": round(ground, 3),
        "demand_g": round(demand, 3),
        "scenario": scenario,
        "scenario_label": physics.SCENARIOS.get(scenario, physics.SCENARIOS["design"])["label"],
        "amplification": round(physics.floor_amplification(floor, total_floors), 2),
        "room_score": physics.room_score(hazards),
        "fix_list": [it["id"] for it in to_fix],
        "fix_total_cost": sum(it["fix_cost"] for it in to_fix),
        "simulation": sim,
        "plan": planner.best_fixes(items, budget),
    }


def _explain(item, capacity, demand, ratio, level):
    """One or two plain-English sentences for the user."""
    if level == "secured":
        return "Marked as secured. Nice work."
    if item["kind"] == "wall":
        start = f"Hung items can jump off open hooks around {capacity:.2f} g."
    else:
        start = (f"Starts to tip at {capacity:.2f} g "
                 f"({item['depth_in']:.0f} in deep / {item['height_in']:.0f} in tall).")
    if ratio >= 1:
        text = start + f" Your floor could shake at {demand:.2f} g, {ratio:.1f}x more than it can take."
    else:
        text = start + f" Your floor could shake at {demand:.2f} g, {ratio:.0%} of its limit."
    sim = item.get("sim")
    if sim and ratio >= 1:
        if sim["fell"] == 0:
            text += f" It rocked but stayed up in all {sim['of']} simulated quakes."
        else:
            text += f" It fell over in {sim['fell']} of {sim['of']} simulated quakes."
    return text


def background_plate(image, items):
    """A copy of the photo with every hazard erased, for the shake animation.

    When an object falls over, the browser needs to show what was BEHIND it.
    We can't know that, but OpenCV's inpainting can make a believable guess by
    filling the hole from the surrounding pixels (the Telea algorithm, which
    "flows" colors inward from the edge of the hole).
    Inpainting big holes at full size is slow, so we do it on a quarter-size
    copy, scale it back up, and only use it inside the holes.
    """
    h, w = image.shape[:2]
    mask = np.zeros((h, w), np.uint8)
    for item in items:
        if item["kind"] != "target":
            x1, y1, x2, y2 = (int(round(v)) for v in item["box"])
            mask[max(0, y1 - 2):y2 + 2, max(0, x1 - 2):x2 + 2] = 255
    if not mask.any():
        return image

    small = cv2.resize(image, (w // 4, h // 4), interpolation=cv2.INTER_AREA)
    small_mask = cv2.resize(mask, (w // 4, h // 4), interpolation=cv2.INTER_NEAREST)
    filled = cv2.inpaint(small, small_mask, 5, cv2.INPAINT_TELEA)
    filled = cv2.GaussianBlur(filled, (5, 5), 0)
    filled = cv2.resize(filled, (w, h), interpolation=cv2.INTER_LINEAR)

    plate = image.copy()
    plate[mask > 0] = filled[mask > 0]
    return plate


def _to_data_url(image):
    ok, jpg = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 88])
    return "data:image/jpeg;base64," + base64.b64encode(jpg.tobytes()).decode()


def analyze_photo(image_bytes: bytes, address: str = "", floor: int = 1,
                  total_floors: int = 1, scenario: str = "design",
                  quake_type: str = rocking.DEFAULT_QUAKE, budget: int = 25):
    """Full pipeline for one uploaded photo. Returns a JSON-ready dict."""
    # Decode the upload. IMREAD_COLOR also applies the phone's EXIF rotation,
    # so portrait photos come out the right way up.
    image = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("That file isn't an image OpenCV can read.")

    h, w = image.shape[:2]
    scale = MAX_SIDE_PX / max(h, w)
    if scale < 1:
        image = cv2.resize(image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
        h, w = image.shape[:2]

    detections = clean_detections(detect(image), w, h)
    ppi, scale_method = estimate_scale(detections, w, h)
    items = build_items(detections, ppi)
    quake = shaking.lookup(address)
    result = evaluate(items, quake["pga"], floor, total_floors, scenario, quake_type, budget)

    # Send back the exact (resized) image so the browser's boxes line up,
    # plus the "hazards erased" version for the animation.
    result.update({
        "image": _to_data_url(image),
        "background": _to_data_url(background_plate(image, items)),
        "width": w, "height": h,
        "pixels_per_inch": ppi, "scale_method": scale_method,
        "shaking": quake, "floor": floor, "total_floors": total_floors,
        "quake_type": quake_type, "budget": budget,
    })
    return result
