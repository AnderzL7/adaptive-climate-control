"""Estimate delayed room measurements without replacing raw sensor states."""

from __future__ import annotations

from dataclasses import dataclass
from math import exp, isfinite
from collections.abc import Mapping


@dataclass(frozen=True)
class PeerChange:
    """A peer's change over the target sensor's missing interval."""

    delta: float
    correlation: float = 1.0
    confidence: float = 1.0


@dataclass(frozen=True)
class Estimate:
    """A current estimate with an uncertainty used for contextual weighting."""

    value: float
    age_s: float
    uncertainty: float
    inferred: bool


def estimate_delayed(
    last_value: float,
    age_s: float,
    peer_changes: tuple[PeerChange, ...],
    *,
    max_drift_per_hour: float,
    baseline_uncertainty: float,
    drift_uncertainty_per_hour: float,
    fresh_for_s: float = 300.0,
) -> Estimate:
    """Project a stale value using robustly capped, confidence-weighted peer changes.

    Each peer delta must cover the interval from the target's last trustworthy
    measurement to now. If no peer is trustworthy, the last value is retained
    with growing uncertainty rather than extrapolated indefinitely.
    """
    if not isfinite(last_value) or not isfinite(age_s) or age_s < 0:
        raise ValueError("Invalid source measurement")
    if any(value < 0 or not isfinite(value) for value in (
        max_drift_per_hour, baseline_uncertainty, drift_uncertainty_per_hour, fresh_for_s
    )):
        raise ValueError("Invalid estimation limit")
    uncertainty = baseline_uncertainty + drift_uncertainty_per_hour * age_s / 3600.0
    if age_s <= fresh_for_s:
        return Estimate(last_value, age_s, uncertainty, False)
    usable = [
        peer for peer in peer_changes
        if isfinite(peer.delta)
        and isfinite(peer.correlation)
        and isfinite(peer.confidence)
        and peer.confidence > 0
        and abs(peer.correlation) <= 2
    ]
    if not usable:
        return Estimate(last_value, age_s, uncertainty, False)
    weight_sum = sum(peer.confidence for peer in usable)
    delta = sum(peer.delta * peer.correlation * peer.confidence for peer in usable) / weight_sum
    cap = max_drift_per_hour * age_s / 3600.0
    delta = max(-cap, min(cap, delta))
    disagreement = sum(
        peer.confidence * abs(peer.delta * peer.correlation - delta) for peer in usable
    ) / weight_sum
    return Estimate(last_value + delta, age_s, uncertainty + disagreement, True)


def weighted_estimate(
    sources: Mapping[str, Estimate],
    context_weights: Mapping[str, float],
    *,
    uncertainty_scale: float,
) -> tuple[float, Mapping[str, float]]:
    """Combine current source estimates, returning value and normalized weights."""
    if uncertainty_scale <= 0 or not isfinite(uncertainty_scale):
        raise ValueError("Invalid uncertainty scale")
    weights = {}
    for name, base_weight in context_weights.items():
        if name not in sources or not isfinite(base_weight) or base_weight <= 0:
            continue
        source = sources[name]
        if not isfinite(source.value) or not isfinite(source.uncertainty):
            continue
        weights[name] = base_weight * exp(-source.uncertainty / uncertainty_scale)
    total = sum(weights.values())
    if total <= 0:
        raise ValueError("No usable sources")
    normalized = {name: weight / total for name, weight in weights.items()}
    return sum(sources[name].value * weight for name, weight in normalized.items()), normalized


def saturation_vapor_pressure_hpa(temperature_c: float) -> float:
    """Approximate saturation vapor pressure for ordinary indoor temperatures."""
    if not isfinite(temperature_c) or not -40 <= temperature_c <= 60:
        raise ValueError("Temperature outside supported range")
    return 6.112 * exp(17.62 * temperature_c / (243.12 + temperature_c))


def vapor_pressure_hpa(temperature_c: float, relative_humidity_pct: float) -> float:
    """Calculate actual vapor pressure from a paired temperature/RH reading."""
    if not isfinite(relative_humidity_pct) or not 0 <= relative_humidity_pct <= 100:
        raise ValueError("Invalid relative humidity")
    return saturation_vapor_pressure_hpa(temperature_c) * relative_humidity_pct / 100.0


def relative_humidity_pct(temperature_c: float, vapor_hpa: float) -> float:
    """Convert predicted moisture and temperature back to RH."""
    if not isfinite(vapor_hpa) or vapor_hpa < 0:
        raise ValueError("Invalid vapor pressure")
    return max(0.0, min(100.0, 100.0 * vapor_hpa / saturation_vapor_pressure_hpa(temperature_c)))
