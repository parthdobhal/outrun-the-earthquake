# Interview guide: understanding and explaining every part

Use this to learn the project well enough to explain any file without notes. Read it next to the code. Each part builds on the one before.

---

## 0. The whole project in three sentences

1. An earthquake sends out a fast, weak **P-wave** and a slower, strong **S-wave**.
2. Phones near the quake feel the P-wave first and report *where (roughly) and when*; a server works out where and when the quake started from those times alone.
3. The server's alert travels far faster than the S-wave, so places farther away get seconds of warning, except near the quake, where the shaking wins (the **no-warning zone**).

**Say it like this:** "Phones close to an earthquake feel it first and send a warning at internet speed, which beats the strong shaking to people farther away. Our project simulates that and lets you test it."

---

## 1. The physics, with real numbers (`outrun/sim/model.py`)

**Distance from the quake to a phone.** The quake starts at depth h below the surface. A phone at horizontal distance d is at straight-line distance:

    R = √(d² + h²)

**Arrival time** = when the quake started (origin time t₀) + distance ÷ speed.

Worked example (the one in our tests): quake 10 km deep, phone 80 km away.
- R = √(80² + 10²) = √6500 = **80.62 km**
- P arrives after 80.62 ÷ 6.0 = **13.44 s**
- S arrives after 80.62 ÷ 3.5 = **23.04 s**
- So that phone has 23.04 − 13.44 = **9.6 s** between feeling the P-wave and the strong shaking.

**Common misunderstanding:** "Internet speed makes the warning possible." Not alone. Warning needs *two* head starts: phones *near* the quake detect the fast P-wave early, *and* the message then outruns the slow S-wave. Without early detection near the source, a fast message would have nothing to say.

**Why `math.hypot`?** Squaring a huge number overflows. `hypot` computes √(a² + b² + c²) safely. We added tests with values like 1e200 km to prove it.

---

## 2. Repeatable randomness (`outrun/sim/rng.py`)

Every random choice comes from a seed. The same seed always gives the same world.

- `derive_seed(0, "demo", "phones")` hashes the text `demo:0:phones` with SHA-256 and takes the first 8 bytes: **755423017566677773**. Check it yourself: `printf 'demo:0:phones' | sha256sum` starts with `0a7bcd3b69372b0d`, which is that number in hexadecimal.
- **Three streams:** `tuning` (we chose thresholds using these worlds), `validation` (only used to report results), `demo` (the live app). Same seed number, different stream → completely different world.

**Judge question:** *How do you know you didn't tune on your test data?* — Thresholds were chosen on the tuning stream; RESULTS.md uses only the validation stream.

---

## 3. The simulated world (`outrun/sim/world.py`)

A 200 × 200 km region, 3 invented towns (2,100 phones) plus 600 countryside phones, a hidden quake, and the **true** wave speeds.

- **Spreading phones evenly in a town.** We pick points in the box around the town's circle (clipped to the map) and keep those inside the circle. At least π/4 ≈ 79 % of that box is inside the circle, so it takes fewer than 1.3 tries per phone. (An earlier method needed 16.6 million tries for one phone in an extreme case; a test now counts the tries.)
- **True speeds are nudged up to 3 % from 6.0 and 3.5.** The server assumes exactly 6.0 and 3.5. This avoids the **inverse crime**: testing a solver with data made by the very same model makes results look too perfect.
- **P must stay faster than S.** The nudge e is limited to e < (p − s)/(p + s) = 2.5/9.5 ≈ 0.263 for our speeds, because the slowest possible P is p(1 − e) and the fastest possible S is s(1 + e).
- **No overflow with huge (but finite) inputs.** Three guards, each with tests:
  - The "inside the town?" check uses `math.hypot(dx, dy) <= radius` instead of `dx² + dy² <= radius²`. Squaring a radius like 1e200 overflows.
  - `max_speed_perturbation` first divides p and s by the same power of two, so p + s can't overflow. That division only changes the float's exponent, so it is exact and ordinary speeds give exactly the same answer as before.
  - A config is rejected if the fastest possible P, p(1 + e), would overflow to infinity. The tests found this third case: such a config used to be accepted and then crash while building the world.

---

## 4. Phone reports (`outrun/sim/reports.py`)

A **report** is the only thing that reaches the server: `report_id`, the **centre of the phone's 2 km grid cell** (not its real position), the **detection time on the phone's own clock**, and when it **arrived** at the server.

How a report is made:
1. Detection is certain within 30 km of the quake, falling to zero at 100 km.
2. The phone notices the P-wave 0.2–1.0 s after it arrives (3 % only notice the S-wave).
3. Its clock is a little wrong (spread 0.1 s).
4. Upload takes 0.5–3.0 s.
5. Random **false reports** from bumped phones: 0.5 per phone per hour.

The server also gets **how many active phones are in each cell** (a count only), as real systems know from phones' regular check-ins.

**Judge question:** *Doesn't the server know where the quake is?* — No. The server code cannot even import the simulation (a test fails if it tries), and a second test saves the reports to JSON, re-runs the server on that file alone, and checks the answer is identical.

---

## 5. The warning server (`outrun/server/`)

The server processes reports **in the order they arrive**. After each one:

