"""
physics.py - the earthquake science behind QuakeReady.

Everything here is plain math with no AI, so it is easy to test and explain.
All accelerations are in "g" (1 g = 9.81 m/s^2, the pull of gravity).

1. WHEN DOES FURNITURE TIP?  (tip_threshold_g)
   Picture a bookshelf standing against a wall. During an earthquake the floor
   shoves sideways. From the bookshelf's point of view, that shove feels like a
   sideways force  F = m * a  acting at its center of mass (COM).

   The shelf wants to rotate about its front bottom edge (the "pivot").
   Two torques fight about that pivot:
       tipping torque   = m * a * h_com        (sideways shove, lever arm = COM height)
       restoring torque = m * g * (D / 2)      (gravity, lever arm = half the depth)

   It starts to tip when the tipping torque wins:
       m * a * h_com  >  m * g * D / 2
   The mass cancels out (a heavy shelf and a light one of the same shape tip at
   the same shaking), leaving:
       a_tip = g * (D / 2) / h_com

   For a uniform box the COM is halfway up (h_com = H / 2), so
       a_tip = g * D / H
   Example: a 72 in tall, 12 in deep bookshelf tips at 12/72 = 0.17 g.

   This is the "static" threshold: the shaking needed to START rocking. Real
   furniture sometimes rocks back without falling, so this is a cautious
   (safe-side) estimate, which is what you want for a safety tool.

2. HOW HARD WILL MY FLOOR SHAKE?  (floor_acceleration_g)
   USGS gives the peak ground acceleration (PGA) at your address. Upper floors
   of a building sway more than the ground, so the building code (ASCE 7-16,
   equation 13.3-1, for objects inside buildings) estimates the acceleration at height z in a building of
   height h as
       a_floor = PGA * (1 + 2 * z / h)
   Ground floor -> 1x. The roof of a building -> up to 3x.

3. WHERE DOES IT LAND?  (fall_reach_in)
   A tipping object rotates about its base, so its top lands about one full
   height away. A 6 ft bookshelf can reach 6 ft across the room.
"""

G = 9.81  # m/s^2, only used to show m/s^2 values to the user


def tip_threshold_g(depth_in: float, height_in: float, com_ratio: float = 0.5) -> float:
    """Sideways floor acceleration (in g) that starts tipping a rigid block.

    depth_in   front-to-back depth of the base (inches)
    height_in  total height (inches)
    com_ratio  center-of-mass height as a fraction of total height (0.5 = middle)
    """
    if depth_in <= 0 or height_in <= 0:
        raise ValueError("depth and height must be positive")
    com_height = com_ratio * height_in
    return (depth_in / 2) / com_height


def floor_amplification(floor: int, total_floors: int) -> float:
    """ASCE 7 height factor (1 + 2 z/h).

    We treat each story as equal height, so on floor n of an N-story building
    the floor sits at z/h = (n - 1) / N. Floor 1 (ground) -> factor 1.0.
    """
    total_floors = max(1, int(total_floors))
    floor = min(max(1, int(floor)), total_floors)
    z_over_h = (floor - 1) / total_floors
    return 1 + 2 * z_over_h


# Which earthquake are we preparing for? USGS gives the "Maximum Considered
# Earthquake" (MCE), a very rare worst case. The building code designs for
# 2/3 of the MCE (the "design earthquake"), e.g. S_DS = 2/3 * S_MS in ASCE 7.
SCENARIOS = {
    "design": {"factor": 2 / 3, "label": "design earthquake (2/3 of the USGS maximum)"},
    "maximum": {"factor": 1.0, "label": "maximum considered earthquake"},
}


def scenario_pga(pga_mce_g: float, scenario: str = "design") -> float:
    """Ground shaking (g) for the chosen scenario."""
    return pga_mce_g * SCENARIOS.get(scenario, SCENARIOS["design"])["factor"]


def floor_acceleration_g(pga_g: float, floor: int = 1, total_floors: int = 1) -> float:
    """Peak sideways acceleration felt by furniture on a given floor (in g)."""
    return pga_g * floor_amplification(floor, total_floors)


def fall_reach_in(height_in: float) -> float:
    """How far from its base a toppling object's top can land (inches)."""
    return height_in


# Open picture hooks and nails let frames hop off at fairly gentle shaking.
# There's no exact formula for this (it depends on the hook), so we use a
# conservative estimate. Closed hooks or screws remove the risk entirely.
WALL_HOOK_RELEASE_G = 0.3


def risk_level(demand_g: float, capacity_g: float) -> tuple[str, float]:
    """Compare how hard the floor shakes (demand) with what the object can
    take (capacity). Engineers call demand / capacity the "utilization ratio".

        ratio >= 1.0   -> HIGH:   it is expected to tip
        0.6 to 1.0     -> MEDIUM: close enough that our estimates (photo size,
                                  default depth) could be off by that much
        ratio < 0.6    -> LOW
    Returns (level, ratio).
    """
    ratio = demand_g / capacity_g
    if ratio >= 1.0:
        return "high", ratio
    if ratio >= 0.6:
        return "medium", ratio
    return "low", ratio


def item_score(ratio: float, severity: float, hits_target: bool,
               p_fall: float | None = None) -> int:
    """Turn the physics into one 0-100 danger score for sorting the fix list.

    * up to 75 points for the shaking, scaled by severity (how bad it is if
      this object falls):
        - without a simulation: all 75 from how far past its tipping point
          the shaking goes (capped at 2x, because "tips easily" vs "tips
          very easily" matters less than tip vs no tip)
        - with the rocking simulation (rocking.py): 40 from that ratio and
          35 from the chance it actually FALLS (p_fall, 0 to 1)
    * +25 if it would land on a bed, crib, couch, desk or block a door
    """
    if p_fall is None:
        shake_part = 75 * min(ratio, 2.0) / 2.0
    else:
        shake_part = 40 * min(ratio, 2.0) / 2.0 + 35 * p_fall
    score = shake_part * severity + (25 if hits_target else 0)
    return int(round(min(100, max(0, score))))


# How many room-score points each danger point costs, by risk level.
# planner.py uses the same weights to work out which fixes help most.
LEVEL_WEIGHTS = {"high": 0.45, "medium": 0.2, "low": 0.05}


def item_penalty(item: dict) -> float:
    """Points this one item takes off the room score (0 if secured)."""
    if item.get("secured") or item.get("level") not in LEVEL_WEIGHTS:
        return 0.0
    return item["score"] * LEVEL_WEIGHTS[item["level"]]


def room_score(items: list[dict]) -> int:
    """Overall room safety score, 100 = nothing to fix.

    Each unsecured item removes points according to its danger score and level.
    Secured items remove nothing, so strapping things visibly raises the score.
    """
    penalty = sum(item_penalty(item) for item in items)
    return int(round(max(0, 100 - penalty)))
