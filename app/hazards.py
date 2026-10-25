"""
hazards.py - QuakeReady's "knowledge base" about household objects.

The detector (YOLO-World) only tells us WHAT something is and WHERE it is in
the photo. It knows nothing about earthquakes. This file supplies the missing
real-world facts for each kind of object:

  * prompts         - the text phrases we give YOLO-World to look for.
                      YOLO-World is "open vocabulary": it finds anything you can
                      describe in words, so synonyms help it catch more objects.
  * kind            - how the object is dangerous in a quake:
                        "tip"       free-standing furniture that can topple over
                        "wall"      things hung on a wall that can jump off hooks
                        "target"    places people are (bed, crib, couch) or need
                                    to get through (door). We check whether a
                                    falling object would land on these.
  * typical_height  - a normal height in inches. Used to estimate the photo's
                      scale when there's no door in view (see measure.py).
  * depth           - a normal front-to-back depth in inches. A single photo
                      can't see depth, so we use a researched default. The user
                      can correct it in the app.
  * com_ratio       - where the center of mass is, as a fraction of the height.
                      0.5 means "halfway up" (a uniform box). Top-heavy things
                      like a TV on a stand have a higher value.
  * severity        - how bad it is if this object falls (0 to 1.2). A
                      300-pound wardrobe is worse than a floor lamp. A water
                      heater is the worst: it can break a gas line and start a
                      fire.
  * min_confidence  - (optional) a stricter detector score for objects the
                      model often mixes up. See detector.MIN_CONFIDENCE.
  * fix / fix_cost  - the specific hardware that prevents it, and roughly what
                      it costs at a hardware store (USD, 2026 prices, approximate).

Sources for the fixes: Earthquake Country Alliance "Secure Your Space" guide and
FEMA E-74 "Reducing the Risks of Nonstructural Earthquake Damage".
Dimensions are typical retail furniture sizes.
"""

