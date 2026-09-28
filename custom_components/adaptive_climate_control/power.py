"""Pure shedding decisions; physical actuation is owned by the HA adapter."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class HeaterRequest:
    """One heater's demand and non-negotiable off state."""

    name: str
    rated_w: float
    forecast_demand_w: float
    comfort_gap_c: float
    requested: bool
    hard_off: bool = False


def select_heaters(
    requests: tuple[HeaterRequest, ...],
    available_w: float,
    *,
    comfort_weight_w_per_c: float = 500.0,
) -> tuple[str, ...]:
    """Give limited peak capacity to the heaters with greatest current need.

    A hard-off flag always wins. This first ranking is deliberately explicit and
    configurable; it is not a replacement for the existing peak controller until
    its decisions have been compared in shadow mode.
    """
    if not isfinite(available_w) or available_w < 0:
        raise ValueError("Invalid available power")
    if not isfinite(comfort_weight_w_per_c) or comfort_weight_w_per_c < 0:
        raise ValueError("Invalid comfort weight")
    eligible = []
    for heater in requests:
        if not all(isfinite(v) for v in (
            heater.rated_w, heater.forecast_demand_w, heater.comfort_gap_c
        )) or heater.rated_w <= 0:
            raise ValueError(f"Invalid heater {heater.name!r}")
        if heater.requested and not heater.hard_off:
            need = max(0.0, heater.forecast_demand_w) + (
                comfort_weight_w_per_c * max(0.0, heater.comfort_gap_c)
            )
            eligible.append((need / heater.rated_w, heater.name, heater))
    eligible.sort(key=lambda row: (-row[0], row[1]))
    selected = []
    remaining = available_w
    for _, name, heater in eligible:
        if heater.rated_w <= remaining:
            selected.append(name)
            remaining -= heater.rated_w
    return tuple(selected)


def coverage_adjusted_power(current_w: float, average_w: float | None, coverage: float | None) -> float:
    """Blend a partial rolling mean with the current reading for missing time.

    HA's statistics average_step spans the samples it has seen, which may cover
    much less than the requested hour immediately after a reload or a quiet
    source. The rest of that hour uses the current reading as a conservative
    holding estimate until the statistics window is filled. An older average
    without coverage metadata is used as supplied for compatibility.
    """
    if not isfinite(current_w):
        raise ValueError("Non-finite current power")
    current = max(0.0, current_w)
    if average_w is None or not isfinite(average_w):
        return current
    if coverage is None or not isfinite(coverage):
        return max(0.0, average_w)
    covered = min(1.0, max(0.0, coverage))
    return covered * max(0.0, average_w) + (1.0 - covered) * current
