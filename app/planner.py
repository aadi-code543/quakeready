"""
planner.py - "I have $20. What should I buy first?"

Most families won't fix everything at once. Given a budget, we pick the set
of fixes that raises the room safety score the most without going over.

This is the classic "0/1 knapsack" problem from computer science:
  * each fix is an item you either take (1) or leave (0)
  * its WEIGHT is its cost in dollars
  * its VALUE is how many room-score points it gives back
    (physics.item_penalty: exactly what that item takes off the score now)
  * the knapsack holds at most `budget` dollars

Trying every combination would take 2^n tries (over a million for 20
fixes). Dynamic programming is much faster. We fill in a table where
    best[d] = the most points we can win back spending at most d dollars
one fix at a time. For each fix costing c, worth v:
    best[d] = max(best[d],           # skip this fix
                  best[d - c] + v)   # buy it, plus the best use of the rest
Going through d from high to low makes sure each fix is bought only once.
That's n x budget steps, a few thousand for a normal room: instant.

Free fixes (like "move the lamp away from the bed") cost $0, so they're
always in the plan.
"""

from . import physics

MAX_BUDGET = 2000  # dollars; keeps the table small even if someone types 1e9


def best_fixes(items, budget):
    """Choose which unsecured hazards to fix first within `budget` dollars.

    Returns {"budget", "ids", "cost", "score_now", "score_after"}.
    """
    budget = int(min(max(0, budget or 0), MAX_BUDGET))
    hazards = [it for it in items if it["kind"] != "target"]
    candidates = [it for it in hazards
                  if not it.get("secured") and it.get("level") in ("high", "medium")]

    free = [it for it in candidates if it["fix_cost"] <= 0]
    paid = [it for it in candidates if it["fix_cost"] > 0]

    # best[d] = most points won back with d dollars; chosen[d] = which fixes.
    best = [0.0] * (budget + 1)
    chosen = [[] for _ in range(budget + 1)]
    for it in paid:
        cost = int(round(it["fix_cost"]))
        value = physics.item_penalty(it)
        for d in range(budget, cost - 1, -1):
            if best[d - cost] + value > best[d]:
                best[d] = best[d - cost] + value
                chosen[d] = chosen[d - cost] + [it["id"]]

    ids = [it["id"] for it in free] + chosen[budget]
    # Score if the plan were done: pretend those items are secured.
    after = [dict(it, secured=True) if it["id"] in ids else it for it in hazards]
    return {
        "budget": budget,
        "ids": ids,
        "cost": sum(int(round(it["fix_cost"])) for it in candidates if it["id"] in ids),
        "score_now": physics.room_score(hazards),
        "score_after": physics.room_score(after),
    }
