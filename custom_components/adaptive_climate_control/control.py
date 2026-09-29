"""Pure, read-only-capable heating decision logic for future shadow comparison."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class ControlInputs:
    target_c: float
    current_comfort_c: float
    forecast_comfort_c: float
    heater_on: bool
    seconds_in_state: float
    emitter_temperature_c: float | None = None
    comfort_limit_c: float | None = None
    comfort_limit_required: bool = False
    absolute_limit_c: float | None = None
    absolute_limit_required: bool = False
    power_peak_veto: bool = False
    humidity_heat_request: bool = False


@dataclass(frozen=True)
class ControlSettings:
    min_on_s: float = 900.0
    min_off_s: float = 900.0
    cold_tolerance_c: float = 0.3
    hot_tolerance_c: float = 0.3
    humidity_max_overshoot_c: float = 0.5


@dataclass(frozen=True)
class Decision:
    heater_on: bool
    reason: str
    lockout_remaining_s: float = 0.0


def decide(inputs: ControlInputs, settings: ControlSettings = ControlSettings()) -> Decision:
    """Evaluate one heater without issuing any HA service call.

    Safety and power vetoes override minimum on time. The comfort limit is a
    normal control request and respects minimum on time. A configured absolute
    limit with an unavailable sensor fails off; omitted limits do nothing.
    """
    numbers = (inputs.target_c, inputs.current_comfort_c, inputs.forecast_comfort_c,
               inputs.seconds_in_state, settings.min_on_s, settings.min_off_s,
               settings.cold_tolerance_c, settings.hot_tolerance_c,
               settings.humidity_max_overshoot_c)
    if not all(isfinite(value) and value >= 0 for value in
               (inputs.seconds_in_state, settings.min_on_s, settings.min_off_s,
                settings.cold_tolerance_c, settings.hot_tolerance_c,
                settings.humidity_max_overshoot_c)) or not all(isfinite(value) for value in numbers):
        raise ValueError("Invalid control input or setting")
    for value in (inputs.emitter_temperature_c, inputs.comfort_limit_c, inputs.absolute_limit_c):
        if value is not None and not isfinite(value):
            raise ValueError("Invalid emitter temperature or limit")
    if (inputs.comfort_limit_c is not None or inputs.absolute_limit_c is not None) and inputs.emitter_temperature_c is None:
        return Decision(False, "emitter_temperature_unavailable")
    if inputs.absolute_limit_required and inputs.absolute_limit_c is None:
        return Decision(False, "absolute_limit_unavailable")
    if inputs.comfort_limit_required and inputs.comfort_limit_c is None:
        return Decision(False, "comfort_limit_unavailable")
    if inputs.power_peak_veto:
        return Decision(False, "power_peak_veto")
    if inputs.absolute_limit_c is not None and inputs.emitter_temperature_c >= inputs.absolute_limit_c:
        return Decision(False, "absolute_emitter_limit")

    if inputs.comfort_limit_c is not None and inputs.emitter_temperature_c >= inputs.comfort_limit_c:
        requested_on, reason = False, "comfort_emitter_limit"
    elif inputs.forecast_comfort_c < inputs.target_c - settings.cold_tolerance_c:
        requested_on, reason = True, "forecast_below_target"
    elif inputs.forecast_comfort_c > inputs.target_c + settings.hot_tolerance_c:
        requested_on, reason = False, "forecast_above_target"
    else:
        requested_on, reason = inputs.heater_on, "within_tolerance"
    if inputs.humidity_heat_request and (inputs.comfort_limit_c is None or inputs.emitter_temperature_c < inputs.comfort_limit_c):
        if inputs.current_comfort_c < inputs.target_c + settings.humidity_max_overshoot_c:
            requested_on, reason = True, "humidity_heat_request"

    if requested_on != inputs.heater_on:
        required = settings.min_on_s if inputs.heater_on else settings.min_off_s
        if inputs.seconds_in_state < required:
            return Decision(inputs.heater_on, "minimum_on_time" if inputs.heater_on else "minimum_off_time",
                            required - inputs.seconds_in_state)
    return Decision(requested_on, reason)
