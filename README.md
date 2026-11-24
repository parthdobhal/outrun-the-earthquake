# Outrun the Earthquake

> **This is a simulation for learning. It is not a real earthquake warning system and not Google's software.**

**Phones close to an earthquake feel it first and send a warning at internet speed, which beats the strong shaking to people farther away.** This project simulates that, step by step, and lets you test whether it really works.

An earthquake sends out two waves: a fast, weaker **P-wave** (about 6 km/s) and a slower **S-wave** (about 3.5 km/s) that brings the strong shaking. Simulated phones near the quake feel the P-wave and report *roughly where* (a 2 km square) and *when*. A warning server that **never sees the earthquake** works out where and when it started from those report times alone, then sends an alert. Because the alert travels much faster than the S-wave, places farther away get seconds of warning. Near the quake, the shaking always wins: that is the **no-warning zone**.

Built for the Global Virtual Hackathon 2026 ("Unveiling Technology"). Real smartphone earthquake alerts exist; this project reconstructs the published principle (Allen et al., *Science*, 2025) with our own simple algorithms.

## Try it

1. **Click anywhere on the map** to start an earthquake.
2. Watch the dashed **P-wave** spread; phones it reaches turn yellow and report.
3. Watch the server's **estimate** (teal cross) close in on the quake as reports arrive. Reports it does not trust turn red.
4. See **ALERT SENT**, then the countdown on the person ("You"). Drag the person to see warnings elsewhere.
   The **race** strip under the map shows the timeline: quake starts → alert sent → strong shaking reaches You, with your warning time highlighted.
5. Move the **slider**: how many agreeing reports should the server wait for before alerting? Fewer = faster but less accurate; more = more accurate but later.
6. Press **Test it blind** to run 25 earthquakes you cannot see and check the results.

## Run it (Linux)

Requires Python 3.10 or newer (developed with 3.12).

```bash
cd outrun-the-earthquake
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m outrun.web.app
```

Open <http://127.0.0.1:5000>. (Flask's development server prints a warning that it is not for production; that is expected.)

Run the tests:

```bash
python -m pytest -q
```

### Web version (no server needed)

