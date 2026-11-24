"""Tests for outrun/sim/rng.py: reproducible, separated random streams."""

import random

import pytest

from outrun.sim.rng import STREAMS, derive_seed, make_rng


def draws(rng, n=5):
    return [rng.random() for _ in range(n)]


def test_same_inputs_give_identical_sequences():
    assert draws(make_rng(42, "demo", "phones")) == draws(make_rng(42, "demo", "phones"))


def test_different_seeds_give_different_sequences():
    assert draws(make_rng(1, "demo", "phones")) != draws(make_rng(2, "demo", "phones"))


def test_tuning_and_validation_streams_differ_for_the_same_seed():
    a = draws(make_rng(7, "tuning", "quake"))
    b = draws(make_rng(7, "validation", "quake"))
    assert a != b


def test_different_parts_give_different_sequences():
    assert draws(make_rng(7, "demo", "phones")) != draws(make_rng(7, "demo", "quake"))


def test_derived_seed_matches_independent_sha256():
    # Expected value computed outside Python with the command:
    #   printf 'demo:0:phones' | sha256sum   -> first 16 hex digits 0a7bcd3b69372b0d
    # so the seed is identical on every computer and every run.
    # (Python's built-in hash() changes between runs and would fail this.)
    assert derive_seed(0, "demo", "phones") == 755423017566677773


def test_every_stream_and_part_combination_is_distinct():
    seeds = {derive_seed(5, s, p) for s in STREAMS for p in ("phones", "quake", "speeds")}
    assert len(seeds) == len(STREAMS) * 3


def test_make_rng_does_not_touch_global_random_state():
    random.seed(123)
    before = random.getstate()
    rng = make_rng(9, "demo", "phones")
    draws(rng, 100)
    assert random.getstate() == before


@pytest.mark.parametrize("bad", ["1", 1.5, None, True])
def test_seed_must_be_an_integer(bad):
    with pytest.raises(TypeError):
        derive_seed(bad, "demo")


def test_seed_must_not_be_negative():
    with pytest.raises(ValueError):
        derive_seed(-1, "demo")


@pytest.mark.parametrize("bad", ["", "test", "Demo", None])
def test_stream_must_be_known(bad):
    with pytest.raises(ValueError):
        derive_seed(1, bad)


@pytest.mark.parametrize("bad", ["", 5, None])
def test_parts_must_be_non_empty_strings(bad):
    with pytest.raises(ValueError):
        derive_seed(1, "demo", bad)


def test_large_seed_is_accepted():
    assert isinstance(derive_seed(10**30, "validation", "quake"), int)
