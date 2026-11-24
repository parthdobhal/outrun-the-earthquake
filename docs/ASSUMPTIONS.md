# Assumptions and limitations

**Outrun the Earthquake is a simulation for learning.** It is not a real earthquake warning system, it does not use real sensor data, and it is not Google's software. It reconstructs the published *principle* of smartphone-based earthquake early warning so that people can see and test how it works.

Every number below is an assumption we chose, not a measurement. Where a value is "tuned", it was chosen using the *tuning* random stream only; results are reported on the separate *validation* stream (see `RESULTS.md`).

## The simulated Earth (`outrun/sim/model.py`, `outrun/sim/world.py`)

| Assumption | Value | Why / limitation |
|---|---|---|
| Crust | Uniform: straight-line waves at constant speed | Real crust is layered, so real travel times differ |
| Surface | Flat map in km; phones at height 0 | Fine over a few hundred km; ignores Earth's curvature and hills |
| Source | A single point | Real large quakes rupture along faults tens to hundreds of km long |
| P-wave speed (nominal) | 6.0 km/s | Typical crustal value, not any real region |
| S-wave speed (nominal) | 3.5 km/s | Typical crustal value |
| True speeds | Nominal ± up to 3 % per quake | So the server never knows the exact speeds ("inverse crime" avoided). Limited so P is always faster than S |
| Depth | 5–20 km, random | The server assumes 10 km |
| Origin time | 0–5 s after the simulation starts | So the server cannot assume it is zero |
| Strong shaking | Starts when the S-wave arrives | Surface waves are not modelled |
| Magnitude | Not modelled: one fixed, moderate quake | Magnitude estimation is hard; the real system underestimated the 2023 Türkiye M7.8 quake |
| Times | Seconds from the start of the simulation | Keeps numbers small and precise |

## The simulated region and phones (`outrun/sim/world.py`)

| Assumption | Value |
|---|---|
| Region | 200 × 200 km |
| Towns | Northville (60, 140), radius 12 km, 900 phones; Eastport (150, 110), 10 km, 700; Southbridge (80, 50), 8 km, 500. All invented |
| Countryside | 600 phones, spread evenly |
| Phone clock error | Normal distribution, spread 0.1 s |

## Phone reports (`outrun/sim/reports.py`)

| Assumption | Value |
|---|---|
| Position in a report | Centre of a 2 km grid cell only (privacy coarsening) |
| Phones taking part | 100 % (varied in the robustness sweeps) |
| Detection | Certain within 30 km of the hypocentre, falling linearly to zero at 100 km |
| Detection delay | 0.2–1.0 s after the P-wave arrives |
| Phones that only notice the S-wave | 3 % |
| Upload delay | 0.5–3.0 s |
| False reports (bumped or dropped phones) | 0.5 per phone per hour, at random times |
| Phone counts per cell | The server receives how many active phones are in each cell (counts only), as real systems know from regular check-ins |

## The warning server (`outrun/server/config.py`)

| Assumption or threshold | Value | Note |
|---|---|---|
| Assumed P / S speed | 6.0 / 3.5 km/s | Not the true per-quake speeds |
| Assumed depth | 10 km | Not the true depth |
| Time window | Last 60 s of reports, at most 300 | Keeps work bounded |
| Pre-filter slack | 1.0 s | Allowance for clock, cell and delay errors |
| Grid search | 4 km, then 1 km | Over the region plus a 50 km margin |
| Outlier rule | Residual above 3 × robust spread (at least 0.5 s) | Robust spread = 1.4826 × median absolute deviation |
| Model error added to the 95 % error radius | 2.5 km | Tuned so the radius covers the truth about 95 % of the time |
| Alert rule | ≥ K trusted reports, timing misfit ≤ 0.6 s, predicted error ≤ 10 km, azimuthal gap ≤ 240°, not ambiguous, nearby phones not silent, enough reports from within 25 km of the estimate (5, or 30 % of the active phones there if fewer; at least 1) | K = 4–40, default 10 |
| Silent-phones check | Phones within 25 km should have reported 4.5 s after the P-wave reached them; at least 30 % of them must have | The server's own assumptions, deliberately not the simulation's exact rules |
| Processing time | 0.5 s | Assumed |
| Alert delivery time | 2.0 s | Assumed, constant |

## What this project does NOT claim

- It does not provide real warnings and must never be used for safety.
- Its accuracy numbers describe **this simulation**, not real earthquakes or real phones.
- It does not reproduce Google's algorithms, data, scale (millions of phones), magnitude estimation or alert levels.
- The data-wall test is a static check of import statements plus a run-time JSON replay test; it guards against mistakes but is not a security sandbox.

## Sources for the real system

- R. M. Allen et al., "Global earthquake detection and warning using Android phones", *Science* 389 (2025): https://rallen.berkeley.edu/pub/2025AllenBarski/AllenEtAl-AndroidEarthquakeAlerts-Science-2025.pdf
- Harvard EPS Q&A on smartphone earthquake alerts (2026): https://eps.harvard.edu/app/uploads/2026/07/260715-Mostafa-QA-for-EPS-website_SMM.pdf
- Report on the 2023 Türkiye underestimate: https://heise.de/-10502312