# Each entry is keyed by a short id. The dictionary order doesn't matter.
CATALOG = {
    # ---------- free-standing furniture that can tip over ----------
    "bookshelf": {
        "label": "Bookshelf",
        "prompts": ["bookshelf", "bookcase", "shelving unit", "shelf full of books", "desk hutch"],
        "kind": "tip",
        "typical_height": 72, "depth": 12, "com_ratio": 0.5, "severity": 1.0,
        "fix": "Two anti-tip furniture straps screwed into a wall stud. Put heavy books on the bottom shelves.",
        "fix_cost": 12,
    },
    "dresser": {
        "label": "Dresser",
        "prompts": ["dresser", "chest of drawers"],
        "kind": "tip",
        "typical_height": 44, "depth": 18, "com_ratio": 0.5, "severity": 0.9,
        "fix": "Anti-tip strap kit into a wall stud, plus child-safety latches so drawers can't slide open and shift the weight forward.",
        "fix_cost": 15,
    },
    "wardrobe": {
        "label": "Wardrobe",
        "prompts": ["wardrobe", "armoire"],
        "kind": "tip",
        "typical_height": 72, "depth": 22, "com_ratio": 0.5, "severity": 1.0,
        "fix": "Two L-brackets or heavy-duty furniture straps anchored into wall studs at the top.",
        "fix_cost": 15,
    },
    "cabinet": {
        "label": "Cabinet",
        "prompts": ["cabinet", "cupboard", "filing cabinet"],
        "kind": "tip",
        "typical_height": 48, "depth": 18, "com_ratio": 0.5, "severity": 0.8,
        "fix": "L-bracket into a wall stud, and latches on the doors or drawers.",
        "fix_cost": 12,
    },
    "tv": {
        "label": "TV",
        "prompts": ["television", "tv", "flat screen tv"],
        "kind": "tip",
        # Height is the screen itself. Depth is the footprint of its stand.
        "typical_height": 28, "depth": 9, "com_ratio": 0.6, "severity": 0.7,
        "fix": "TV anti-tip strap kit that connects the back of the TV to the wall or the furniture under it.",
        "fix_cost": 15,
    },
    "monitor": {
        "label": "Computer monitor",
        "prompts": ["computer monitor"],
        "kind": "tip",
        "typical_height": 16, "depth": 8, "com_ratio": 0.6, "severity": 0.4,
        "fix": "Monitor strap or a few dots of earthquake putty under the stand.",
        "fix_cost": 8,
    },
    "refrigerator": {
        "label": "Refrigerator",
        "prompts": ["refrigerator", "fridge"],
        "kind": "tip",
        "typical_height": 68, "depth": 30, "com_ratio": 0.5, "severity": 1.0,
        "fix": "Appliance anti-tip strap anchored to a wall stud behind the fridge.",
        "fix_cost": 25,
    },
    "water_heater": {
        "label": "Water heater",
        "prompts": ["water heater", "hot water tank"],
        "min_confidence": 0.3,  # rare in photos and often confused with stoves
        "kind": "tip",
        "typical_height": 60, "depth": 20, "com_ratio": 0.5, "severity": 1.2,
        "fix": "Double metal strap kit (top third and bottom third) into wall studs, plus a flexible gas line. Required by Washington code.",
        "fix_cost": 40,
    },
    "lamp": {
        "label": "Floor lamp",
        "prompts": ["floor lamp"],
        "min_confidence": 0.3,  # wall lamps and decorations often score 0.2
        "kind": "tip",
        "typical_height": 60, "depth": 10, "com_ratio": 0.5, "severity": 0.3,
        "fix": "Move it away from the bed and walkways, or swap it for a lamp with a weighted base.",
        "fix_cost": 0,
    },

    # ---------- things hung on walls ----------
    "mirror": {
        "label": "Mirror",
        "prompts": ["mirror", "wall mirror"],
        "kind": "wall",
        "typical_height": 30, "depth": 1, "com_ratio": 0.5, "severity": 0.7,
        "fix": "Replace open hooks with closed (screw-eye) hooks, or mount with screws into a stud. Never hang glass above a bed.",
        "fix_cost": 8,
    },
    "frame": {
        "label": "Picture frame",
        "prompts": ["picture frame", "framed painting", "poster frame"],
        "kind": "wall",
        "typical_height": 20, "depth": 1, "com_ratio": 0.5, "severity": 0.4,
        "fix": "Closed earthquake hooks or museum putty on the bottom corners.",
        "fix_cost": 6,
    },
    "wall_shelf": {
        "label": "Wall shelf",
        "prompts": ["wall shelf", "floating shelf"],
        "kind": "wall",
        "typical_height": 10, "depth": 8, "com_ratio": 0.5, "severity": 0.5,
        "fix": "Screw brackets into studs and add a lip or museum putty so items can't slide off.",
        "fix_cost": 10,
    },

    # ---------- places where people are ("targets") ----------
    "bed": {
        "label": "Bed", "prompts": ["bed"], "kind": "target",
        "min_confidence": 0.2,  # canopies and loft frames sometimes score ~0.17
        "typical_height": 24, "depth": 80, "com_ratio": 0.5, "severity": 0,
        "target_reason": "falls onto the bed, where people sleep",
    },
    "crib": {
        "label": "Crib", "prompts": ["crib", "baby crib"], "kind": "target",
        "typical_height": 40, "depth": 28, "com_ratio": 0.5, "severity": 0,
        "target_reason": "falls onto the crib",
    },
    "couch": {
        "label": "Couch", "prompts": ["couch", "sofa"], "kind": "target",
        "typical_height": 34, "depth": 36, "com_ratio": 0.5, "severity": 0,
        "target_reason": "falls onto the couch, where people sit",
    },
    "desk": {
        "label": "Desk", "prompts": ["desk"], "kind": "target",
        "typical_height": 30, "depth": 24, "com_ratio": 0.5, "severity": 0,
        "target_reason": "falls onto the desk, where someone may be working",
    },
    "door": {
        "label": "Door", "prompts": ["door", "open door", "interior door", "doorway"], "kind": "target",
        # Standard US interior door: 80 in tall. measure.py uses this as a ruler.
        "typical_height": 80, "depth": 2, "com_ratio": 0.5, "severity": 0,
        "target_reason": "blocks the door, your escape route",
    },
}

# Things that look a bit like our objects but aren't dangerous in the same
# way. We ask the detector to look for these too. If "chandelier" scores
# higher than "floor lamp" on the same box, the box becomes a chandelier, and
# then we throw it away. This is a common trick with open-vocabulary models:
# give them the right answer as an option, so they don't pick a wrong one.
DISTRACTORS = [
    "chandelier", "ceiling light", "window", "curtain", "radiator",
    "coffee table", "dining table", "chair", "stove", "oven", "microwave",
    "kitchen counter", "sink", "computer tower", "person",
]

# Free-standing furniture stands on the floor, and in a photo taken from
# standing height the floor is in the lower part of the picture. So a
# "bookshelf" or "floor lamp" whose bottom edge is in the top half of the
# photo is probably something else (a chandelier, an upper kitchen cabinet).
# TVs and monitors are exempt because they sit on other furniture.
FLOOR_ITEMS = {"bookshelf", "dresser", "wardrobe", "cabinet", "refrigerator",
               "water_heater", "lamp"}

# Height of a standard US interior door, our preferred "ruler" in the photo.
DOOR_HEIGHT_IN = 80


def all_prompts():
    """Flatten the catalog into two parallel lists for YOLO-World.

    Returns (prompts, keys) where prompts[i] is a text phrase and keys[i] is
    the catalog id it belongs to. For example "bookcase" -> "bookshelf".
    """
    prompts, keys = [], []
    for key, info in CATALOG.items():
        for phrase in info["prompts"]:
            prompts.append(phrase)
            keys.append(key)
    for phrase in DISTRACTORS:
        prompts.append(phrase)
        keys.append(None)   # None = "not something we care about"
    return prompts, keys
