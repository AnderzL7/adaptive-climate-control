"""Behavioral checks for shadow comfort and future heater decisions."""

from dataclasses import replace

import pytest

from comfort import apparent_temperature_c, control_temperature_c, forecast_comfort_c
from control import ControlInputs, ControlSettings, decide


def test_humidity_and_local_airflow_affect_comfort():
    assert control_temperature_c(22, 70) > control_temperature_c(22, 50)
    assert control_temperature_c(22, 50, 0.5) < control_temperature_c(22, 50, 0)
    assert apparent_temperature_c(22, 50) == pytest.approx(22.345, abs=0.03)
    current, future = forecast_comfort_c(22, 23, 60)
    assert future > current
    assert future - current == pytest.approx(1)


def test_dynamic_comfort_limit_respects_minimum_on_time_and_absolute_limit_does_not():
    inputs = ControlInputs(23, 22, 22, True, 120, emitter_temperature_c=24.6,
                           comfort_limit_c=24.5, absolute_limit_c=25.5)
    assert decide(inputs).reason == "minimum_on_time"
    assert decide(replace(inputs, seconds_in_state=900)).reason == "comfort_emitter_limit"
    assert not decide(replace(inputs, emitter_temperature_c=25.5)).heater_on
    assert decide(replace(inputs, emitter_temperature_c=25.5)).reason == "absolute_emitter_limit"


def test_minimum_off_time_and_optional_limits():
    inputs = ControlInputs(23, 21, 21, False, 400)
    assert decide(inputs).reason == "minimum_off_time"
    assert decide(replace(inputs, seconds_in_state=900)).heater_on
    assert decide(replace(inputs, seconds_in_state=900), ControlSettings(min_off_s=1200)).reason == "minimum_off_time"


def test_missing_required_safety_measurement_fails_off_and_power_veto_is_immediate():
    inputs = ControlInputs(23, 21, 21, True, 20, absolute_limit_required=True)
    assert decide(inputs).reason == "absolute_limit_unavailable"
    assert decide(replace(inputs, emitter_temperature_c=23, absolute_limit_c=25.5,
                          power_peak_veto=True)).reason == "power_peak_veto"
    assert decide(replace(inputs, emitter_temperature_c=None, absolute_limit_c=25.5)).reason == "emitter_temperature_unavailable"


def test_humidity_request_does_not_override_limit_or_overshoot_bound():
    inputs = ControlInputs(23, 23, 23, False, 1000, humidity_heat_request=True)
    assert decide(inputs).reason == "humidity_heat_request"
    assert decide(replace(inputs, current_comfort_c=24)).heater_on is False
    assert decide(replace(inputs, emitter_temperature_c=24.5,
                          comfort_limit_c=24.5)).reason == "comfort_emitter_limit"
