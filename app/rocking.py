"""
rocking.py - a real earthquake simulation for every piece of furniture.

physics.py answers "how hard a shove does it take to START tipping?" That's
the static threshold  a_tip = g * D / H.  But starting to tip isn't falling.
A bookshelf can lift onto its front edge, rock, and land back on its base.
Whether it actually falls depends on how long the shaking lasts, how fast it
goes back and forth, and how big the object is. This file finds out by
simulating it, the same way earthquake engineers study rocking objects.

There are two parts.

1. MAKE FAKE (BUT REALISTIC) EARTHQUAKES.  (unit_quakes)
   We don't have a recording of the next Cascadia earthquake, so we build
   "synthetic ground motions", a standard engineering trick:
     a. Start with random noise (every frequency equally strong).
     b. Shape its frequencies like real ground shaking with the
        Kanai-Tajimi filter. Soil and rock pass some frequencies and damp
        others; the filter peaks at the ground's "favorite" frequency
        omega_g. The Clough-Penzien filter then removes the very slowest
        drift, which real accelerometers never show.
     c. Multiply by an "envelope" so it builds up, shakes hard for a while,
        then dies out.
     d. Scale it so its strongest moment matches the shaking from USGS.
   Two kinds of Northwest earthquake have very different personalities:
     * Seattle Fault (shallow, right under the city): short, sharp, fast
       back-and-forth. About 10 seconds of strong shaking.
     * Cascadia Subduction Zone (magnitude 9, off the coast): slower, rolling
       shaking that goes on for minutes. We simulate 90 seconds to keep the
       app fast. Real Cascadia shaking can last 3 to 5 minutes, so the real
       risk is, if anything, higher than what we show.
   The numbers in QUAKE_TYPES are reasonable textbook-style values, not a
   seismologist's model of these exact faults.

2. ROCK EACH OBJECT THROUGH EACH QUAKE.  (simulate_room)
   We use George Housner's rocking-block model (1963), the classic model for
   tall blocks on a shaking floor. For a block of half-depth b and
   center-of-mass height h:
       alpha = atan(b / h)        how far it can lean before gravity stops
                                  pulling it back (its "slenderness angle")
       R     = sqrt(b^2 + h^2)    distance from the pivot corner to the COM
       p^2   = 3 g / (4 R)        "frequency parameter": big objects have a
                                  small p, so they react more slowly
   The angle theta it has lifted off the floor obeys
       theta'' = -p^2 * [ sin(alpha*s - theta) + (a_ground/g) * cos(alpha*s - theta) ]
   where s = +1 when it leans on one corner and -1 on the other.
     * It only starts rocking when |a_ground| > g * tan(alpha) = g * b / h,
       which is exactly the static threshold from physics.py.
     * Each time it slams back down on its base it loses energy. Housner
       showed the angular speed keeps the fraction e = 1 - 1.5 * sin(alpha)^2.
     * Once theta passes alpha, its center of mass is past the pivot and it
       falls over.
   We step time forward 0.01 s at a time (100 steps per second), using
   "semi-implicit Euler": new speed from the acceleration, then new angle
   from the new speed.

   We run every object through N_QUAKES different random quakes and count
   how many times it falls. "Fell in 19 of 24" means about a 79% chance.
   This is called a Monte Carlo simulation.

Simplifications (good material for your technical-challenge answer):
  * Furniture is treated as a solid box. Real shelves have their weight
    wherever the books are (com_ratio handles some of that).
  * It rocks freely both ways. A wall right behind it stops backward rocking,
    which can make it a bit safer than we predict. Safe-side again.
  * It never slides. Sliding needs a slippery floor and stubby objects;
    tall furniture rocks first.
  * The shaking is the same on every floor except for its strength (the
    building-height factor from physics.py). A real building also filters
    the shaking.

Speed: every step updates all quakes and all objects at once as NumPy
arrays (shape: quakes x objects), so the whole room takes well under a second.
"""

from functools import lru_cache
import math

import numpy as np

from .physics import WALL_HOOK_RELEASE_G

G = 9.81            # m/s^2
INCH = 0.0254       # meters per inch
DT = 0.01           # simulation time step, seconds
N_QUAKES = 24       # how many random earthquakes each object goes through
FRAME_RATE = 20     # frames per second of simulated time sent to the browser
SEED = 2026         # fixed random seed: the same room always gets the same answer

QUAKE_TYPES = {
    "seattle": {
        "label": "Seattle Fault quake (short and violent)",
        "duration": 25,      # seconds simulated
        "rise": 2,           # seconds to build up to full strength
        "strong_end": 10,    # strong shaking lasts until here, then fades
        "omega_g": 15.0,     # ground's favorite frequency, rad/s (about 2.4 Hz)
        "zeta_g": 0.6,       # how sharp that peak is (damping)
    },
    "cascadia": {
        "label": "Cascadia megaquake (long and rolling)",
        "duration": 90,
        "rise": 10,
        "strong_end": 60,
        "omega_g": 8.0,      # slower shaking, about 1.3 Hz
        "zeta_g": 0.6,
    },
}
DEFAULT_QUAKE = "cascadia"