### 5a. Pre-filter (`prefilter.py`)
Two reports can come from one quake only if their time gap ≤ their distance apart ÷ 6 km/s + 1 s. Example: two phones 6 km apart, the P-wave needs 1 s to go between them, so their times can differ by at most 2 s. This removes some false reports cheaply (not all: far-apart reports are allowed big gaps).

### 5b. Locator (`locator.py`): three steps
The model: report time tᵢ ≈ t₀ + √((x − xᵢ)² + (y − yᵢ)² + h²) ÷ 6. Unknowns: x, y, t₀.

1. **Grid search.** Try every point on a 4 km grid (then 1 km around the best). At each point, the best t₀ is the *median* of (tᵢ − travel time). Score = sum of squared misfits, each capped at 1.5 s so one bad report can't dominate. The lowest score wins.
2. **Least squares (Gauss–Newton).** Starting from the best grid point, repeatedly solve a small linear problem to slide x, y, t₀ to the best fit. It starts with **only the reports that already fit the grid answer** (a bug we found: starting with all reports let 3 false ones drag the answer 67 km).
3. **Outlier rejection.** Robust spread σ = 1.4826 × median absolute misfit. Drop reports with misfit > max(3σ, 0.5 s); refit; repeat.

Quality numbers it reports: timing misfit (rms), **predicted error** (a 95 % circle from the least-squares maths plus a 2.5 km model-error term), **azimuthal gap** (largest angle around the estimate with no reports), and **ambiguous** (a different place over 20 km away fits almost as well, e.g. phones along one straight road).

### 5c. Silent-phones check (`silence.py`)
If the quake were really at the estimate, active phones within 25 km would have reported by now. If fewer than 30 % of those expected did, the estimate is rejected. This is how real systems use "not-yet-triggered" stations. In tuning it removed every confidently wrong alert (6 of 100 before).

There is a catch: if the wrong estimate lands in **empty** countryside, there are no phones there to be silent, so the check cannot reject it. So the rule also needs **positive evidence**: reports from within 25 km of the estimate. A real quake always produces reports near its own epicentre. How many? 5, or 30 % of the active phones actually near the estimate if that is fewer, and always at least 1. (A fixed 5 was too strict where few phones exist: with only a tenth of phones online it missed 69 % of quakes in validation. Scaling it to the local phone count fixed that.)

### 5d. Alert rule (`decide.py`)
Alert the first time: at least **K** trusted reports, misfit ≤ 0.6 s, predicted error ≤ 10 km, gap ≤ 240°, not ambiguous, nearby phones not silent, and enough reports from near the estimate. **K is the slider.**

### 5e. Warning time (`warn.py`)
    predicted warning = (t₀_est + √(d² + h²) ÷ 3.5) − time the alert is delivered
If that is ≤ 0, the place is in the no-warning zone.

---

## 6. Evaluation (`outrun/evaluation/metrics.py`, `scripts/validate.py`)

The only code that compares the server's answer with the truth, **after** the server has finished. It measures location error, origin-time error, alert delay, missed quakes, false alerts (simulated hours of pure noise), warning-time errors, "false reassurance" (told "you have time" when you had none), and how often the 95 % circle really contains the truth. `RESULTS.md` has the numbers.

---

## 7. The web app (`outrun/web/`)

Flask serves the page and four API routes. For one quake: simulation → reports and phone counts (plain data) → server → evaluation → JSON to the browser. The browser only draws. Moving the slider re-runs the server for real.

---

## 8. Likely judge questions and honest answers

| Question | Answer |
|---|---|
| You made the data, so of course you can find the quake? | The server never sees the truth (import test + JSON replay test), uses deliberately imperfect speeds and depth, and is judged on a separate validation stream it was never tuned on. |
| Why one constant wave speed? | A stated simplification; real crust is layered. The speeds are nudged so the server's model is never exactly right. |
| How big was the earthquake? | We don't estimate magnitude: it's genuinely hard; even the real system underestimated Türkiye 2023 (M7.8 estimated as 4.5–4.9). |
| How do you reject a dropped phone? | Pre-filter (impossible timing), outlier rejection (doesn't fit), and the silent-phones check. |
| What is the weakest case? | Sparse, one-sided networks. With phones only in towns, many quakes get no alert and some alerts are wrong ("Towns only" row in RESULTS.md). We report it rather than hide it. |
| Phones' clocks are wrong; how does that work? | Clock error is modelled (0.1 s); it's part of the timing noise the fit tolerates. |
| Why does K matter if false alarms are zero? | With the silent-phones check, our simulation raised no false alarms at normal noise. K still trades alert time against accuracy, and with much more noise (see RESULTS.md) false alarms appear at low K. |
| Is this Google's system? | No. It's a teaching reconstruction of the published principle, with our own simple algorithms. |
| Can it warn real people? | No. It is a simulation and says so on every screen. |
| What was the hardest bug? | Three false reports pulling the fit 67 km away, because least squares started from all reports. Fixed by starting only from reports that fit the grid answer; a test keeps it fixed. |

---

## 9. Check yourself: can you explain these without notes?

1. Why the P-wave is detected but the S-wave is what we warn about.
2. Why the warning is zero near the quake (work out the no-warning radius for an alert delivered 7.5 s after the quake: about 3.5 × 7.5 ≈ 26 km of S travel, √(26² − 10²) ≈ 24 km).
3. The three locator steps and why each is needed.
4. What K does, and what happens at K = 4 versus K = 40.
5. How you stop the server from cheating.
