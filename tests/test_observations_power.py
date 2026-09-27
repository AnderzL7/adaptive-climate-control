"""Checks for delayed readings, contextual weights, humidity, and peak vetoes."""

from math import isclose

from observations import Estimate, PeerChange, estimate_delayed, relative_humidity_pct, vapor_pressure_hpa, weighted_estimate
from power import HeaterRequest, select_heaters


def test_peer_trend_projects_lagging_sensor_but_caps_drift():
    estimated = estimate_delayed(20, 3600, (PeerChange(3),), max_drift_per_hour=1, baseline_uncertainty=0.1, drift_uncertainty_per_hour=0.2)
    assert estimated.value == 21
    assert estimated.inferred
    held = estimate_delayed(20, 3600, (), max_drift_per_hour=1, baseline_uncertainty=0.1, drift_uncertainty_per_hour=0.2)
    assert held.value == 20
    assert not held.inferred


def test_context_weights_remain_but_uncertain_sensor_contributes_less():
    sources = {"pc": Estimate(24, 3600, 1, True), "tv": Estimate(21, 0, 0.1, False)}
    value, weights = weighted_estimate(sources, {"pc": 0.5, "tv": 0.225}, uncertainty_scale=0.5)
    assert weights["pc"] < weights["tv"]
    assert 21 < value < 24


def test_relative_humidity_falls_when_same_moisture_is_warmed():
    vapor = vapor_pressure_hpa(20, 65)
    assert isclose(relative_humidity_pct(20, vapor), 65)
    assert relative_humidity_pct(22, vapor) < 65


def test_peak_veto_and_priority_are_hard_constraints():
    heaters = (
        HeaterRequest("stove", 1500, 800, 1, True, hard_off=True),
        HeaterRequest("sov", 500, 200, 2, True),
    )
    assert select_heaters(heaters, 1500) == ("sov",)
    assert select_heaters(heaters, 0) == ()
