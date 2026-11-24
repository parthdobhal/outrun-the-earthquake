"""Warning server: pre-filter, locator, silent-phones check, alert decision, warnings.

The server works from plain data alone: phone reports (cell and detection time)
and the number of active phones per cell. It never receives the ground truth.

RULE: modules in this package may import only the standard library, numpy and
other modules inside outrun.server. They must never import outrun.sim or
outrun.evaluation. tests/test_data_wall.py checks this statically (it reads
import statements), and tests/test_server.py replays a run from JSON to check
the result depends only on that plain data. These catch mistakes but are not a
sandbox, so code review still matters.
"""
