# QuakeReady walkthrough (study guide for Aadi)

This guide is for you, not for judges. Read it with the code open. The goal is that by Monday you can explain every part of QuakeReady in your own words, change it confidently, and answer the written questions honestly.

## 0. Be honest about how it was built

You chose to have Claude write the first version and to study and modify it. The Congressional App Challenge expects the app to be your own work, so:

* Read the official rules on AI tools before submitting. If they ask, say plainly that you used an AI coding assistant and what you did yourself.
* Make real changes of your own (ideas in section 6). The more of the final app you wrote or reshaped, the stronger and safer your entry is.
* Only describe things in the written answers and video that you actually understand and did.

## 1. Get it running first (30 minutes)

1. Follow "Run it" in `README.md`.
2. Scan each sample, then a photo of your own room.
3. Press **Shake the room**. Watch the seismograph under the photo: the orange line is "now", and the red dashed lines show the shaking needed to start the most fragile item rocking. Then press **I strapped it** on one red item and shake again. That item stays put and the score goes up.
4. Change the floor to 2 of 2. Notice the score drop: upper floors shake harder.
5. Switch **Type of earthquake** between Cascadia and Seattle Fault. Same peak shaking, but the fall chances change. Can you explain why? (Section 3.)
6. Type different budgets ($10, $25, $50) and watch which fixes get the "Buy first" tag.
7. Run `python -m pytest`. All 21 tests should pass.

## 2. Read the code in this order

| Order | File | What to understand | Time |
|---|---|---|---|
| 1 | `app/physics.py` | The whole idea of the app. Work through the torque derivation in the top comment on paper. | 45 min |
| 2 | `tests/test_physics.py` | How each formula is checked with numbers you can work out by hand. | 15 min |
| 3 | `app/hazards.py` | Why each object has a depth, center of mass and severity. | 15 min |
| 4 | `app/measure.py` | How pixels become inches, and why the median beats the average. | 20 min |
| 5 | `app/shaking.py` | Calling two web APIs, parsing JSON, falling back when the internet fails. | 20 min |
| 6 | `app/detector.py` | Open-vocabulary detection and why COCO YOLO isn't enough. | 20 min |
| 7 | `app/rocking.py` | **New.** Synthetic earthquakes and the Housner rocking simulation. The hardest and most impressive file. | 60 min |
| 8 | `app/planner.py` | **New.** The knapsack algorithm behind "Buy first". | 20 min |
| 9 | `tests/test_rocking.py` | **New.** How the simulation and planner are checked. | 15 min |
| 10 | `app/analyze.py` | The pipeline, fall zones, the hit test, the inpainted background, and how `evaluate()` runs in three passes. | 40 min |
| 11 | `app/main.py` | How FastAPI turns Python functions into web routes. | 15 min |
| 12 | `static/app.js` | Fetching from the server, drawing on a canvas, the seismograph, and the shake animation playing back the simulation. | 75 min |

## 3. The key ideas, in plain words

**Tip-over physics.** An earthquake shoves the floor sideways. The furniture's own inertia acts like a sideways push at its center of mass. Gravity pulls it back down about the front edge. Tipping starts when the shove's torque beats gravity's torque: `a * h_com > g * D/2`. Mass cancels, so only shape matters. For a uniform box that's `a_tip = g * D / H`. A 72 in by 12 in bookshelf tips at about 0.17 g.

**Demand vs capacity.** "Capacity" is what the object can take (its tip threshold). "Demand" is how hard your floor shakes. Engineers compare them as a ratio. Ratio over 1 means it tips.

**Where demand comes from.** USGS publishes the peak ground acceleration (PGA) engineers use to design buildings at every U.S. location. We use the "design earthquake", which is 2/3 of the USGS maximum considered earthquake. That's the same 2/3 rule the building code uses for its design values. Upper floors sway more, so ASCE 7 multiplies by `1 + 2z/h`.

**Open-vocabulary detection.** Normal YOLO only knows the 80 COCO classes. YOLOE and YOLO-World also run a text encoder, a model that turns words into numbers. They match image regions against those numbers, so you can ask for "water heater" without training anything.

**Scale from a photo.** A door is about 80 inches tall, so its pixel height tells you pixels per inch. With no door, every object votes using its typical height, and the median vote wins. The median ignores outliers.

**Fall zone.** A toppling object's top lands about one height from its base. In the photo, that's an oval in front of the base, squashed vertically because the floor is seen at an angle. We sprinkle 60 test points over each bed, couch, desk or door footprint and count how many land in the oval.

**Starting to tip is not falling (the rocking simulation).** The static threshold says when a bookshelf *lifts onto its edge*. Whether it then falls depends on the shaking's timing. In 1963 George Housner wrote down the equation for a block rocking on a shaking floor. `rocking.py` solves that equation step by step, 100 times per simulated second: work out the angular acceleration, update the speed, update the angle. Each time the block slams back down it loses some speed. If it leans past its "slenderness angle" `alpha = atan(half-depth / COM height)`, it falls. Two surprising results come out of this, and both are real physics you can talk about:

* *Size matters, not just shape.* Two boxes with the same D/H start rocking at the same shaking, but the bigger one falls less often, because it rocks more slowly and each push is over before it can lean far.
* *Duration matters.* A Cascadia quake and a Seattle Fault quake with the same peak shaking give different answers. Cascadia goes on much longer, so things get pushed many more times.