# ------------------------------------------------------- 1. make the quakes

def _filter_gain(omega, omega_g, zeta_g):
    """How much the ground amplifies each frequency (Kanai-Tajimi x Clough-Penzien).

    omega is an array of frequencies in rad/s. Returns the amplitude gain.
    Both filters are written as POWER (squared amplitude), so we take sqrt.
    """
    kt = ((omega_g ** 4 + (2 * zeta_g * omega_g * omega) ** 2)
          / ((omega_g ** 2 - omega ** 2) ** 2 + (2 * zeta_g * omega_g * omega) ** 2))
    omega_f, zeta_f = 0.1 * omega_g, 0.6   # high-pass that removes slow drift
    cp = omega ** 4 / ((omega_f ** 2 - omega ** 2) ** 2 + (2 * zeta_f * omega_f * omega) ** 2)
    return np.sqrt(kt * cp)


def _envelope(t, q):
    """Strength over time: ramp up, hold, then fade to 5% by the end."""
    env = np.ones_like(t)
    env[t < q["rise"]] = (t[t < q["rise"]] / q["rise"]) ** 2
    late = t > q["strong_end"]
    fade_rate = math.log(20) / (q["duration"] - q["strong_end"])
    env[late] = np.exp(-fade_rate * (t[late] - q["strong_end"]))
    return env


@lru_cache(maxsize=4)
def unit_quakes(quake_type: str = DEFAULT_QUAKE, n_quakes: int = N_QUAKES):
    """N random ground-acceleration records whose peak is exactly 1.

    Returns an array of shape (n_quakes, n_steps). Multiply by the shaking
    in g to get real records. Cached, because it never changes.
    """
    q = QUAKE_TYPES.get(quake_type, QUAKE_TYPES[DEFAULT_QUAKE])
    n = int(q["duration"] / DT)
    t = np.arange(n) * DT
    rng = np.random.default_rng(SEED)

    noise = rng.standard_normal((n_quakes, n))
    # Frequency domain: rfft splits each record into its frequencies, we
    # multiply each one by the filter gain, and irfft puts it back together.
    omega = 2 * np.pi * np.fft.rfftfreq(n, DT)
    shaped = np.fft.irfft(np.fft.rfft(noise, axis=1) * _filter_gain(omega, q["omega_g"], q["zeta_g"]),
                          n, axis=1)
    records = shaped * _envelope(t, q)
    records /= np.abs(records).max(axis=1, keepdims=True)
    return records


def ground_displacement(accel):
    """Turn one acceleration record (any units) into a displacement shape.

    Integrate twice (acceleration -> velocity -> position) with cumulative
    sums. Tiny errors pile up into a slow drift, so after each integration
    we subtract the best-fit straight line ("baseline correction", which
    real seismologists also do). Only the shape matters: the browser uses it
    to shake the photo.
    """
    t = np.arange(len(accel)) * DT

    def detrend(x):
        slope, intercept = np.polyfit(t, x, 1)
        return x - (slope * t + intercept)

    velocity = detrend(np.cumsum(accel) * DT)
    return detrend(np.cumsum(velocity) * DT)


# --------------------------------------------------- 2. rock the objects