The same Python package can also run **inside the browser** with [Pyodide](https://pyodide.org) (Python compiled to WebAssembly), so the site can be hosted as plain files, e.g. on GitHub Pages. Nothing is pre-computed: the site ships the Python source files and calculates every number when you click.

```bash
python scripts/build_web.py --out site --cdn     # loads Pyodide from the jsDelivr CDN
python -m http.server -d site 8000               # open http://127.0.0.1:8000
```

`outrun/web/browser/bridge.js` answers the page's `/api/...` requests by calling the Python functions in `outrun/web/api.py` inside a Web Worker (`worker.js`), instead of over HTTP. The CDN build has not been tested from our development machine (it could not reach the CDN); a build with Pyodide hosted locally (`--pyodide-dir`) was tested in Chromium and gives exactly the same numbers as the Flask server.

### Blind validation

Re-run the blind validation (about 10 minutes; writes `RESULTS.md`):

```bash
python scripts/validate.py
```

## How it works

```
 SIMULATION (outrun/sim)            SERVER (outrun/server)                 EVALUATION
 hidden quake, phones,      plain   pre-filter -> grid search ->           compares the
 true wave speeds  ------> reports  least squares -> outlier rejection ->  server's answer
 (ground truth)            + phone  silent-phones check -> alert rule      with the truth,
                           counts   -> warning times                       AFTER the run
```

**The data wall.** The server receives only plain data: each report's grid cell and detection time, and how many active phones are in each cell. It cannot import the simulation (a test fails if any server file tries), and a second test saves a run's input to JSON and checks the server gives an identical answer from that file alone.

**The server's steps** (all in `outrun/server/`):

1. **Pre-filter:** two reports can come from one quake only if their time gap is no more than their distance apart ÷ 6 km/s, plus 1 s.
2. **Grid search:** tries every point on a 4 km then 1 km grid; the best origin time at each point is the median of (report time − travel time); misfits are capped so one bad report cannot dominate.
3. **Least squares (Gauss–Newton):** refines the best grid point, starting only from reports that already fit it.
4. **Outlier rejection:** drops reports whose misfit is above 3 × a robust spread (at least 0.5 s), then refits.
5. **Silent-phones check:** if the quake were really at the estimate, phones within 25 km would have reported by now; if most are silent, the estimate is rejected. Enough reports must also come from near the estimate (5, or fewer where few phones exist).
6. **Alert rule:** at least **K** trusted reports (the slider), timing misfit ≤ 0.6 s, predicted error ≤ 10 km, reports not all on one side, not ambiguous, and the checks in step 5.
7. **Warning time:** (estimated S-wave arrival) − (when the alert is delivered). Zero or less = no warning.

**Honest testing.** The simulation's true wave speeds and depth differ from what the server assumes (so we never test with the same model we solve with). Thresholds were tuned on a *tuning* random stream; results are reported on a separate *validation* stream.

## Results (simulation only)

See [`RESULTS.md`](RESULTS.md) for the full tables, generated by `scripts/validate.py`.

All quakes below come from a **validation** random stream that was never used to choose any threshold. **These numbers describe our simulation, not real earthquakes.**

| Measure (200 hidden quakes, K = 10) | Result | Target set in advance |
|---|---|---|
| Median location error | 1.6 km | ≤ 3 km |
| 90 % of quakes located within | 3.2 km | ≤ 8 km |
| Quakes inside the phone network that got no alert | 0 % | ≤ 2 % |
| Places told "you have time" that had none | 0.5 % | ≤ 1 % |
| Truth inside the 95 % error circle | 94 % | 85–99 % |
| False alerts in 20 simulated hours of noise | 0 | 0 |
| Median time from quake start to alert | 5.9 s | (no target) |

**What the slider does** (100 hidden quakes each): K = 4 alerts after a median 5.8 s with 1.9 km error; K = 40 alerts after 8.3 s with 0.95 km error. Waiting for more reports buys accuracy with warning time.

**Where it struggles:** with only a tenth of phones online, 12.5 % of quakes inside the network got no alert; with phones only in towns (no countryside phones), 73 % got no alert and the alerts that were sent had a median error of 7.3 km. The validation stream was run three times during development; the history is disclosed in `RESULTS.md`.

## Limitations

- **Everything is simulated:** invented towns, simulated phones, a uniform crust, straight-line waves, a single point source, one moderate earthquake. See [`docs/ASSUMPTIONS.md`](docs/ASSUMPTIONS.md).
- **No magnitude estimate.** It is genuinely hard; the real system underestimated the 2023 Türkiye M7.8 earthquake.
- **Sparse or one-sided phone networks are hard.** With phones only in towns (no countryside phones), many quakes get no alert and some alerts are wrong; see the "Towns only" row in `RESULTS.md`.
- **Accuracy numbers describe this simulation only**, not real earthquakes or phones.
- The data-wall tests guard against mistakes; they are not a security sandbox.

## Project layout

```
outrun/
  sim/          model.py (waves), rng.py (seeds), world.py (region, phones, hidden quake),
                reports.py (phone reports + per-cell phone counts)
  server/       config.py, messages.py, prefilter.py, locator.py, silence.py,
                decide.py (main loop + alert rule), warn.py
  evaluation/   metrics.py (compare with truth after a run; blind tests; false alarms)
  web/          app.py (Flask routes), api.py (glue), static/ (the page: index.html, style.css, app.js),
                browser/ (bridge.js + worker.js: run the same Python in the browser with Pyodide)
scripts/        validate.py (blind validation -> RESULTS.md), build_web.py (browser-only website)
tests/          automated tests (pytest)
docs/           ASSUMPTIONS.md, AI_USE.md, INTERVIEW_GUIDE.md
```

## More

- [`docs/ASSUMPTIONS.md`](docs/ASSUMPTIONS.md): every assumed value and limitation
- [`docs/AI_USE.md`](docs/AI_USE.md): how we used AI tools
- [`docs/INTERVIEW_GUIDE.md`](docs/INTERVIEW_GUIDE.md): plain-language explanation of every part

## Licence

MIT: see [`LICENSE`](LICENSE).

## Sources

- R. M. Allen et al., "Global earthquake detection and warning using Android phones", *Science* 389, 254 (2025): https://rallen.berkeley.edu/pub/2025AllenBarski/AllenEtAl-AndroidEarthquakeAlerts-Science-2025.pdf
- Harvard EPS Q&A on smartphone earthquake alerts (2026): https://eps.harvard.edu/app/uploads/2026/07/260715-Mostafa-QA-for-EPS-website_SMM.pdf
