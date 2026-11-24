"""Outrun the Earthquake: an educational SIMULATION of smartphone-based
earthquake early warning.

This is not a real warning system and not Google's software.

Package layout (one-way data flow):

    sim/         owns and generates the hidden ground truth (the earthquake,
                 true phone positions and clocks) and produces phone reports
    server/      the warning server; receives reports only, and must never
                 import sim/ or evaluation/
    evaluation/  may receive the ground truth only AFTER a simulation run,
                 to compare it with the server's estimate
    web/         Flask app and browser interface

The import rule for server/ is checked by tests/test_data_wall.py. That is a
static check that catches mistakes; it is not a security sandbox.
"""

__version__ = "1.1.0"
