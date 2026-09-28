"""Read-only forecast sensors for comparison with the current controller."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from math import isfinite

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .const import DOMAIN, MODEL_VERSION
from .model import Snapshot, forecast
from .power import coverage_adjusted_power

SCAN_INTERVAL = timedelta(minutes=5)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Add one temperature forecast entity per configured room."""
    runtime = hass.data[DOMAIN]
    runtime["entities"] = [
        ShadowForecastSensor(hass, runtime, room) for room in runtime["active"][1]["rooms"]
    ]
    async_add_entities(runtime["entities"], update_before_add=True)


def _number(hass: HomeAssistant, entity_id: str) -> float | None:
    state = hass.states.get(entity_id)
    if state is None:
        return None
    try:
        value = float(state.state)
    except (TypeError, ValueError):
        return None
    return value if isfinite(value) else None


def _age_minutes(hass: HomeAssistant, entity_id: str, now: datetime) -> float | None:
    """Report HA's last state report age, which may differ from device age."""
    state = hass.states.get(entity_id)
    if state is None:
        return None
    reported = getattr(state, "last_reported", None) or state.last_updated
    return max(0.0, (now - reported).total_seconds() / 60)


def _opening_fraction(hass: HomeAssistant, entity_id: str) -> float | None:
    state = hass.states.get(entity_id)
    if state is None:
        return None
    return {"Closed": 0.0, "20%": 0.2, "40%": 0.4, "60%": 0.6,
            "80%": 0.8, "Open": 1.0}.get(state.state)


class ShadowForecastSensor(SensorEntity):
    """Expose a model prediction without any heater service calls."""

    _attr_should_poll = True
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(self, hass: HomeAssistant, runtime: dict, room: str) -> None:
        """Bind a room forecast to the shared house model."""
        self.hass = hass
        self._runtime = runtime
        self._room = room
        minutes = runtime["active"][1]["horizon_minutes"]
        self._attr_name = f"Adaptive climate {room} {minutes}m forecast"
        self._attr_unique_id = f"adaptive_climate_control_{room}_forecast_{minutes}m"
        self._attr_native_value = None
        self._attr_available = False
        self._attr_extra_state_attributes = {"model_version": MODEL_VERSION, "shadow_only": True}

    async def async_update(self) -> None:
        """Take a current HA snapshot and forecast all rooms together."""
        house, settings = self._runtime["active"]
        outside = _number(self.hass, settings["outside_entity"])
        temps = {
            room: _number(self.hass, data["temperature_entity"])
            for room, data in settings["rooms"].items()
        }
        boundaries = {
            name: _number(self.hass, entity_id)
            for name, entity_id in settings["boundaries"].items()
        }
        heater_settings = {
            data["name"]: _number(self.hass, data["setpoint_entity"])
            for data in settings["setpoint_heaters"]
        }
        opening_fractions = {
            data["name"]: _opening_fraction(self.hass, data["position_entity"])
            for data in settings["air_paths"]
        }
        if outside is None or any(
            value is None for value in (*temps.values(), *boundaries.values(),
                                        *heater_settings.values(), *opening_fractions.values())
        ):
            self._attr_available = False
            return
        emitters = {}
        stored = {}
        recent_estimates = {}
        for emitter in house.emitters:
            room_data = settings["rooms"][emitter.zone]
            input_entity = room_data.get("heating_power_entity")
            recent_entity = room_data.get("recent_heating_power_entity")
            input_w = _number(self.hass, input_entity) if input_entity else 0.0
            recent_w = _number(self.hass, recent_entity) if recent_entity else 0.0
            if input_w is None:
                self._attr_available = False
                return
            recent_state = self.hass.states.get(recent_entity) if recent_entity else None
            try:
                coverage = float(recent_state.attributes["age_coverage_ratio"]) if recent_state else None
            except (KeyError, TypeError, ValueError):
                coverage = None
            emitters[emitter.name] = max(0.0, input_w)
            recent_estimates[emitter.name] = coverage_adjusted_power(input_w, recent_w, coverage)
            stored[emitter.name] = recent_estimates[emitter.name] * emitter.release_time_s
        snapshot = Snapshot(
            temperatures_c=temps,
            outside_c=outside,
            boundary_temperatures_c=boundaries,
            emitter_stored_j=stored,
            emitter_input_w=emitters,
            heater_setpoints_c=heater_settings,
            opening_fractions=opening_fractions,
        )
        result = forecast(house, snapshot, settings["horizon_minutes"] * 60)
        source_ids = [settings["outside_entity"], *settings["boundaries"].values()]
        source_ids.extend(data["setpoint_entity"] for data in settings["setpoint_heaters"])
        source_ids.extend(data["position_entity"] for data in settings["air_paths"])
        for data in settings["rooms"].values():
            source_ids.append(data["temperature_entity"])
            source_ids.extend(
                data[key] for key in ("heating_power_entity", "recent_heating_power_entity") if key in data
            )
        now = datetime.now(UTC)
        input_age = {
            entity_id: round(age, 1)
            for entity_id in dict.fromkeys(source_ids)
            if (age := _age_minutes(self.hass, entity_id, now)) is not None
        }
        self._attr_native_value = round(result.temperatures_c[self._room], 3)
        self._attr_available = True
        self._attr_extra_state_attributes = {
            "model_version": MODEL_VERSION,
            "model_reload_generation": self._runtime["generation"],
            "shadow_only": True,
            "horizon_minutes": settings["horizon_minutes"],
            "starting_temperature_c": temps[self._room],
            "boundary_temperatures_c": boundaries,
            "heater_setpoints_c": heater_settings,
            "opening_fractions": opening_fractions,
            "initial_air_path_w": round(result.initial_air_path_w[self._room], 2),
            "recent_heater_power_estimate_w": {
                name: round(value, 2) for name, value in recent_estimates.items()
            },
            "ha_input_age_minutes": input_age,
            "ha_inputs_over_45_minutes": [entity_id for entity_id, age in input_age.items() if age > 45],
            "initial_conduction_w": round(result.initial_conduction_w[self._room], 2),
            "emitter_release_w": round(sum(
                result.initial_emitter_release_w[emitter.name]
                for emitter in house.emitters if emitter.zone == self._room
            ), 2),
            "setpoint_proxy_gain_w": round(sum(
                result.initial_setpoint_proxy_gain_w[heater.name]
                for heater in house.setpoint_heaters if heater.zone == self._room
            ), 2),
        }
