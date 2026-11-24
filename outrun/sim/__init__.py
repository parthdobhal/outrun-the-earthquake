"""Simulated world: phones, the hidden earthquake, wave travel and phone reports.

This package OWNS and GENERATES the hidden ground truth (earthquake location,
depth, origin time, true wave speeds, true phone positions and clock errors).
What it hands to the server, as plain data only, is:
  - phone reports (grid cell and detection time; reports.py), and
  - the number of active phones in each grid cell (reports.active_phone_counts).
Neither contains the ground truth.
"""