def simulate_room(items, demand_g, quake_type=DEFAULT_QUAKE, n_quakes=N_QUAKES):
    """Run every unsecured hazard through n_quakes earthquakes.

    items     the app's item dicts (only "tip" and "wall" kinds are simulated)
    demand_g  peak sideways acceleration on this floor, in g

    Returns {"per_item": {id: {...}}, "frames": {...} for the animation, ...}
    """
    q = QUAKE_TYPES.get(quake_type, QUAKE_TYPES[DEFAULT_QUAKE])
    ground = unit_quakes(quake_type, n_quakes) * demand_g * G   # m/s^2
    n_steps = ground.shape[1]
    stride = int(round(1 / (FRAME_RATE * DT)))                   # steps per frame

    tippers = [it for it in items if it["kind"] == "tip" and not it.get("secured")]
    hangers = [it for it in items if it["kind"] == "wall" and not it.get("secured")]

    # ---- the rocking blocks (all of them at once) ----
    m = len(tippers)
    b = np.array([it["depth_in"] / 2 * INCH for it in tippers])
    h = np.array([it["com_ratio"] * it["height_in"] * INCH for it in tippers])
    alpha = np.arctan2(b, h) if m else np.zeros(0)
    p2 = 3 * G / (4 * np.hypot(b, h)) if m else np.zeros(0)
    restitution = 1 - 1.5 * np.sin(alpha) ** 2
    start_g = np.tan(alpha)                    # needed shaking to start rocking, in g

    theta = np.zeros((n_quakes, m))            # lean angle, radians
    omega = np.zeros((n_quakes, m))            # lean speed, radians per second
    fallen = np.zeros((n_quakes, m), bool)
    fall_step = np.full((n_quakes, m), -1)
    frames = []                                # lean angle every `stride` steps

    for k in range(n_steps):
        a = ground[:, k:k + 1]                 # this instant's shaking, shape (quakes, 1)

        # Which corner is it pivoting on? If it's leaning, the side it leans
        # to. If it's flat, the side the shaking throws it toward (opposite
        # to the floor's push, like you lurching back when a bus starts).
        side = np.where(theta != 0, np.sign(theta),
                        np.where(omega != 0, np.sign(omega), -np.sign(a)))
        lean = alpha * side - theta
        accel = -p2 * (np.sin(lean) + (a / G) * np.cos(lean))

        # A flat, still block stays put unless the shaking beats its threshold.
        resting = (theta == 0) & (omega == 0)
        accel = np.where(resting & (np.abs(a) <= start_g * G), 0.0, accel)
        accel = np.where(fallen, 0.0, accel)

        new_omega = omega + accel * DT
        new_theta = theta + new_omega * DT

        # Slammed back down onto its base (the angle changed sign)? It now
        # pivots on the other corner and keeps only part of its speed.
        landed = (theta != 0) & (np.sign(new_theta) != np.sign(theta))
        new_theta = np.where(landed, 0.0, new_theta)
        new_omega = np.where(landed, new_omega * restitution, new_omega)
        # Barely moving after landing: call it settled.
        new_omega = np.where(landed & (np.abs(new_omega) < 1e-3), 0.0, new_omega)

        # Leaned past alpha: the center of mass is past the corner. It falls.
        falls_now = ~fallen & (np.abs(new_theta) >= alpha)
        fall_step = np.where(falls_now, k, fall_step)
        fallen |= falls_now
        new_theta = np.where(fallen, np.sign(new_theta) * alpha, new_theta)

        theta, omega = new_theta, np.where(fallen, 0.0, new_omega)
        if k % stride == 0:
            frames.append(theta.copy())

    # ---- wall-hung items: they hop off open hooks the first time the
    # shaking passes WALL_HOOK_RELEASE_G (see physics.py). ----
    over = np.abs(ground) > WALL_HOOK_RELEASE_G * G             # (quakes, steps)
    wall_step = np.where(over.any(axis=1), over.argmax(axis=1), -1)

    # ---- pick ONE quake to show in the animation ----
    # Choose the quake where the number of things that fell is closest to the
    # average, so the animation is a typical result, not a lucky or unlucky one.
    fell_count = fallen.sum(axis=1) + (wall_step >= 0) * len(hangers)
    shown = int(np.argmin(np.abs(fell_count - fell_count.mean())))

    per_item = {}
    angles = {}
    frame_array = np.array(frames) if frames else np.zeros((0, n_quakes, m))
    for j, it in enumerate(tippers):
        n_fell = int(fallen[:, j].sum())
        step = int(fall_step[shown, j])
        per_item[it["id"]] = {
            "fell": n_fell, "of": n_quakes, "p_fall": round(n_fell / n_quakes, 2),
            "alpha": round(float(alpha[j]), 4),
            "fall_time": round(step * DT, 2) if step >= 0 else None,
        }
        angles[it["id"]] = np.round(frame_array[:, shown, j], 4).tolist()
    for it in hangers:
        step = int(wall_step[shown])
        n_fell = int((wall_step >= 0).sum())
        per_item[it["id"]] = {
            "fell": n_fell, "of": n_quakes, "p_fall": round(n_fell / n_quakes, 2),
            "alpha": None,
            "fall_time": round(step * DT, 2) if step >= 0 else None,
        }

    accel = ground[shown] / (demand_g * G) if demand_g > 0 else ground[shown]
    disp = ground_displacement(accel)
    disp /= max(1e-9, np.abs(disp).max())
    return {
        "quake_type": quake_type if quake_type in QUAKE_TYPES else DEFAULT_QUAKE,
        "label": q["label"],
        "duration_s": q["duration"],
        "n_quakes": n_quakes,
        "per_item": per_item,
        "expected_falls": round(float(fell_count.mean()), 1),
        "frames": {
            "fps": FRAME_RATE,
            "accel": np.round(accel[::stride], 3).tolist(),     # -1..1, for the seismograph
            "ground": np.round(disp[::stride], 3).tolist(),     # -1..1, shakes the photo
            "angles": angles,                                    # radians, per item id
        },
    }
