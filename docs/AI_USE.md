# How AI was used in this project

We are a team of two school students. We used AI assistants heavily, and we want to be clear about how.

## What the AI did

- **Claude (Anthropic)** helped us choose and refine the project idea, wrote most of the code and tests, wrote the first drafts of the documentation, and ran the tests and validation in its own environment while building each milestone.
- Claude also redesigned the website's look (version 1.1) and built the browser-only web version: `outrun/web/browser/` and `scripts/build_web.py` run our unchanged Python code inside the browser with Pyodide, so the demo can be opened from a link without installing anything.
- **ChatGPT (OpenAI)** acted as an independent reviewer. We sent each milestone to it and asked for problems; several of its review points led to real fixes (for example, a gap in the data-wall checker, overflow handling in the earthquake model, and slow phone placement).

## What we did

- We set the requirements for every milestone (including honesty rules: no hard-coded results, clear simulation labels, the server must never see the hidden truth).
- We ran the full test suite on our own computers after each milestone and only moved on when it passed.
- We asked for changes when something was unclear, too complex, or not honest enough, and decided which ideas to keep.

## Things that went wrong and were fixed

Being honest about mistakes is part of the work. During development, testing caught:

- A locator that started its least-squares fit from all reports, so three false reports dragged one estimate 67 km away.
- Estimates flying thousands of km away when all early reports came from one small area.
- Confident but wrong early alerts (6 of 100 tuning quakes), fixed with the "silent phones" check.
- A 95 % error circle that only covered the truth 81 % of the time, fixed by adding a model-error term.
- Validation runs that revealed two more weaknesses (wrong alerts when phones are only in towns, then too many missed quakes in sparse networks). Each fix was chosen on the tuning stream and validation was re-run; all three runs are disclosed in RESULTS.md.

Each fix has a test that fails if the problem returns.

## Our responsibility

The judges will interview us about our own code. Using AI does not change that: we are responsible for being able to explain every file, every formula and every design choice in this project.
