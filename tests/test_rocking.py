"""Tests for the rocking simulation (rocking.py) and the budget planner
(planner.py). Run with:  python -m pytest
"""

import numpy as np
import pytest

from app import planner, rocking


def _block(id, height, depth, kind="tip"):
    return {"id": id, "kind": kind, "height_in": height, "depth_in": depth,
            "com_ratio": 0.5, "secured": False}


def test_quakes_are_repeatable_and_scaled_to_one():
    a = rocking.unit_quakes("seattle")
    assert np.abs(a).max(axis=1) == pytest.approx(np.ones(rocking.N_QUAKES))
    # Same seed, same quakes: the app gives the same answer every time.
    rocking.unit_quakes.cache_clear()
    assert np.array_equal(a, rocking.unit_quakes("seattle"))


def test_below_threshold_never_moves():
    # 72 x 12 bookshelf starts to tip at 0.17 g. At 0.10 g it must not budge.
    sim = rocking.simulate_room([_block(0, 72, 12)], demand_g=0.10, quake_type="seattle")
    assert sim["per_item"][0]["fell"] == 0
    assert max(abs(x) for x in sim["frames"]["angles"][0]) == 0


def test_strong_shaking_topples_a_slender_shelf():
    sim = rocking.simulate_room([_block(0, 72, 12)], demand_g=0.9, quake_type="seattle")
    assert sim["per_item"][0]["p_fall"] > 0.9


def test_squat_objects_are_safer_than_slender_ones():
    sim = rocking.simulate_room([_block(0, 72, 12), _block(1, 30, 24)],
                                demand_g=0.5, quake_type="cascadia")
    assert sim["per_item"][1]["fell"] < sim["per_item"][0]["fell"]


def test_longer_quake_is_worse():
    # Same peak shaking, but Cascadia goes on much longer, so a borderline
    # wardrobe should fall at least as often.
    wardrobe = [_block(0, 72, 22)]
    seattle = rocking.simulate_room(wardrobe, 0.45, "seattle")["per_item"][0]["fell"]
    cascadia = rocking.simulate_room(wardrobe, 0.45, "cascadia")["per_item"][0]["fell"]
    assert cascadia >= seattle


def test_wall_items_drop_when_shaking_passes_hook_limit():
    frame = [_block(0, 20, 1, kind="wall")]
    assert rocking.simulate_room(frame, 0.2, "seattle")["per_item"][0]["fell"] == 0
    assert rocking.simulate_room(frame, 0.5, "seattle")["per_item"][0]["p_fall"] == 1


def _hazard(id, score, cost, level="high"):
    return {"id": id, "kind": "tip", "level": level, "score": score,
            "fix_cost": cost, "secured": False}


def test_planner_picks_best_value_within_budget():
    # $20 budget. Fix A ($15, 80 pts) alone beats B + C ($10 each, 30 pts each).
    items = [_hazard(0, 80, 15), _hazard(1, 30, 10), _hazard(2, 30, 10)]
    plan = planner.best_fixes(items, 20)
    assert plan["ids"] == [0] and plan["cost"] == 15
    # With $25 it can afford A and one of the others; $35 buys all three.
    assert len(planner.best_fixes(items, 25)["ids"]) == 2
    assert len(planner.best_fixes(items, 35)["ids"]) == 3


def test_planner_always_includes_free_fixes_and_raises_score():
    items = [_hazard(0, 50, 0), _hazard(1, 60, 40)]
    plan = planner.best_fixes(items, 10)
    assert plan["ids"] == [0]
    assert plan["score_after"] > plan["score_now"]
