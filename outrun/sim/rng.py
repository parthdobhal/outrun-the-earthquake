"""Reproducible random numbers for the simulation.

Every random draw in the simulation comes from a random.Random object made
here, never from Python's shared global `random` functions. That gives us:

1. Reproducibility: the same seed always produces the same world.
2. Separate streams: "tuning" seeds (used while choosing thresholds) can never
   produce the same worlds as "validation" seeds (used to report results), even
   if the seed numbers are equal.
3. Independent parts: the phones, the quake and the wave speeds each get their
   own sub-stream, so moving the earthquake does not reshuffle the phones.

How a seed is derived: we hash the text "stream:seed:part" with SHA-256 and use
the first 8 bytes as the seed for random.Random. SHA-256 gives the same answer
on every computer and every run (unlike Python's built-in hash(), which changes
between runs).
"""

import hashlib
import random

STREAMS = ("tuning", "validation", "demo")


def derive_seed(seed: int, stream: str, *parts: str) -> int:
    """Turn (seed, stream, parts...) into a 64-bit seed, deterministically."""

    if isinstance(seed, bool) or not isinstance(seed, int):
        raise TypeError("seed must be an integer")
    if seed < 0:
        raise ValueError("seed must be zero or positive")
    if stream not in STREAMS:
        raise ValueError(f"stream must be one of {STREAMS}, got {stream!r}")
    for part in parts:
        if not isinstance(part, str) or not part:
            raise ValueError("each part must be a non-empty string")

    text = ":".join([stream, str(seed), *parts])
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def make_rng(seed: int, stream: str, *parts: str) -> random.Random:
    """A private random-number generator for one stream and part."""

    return random.Random(derive_seed(seed, stream, *parts))
