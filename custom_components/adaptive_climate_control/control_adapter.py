"""Resolve optional HA number, entity, and template inputs for shadow control."""

from __future__ import annotations

from datetime import UTC, datetime
from math import isfinite

from homeassistant.core import HomeAssistant
from homeassistant.helpers.template import Template

from .control import ControlInputs, ControlSettings, decide


def numeric_source(hass: HomeAssistant, source: float | str | None) -> float | None:
    """Read a literal, entity state, or HA template as a finite number."""
    if source is None:
        return None
    if isinstance(source, (int, float)):
        value = float(source)
    elif "{{" in source or "{%" in source:
        try:
            value = float(Template(source, hass).async_render(parse_result=False))
        except Exception:  # HA templates can fail at render time when an input disappears.
            return None
    else:
        state = hass.states.get(source)
        if state is None:
            return None
        try:
            value = float(state.state)
        except (TypeError, ValueError):
            return None
    return value if isfinite(value) else None


def shadow_control(hass: HomeAssistant, config: dict, current_comfort_c: float,
                   forecast_comfort_c: float, emitter_temperature_c: float | None,
                   now: datetime | None = None) -> dict:
    """Evaluate the configured heater and return diagnostics only."""
    now = now or datetime.now(UTC)
    heater = hass.states.get(config["heater_entity"])
    if heater is None:
        return {"shadow_control_reason": "heater_state_unavailable"}
    action = heater.attributes.get("hvac_action")
    if action not in ("heating", "idle", "off"):
        return {"shadow_control_reason": "heater_state_unavailable"}
    heater_on = action == "heating"
    transition_entity = config["last_on_entity"] if heater_on else config["last_off_entity"]
    transition = hass.states.get(transition_entity)
    try:
        transition_epoch = float(transition.attributes["timestamp"])
    except (AttributeError, KeyError, TypeError, ValueError):
        return {"shadow_control_reason": "heater_transition_unavailable"}
    age_s = max(0.0, now.timestamp() - transition_epoch)
    target = numeric_source(hass, config["target"])
    if target is None:
        return {"shadow_control_reason": "target_unavailable"}
    comfort_limit = numeric_source(hass, config.get("comfort_limit"))
    absolute_limit = numeric_source(hass, config.get("absolute_limit"))
    veto = numeric_source(hass, config.get("power_peak_veto"))
    humidity = numeric_source(hass, config.get("humidity_heat_request"))
    if ("power_peak_veto" in config and veto is None) or ("humidity_heat_request" in config and humidity is None):
        return {"shadow_control_reason": "control_context_unavailable"}
    decision = decide(
        ControlInputs(
            target_c=target,
            current_comfort_c=current_comfort_c,
            forecast_comfort_c=forecast_comfort_c,
            heater_on=heater_on,
            seconds_in_state=age_s,
            emitter_temperature_c=emitter_temperature_c,
            comfort_limit_c=comfort_limit,
            comfort_limit_required="comfort_limit" in config,
            absolute_limit_c=absolute_limit,
            absolute_limit_required="absolute_limit" in config,
            power_peak_veto=bool(veto),
            humidity_heat_request=bool(humidity),
        ),
        ControlSettings(
            min_on_s=config["min_on_s"],
            min_off_s=config["min_off_s"],
            cold_tolerance_c=config["cold_tolerance_c"],
            hot_tolerance_c=config["hot_tolerance_c"],
            humidity_max_overshoot_c=config["humidity_max_overshoot_c"],
        ),
    )
    return {
        "shadow_heater_on": decision.heater_on,
        "shadow_control_reason": decision.reason,
        "shadow_lockout_remaining_s": round(decision.lockout_remaining_s),
        "shadow_target_c": target,
        "shadow_comfort_limit_c": comfort_limit,
        "shadow_absolute_limit_c": absolute_limit,
        "observed_heater_on": heater_on,
    }
