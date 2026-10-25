"""Tests for the physics. Run with:  python -m pytest

These check the math against numbers you can work out by hand, so if
someone changes a formula by mistake, a test fails.
"""

import pytest

from app import physics
from app.analyze import evaluate, fall_zone, zone_hits


def test_bookshelf_tip_threshold():
    # 12 in deep, 72 in tall: a_tip = D / H = 12 / 72 = 0.1667 g
    assert physics.tip_threshold_g(12, 72) == pytest.approx(0.1667, abs=1e-3)


def test_low_dresser_is_more_stable():
    # 18 in deep, 30 in tall: 0.6 g, much harder to tip than the bookshelf
    assert physics.tip_threshold_g(18, 30) == pytest.approx(0.6)


def test_top_heavy_tips_sooner():
    uniform = physics.tip_threshold_g(10, 40, com_ratio=0.5)
    top_heavy = physics.tip_threshold_g(10, 40, com_ratio=0.7)
    assert top_heavy < uniform


def test_floor_amplification():
    assert physics.floor_amplification(1, 1) == 1.0       # house, ground floor
    assert physics.floor_amplification(2, 2) == 2.0       # top of 2 stories
    assert physics.floor_amplification(10, 10) == pytest.approx(2.8)
    assert physics.floor_amplification(99, 3) == physics.floor_amplification(3, 3)  # clamped


def test_design_scenario_is_two_thirds():
    assert physics.scenario_pga(0.6, "design") == pytest.approx(0.4)
    assert physics.scenario_pga(0.6, "maximum") == pytest.approx(0.6)


def test_risk_levels():
    assert physics.risk_level(0.5, 0.17)[0] == "high"
    assert physics.risk_level(0.5, 0.6)[0] == "medium"    # 83% of its limit
    assert physics.risk_level(0.2, 0.6)[0] == "low"


def test_room_score_ignores_secured_items():
    items = [{"level": "high", "score": 80, "secured": False}]
    strapped = [{"level": "secured", "score": 0, "secured": True}]
    assert physics.room_score(items) < physics.room_score(strapped) == 100


def _item(id, key, kind, box, height=72, depth=12):
    return {"id": id, "key": key, "kind": kind, "box": box, "label": key,
            "height_in": height, "depth_in": depth, "com_ratio": 0.5,
            "severity": 1.0, "fix": "strap", "fix_cost": 12, "secured": False}


def test_bookshelf_next_to_bed_hits_bed():
    shelf = _item(0, "bookshelf", "tip", [100, 100, 200, 400])
    bed = _item(1, "bed", "target", [180, 300, 500, 450])
    hits = zone_hits(shelf, [bed], fall_zone(shelf))
    assert [h["key"] for h in hits] == ["bed"]


def test_far_away_bed_is_safe():
    shelf = _item(0, "bookshelf", "tip", [100, 100, 200, 400])
    bed = _item(1, "bed", "target", [900, 300, 1200, 450])
    assert zone_hits(shelf, [bed], fall_zone(shelf)) == []


def test_strapping_removes_item_from_fix_list():
    shelf = _item(0, "bookshelf", "tip", [100, 100, 200, 400])
    result = evaluate([shelf], pga_g=0.67)
    assert result["fix_list"] == [0]
    shelf["secured"] = True
    result = evaluate([shelf], pga_g=0.67)
    assert result["fix_list"] == [] and result["room_score"] == 100


# ---- detection clean-up rules (analyze.clean_detections) ----

def _det(key, box, conf=0.3):
    return {"key": key, "prompt": key, "confidence": conf, "box": box}


def test_unsure_floor_furniture_near_ceiling_is_dropped():
    from app.analyze import clean_detections
    # A "floor lamp" hanging from the top of a 640 px photo is a chandelier.
    assert clean_detections([_det("lamp", [90, 0, 200, 170])], 446, 640) == []
    # The same box with a confident score is kept (low camera angle).
    assert len(clean_detections([_det("lamp", [90, 0, 200, 170], 0.8)], 446, 640)) == 1


def test_tall_narrow_cabinet_becomes_door():
    from app.analyze import clean_detections
    out = clean_detections([_det("cabinet", [385, 86, 446, 639])], 446, 640)
    assert out[0]["key"] == "door"


def test_tall_wall_shelf_becomes_bookshelf():
    from app.analyze import clean_detections
    out = clean_detections([_det("wall_shelf", [78, 75, 457, 357])], 500, 375)
    assert out[0]["key"] == "bookshelf"