**Synthetic earthquakes and Monte Carlo.** We can't record the next Cascadia quake, so we make 24 realistic fake ones: random noise, shaped to the frequencies the ground likes (the Kanai-Tajimi filter), given a build-up-and-fade envelope, and scaled so the peak matches USGS. Running every object through all 24 and counting falls gives a probability. That's a Monte Carlo simulation, the same idea insurance and engineering firms use. The random seed is fixed, so the same room always gives the same answer (important for a demo).

**The score now uses the simulation.** Each item's danger score splits 75 points between "how far past its tipping point" (40) and "how often it actually fell" (35), times severity, plus 25 if it lands on a bed or blocks a door.

**The budget plan (knapsack).** Each fix has a cost and a value (the points it gives back to the room score). Choosing the best set under a budget is the 0/1 knapsack problem. Instead of trying all 2^n combinations, dynamic programming fills a table `best[dollars]` one fix at a time. Read the comment at the top of `planner.py` and try a 3-item example on paper.

**The animation plays back the physics.** The server sends each object's lean angle 20 times per simulated second, plus the floor's movement. The browser plays that back, sped up so a 90-second quake fits in 12 seconds. When an object passes its tipping angle, the browser takes over and lets it fall the rest of the way.

**Inpainting.** For the animation, OpenCV's `cv2.inpaint` fills each object's box with a guess of what's behind it, using the surrounding pixels.

## 4. Questions a judge might ask

Practice answering these out loud without notes:

1. Why does a heavier bookshelf not tip more easily than a light one of the same shape?
2. What does 0.17 g mean physically?
3. Why can't you just use a normal YOLO model?
4. How do you know how big something is from a 2D photo? When does that fail?
5. Where does the shaking number for my address come from?
6. Why is the 2nd floor more dangerous than the 1st?
7. What happens if the detector is wrong?
8. Your app says the bookshelf "will tip" but only falls 60% of the time. Isn't that a contradiction? (No: one is when it starts rocking, the other is whether it falls.)
9. Why is a long Cascadia quake worse than a short one with the same peak?
10. Are the simulated earthquakes real? (No: synthetic, shaped like real ones, scaled to real USGS values. Say what's simplified: rigid box, no wall behind it, no sliding, 90 s instead of 3 to 5 minutes.)
11. How does the budget plan pick fixes, and why not just take the cheapest first?
12. What would you build next?

## 5. Honest differences from the original plan

The plan said YOLO-World. The code supports both YOLO-World and YOLOE (switch with `MODEL_FILE` in `app/detector.py`). It defaults to YOLOE, a newer model from the same company, because it's more accurate at zero-shot detection, and because its text encoder downloads from GitHub. Claude couldn't download YOLO-World's text encoder (OpenAI CLIP) in its test environment, so YOLO-World is untested. Try both on your own photos and keep whichever works better. Comparing them would make a good technical-challenge story if you actually do it.

Rocking dynamics were a "2.0 idea" in the first version. They're in now (`rocking.py`), along with the budget planner, the seismograph, the quake-type picker and a print stylesheet. On Oct 24 the real detector was tested on the 3 samples plus 11 COCO room photos (the boxes are in `quakeready_preview/detection_test_*.jpg`). It was good at fridges, TVs, couches and beds, but it made some mistakes, so these fixes went in:

* It switched from the small model to the medium one (`yoloe-11m-seg.pt`). The small model called the living-room door a cabinet.
* `hazards.DISTRACTORS` are extra prompts like "chandelier", "stove" and "computer tower". They give the model a better answer to choose than a wrong one, and then we throw those boxes away. Before this, the chandelier was a "floor lamp" and a stove was a "water heater".
* Some objects need a higher score to count (`min_confidence` in `hazards.py`): water heaters, floor lamps and beds.
* `analyze.clean_detections` has three new sanity rules: unsure floor furniture near the ceiling is dropped, a tall, narrow "cabinet" is relabeled as a door, and a "wall shelf" that's nearly as tall as it is wide becomes a bookshelf. The last three tests in `tests/test_physics.py` check these rules.

It still makes mistakes, which is why every item has a "Not a ..." button. Test it on 10 to 15 photos of your own rooms and count right and wrong detections. That's real data for your technical-challenge answer.

## 6. Ways to make it yours (pick at least two)

Each of these is a few hours. Do them yourself, using this guide and the comments. Ask Claude to explain things or review your code, not to write it.

* **Tune `hazards.py` with real measurements.** Measure the furniture in your house and friends' houses and replace the default depths and heights. Add new objects (aquarium, piano, microwave on a cart).
* **Improve the fall zone.** Right now every item falls toward the center of the photo. Let the user tap which way it faces.
* **Paper-sheet ruler.** Detect a sheet of printer paper (11 in) as a second ruler in `measure.py`.
* **Compare models.** Run YOLOE and YOLO-World on 15 of your own photos, count correct detections, and keep the better one.
* **Wall behind the furniture.** `rocking.py` lets objects rock both ways. Add an option where backward rocking is blocked by the wall (when `theta` would go negative, stop it at 0). Compare fall chances with and without it.
* **Tune the quakes.** Change `omega_g`, `duration` and `strong_end` in `QUAKE_TYPES` and see how the results change. Research real values for Seattle-area soil and explain your choice.
* **Add a third quake type**, such as a deep Nisqually-style quake (2001, M6.8).
* **Design.** Restyle the page, write the "How it works" text in your own words, add your name and school.
* **Deploy it.** Put it on Hugging Face Spaces or Render so judges can try a link.

## 7. Before you submit

* Replace the sample photos with your own rooms.
* Strap one real item at home and film it for the end of the video.
* Check that `python -m pytest` passes and the app runs from a fresh `pip install`.
