"""Read-only forecast sensors for comparison with the current controller."""

from __future__ import annotations

from datetime import timedelta
from math import isfinite

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .const import DOMAIN, MODEL_VERSION
from .model import Snapshot, forecast

SCAN_INTERVAL = timedelta(minutes=5)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Add one temperature forecast entity per configured room."""
    runtime = hass.data[DOMAIN]
    async_add_entities(
        [ShadowForecastSensor(hass, runtime, room) for room in runtime["settings"]["rooms"]],
        update_before_add=True,
    )


def _number(hass: HomeAssistant, entity_id: str) -> float | None:
    state = hass.states.get(entity_id)
    if state is None:
        return None
    try:
        value = float(state.state)
    except (TypeError, ValueError):
        return None
    return value if isfinite(value) else None


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
        minutes = runtime["settings"]["horizon_minutes"]
        self._attr_name = f"Adaptive climate {room} {minutes}m forecast"
        self._attr_unique_id = f"adaptive_climate_control_{room}_forecast_{minutes}m"
        self._attr_native_value = None
        self._attr_available = False
        self._attr_extra_state_attributes = {"model_version": MODEL_VERSION, "shadow_only": True}

    async def async_update(self) -> None:
        """Take a current HA snapshot and forecast all rooms together."""
        house = self._runtime["house"]
        settings = self._runtime["settings"]
        outside = _number(self.hass, settings["outside_entity"])
        temps = {
            room: _number(self.hass, data["temperature_entity"])
            for room, data in settings["rooms"].items()
        }
        boundaries = {
            name: _number(self.hass, entity_id)
            for name, entity_id in settings["boundaries"].items()
        }
        if outside is None or any(value is None for value in (*temps.values(), *boundaries.values())):
            self._attr_available = False
            return
        emitters = {}
        stored = {}
        for emitter in house.emitters:
            room_data = settings["rooms"][emitter.zone]
            input_entity = room_data.get("heating_power_entity")
            recent_entity = room_data.get("recent_heating_power_entity")
            input_w = _number(self.hass, input_entity) if input_entity else 0.0
            recent_w = _number(self.hass, recent_entity) if recent_entity else 0.0
            if input_w is None or recent_w is None:
                self._attr_available = False
                return
            emitters[emitter.name] = max(0.0, input_w)
            stored[emitter.name] = max(0.0, recent_w) * emitter.release_time_s
        snapshot = Snapshot(
            temperatures_c=temps,
            outside_c=outside,
            boundary_temperatures_c=boundaries,
            emitter_stored_j=stored,
            emitter_input_w=emitters,
        )
        result = forecast(house, snapshot, settings["horizon_minutes"] * 60)
        self._attr_native_value = round(result.temperatures_c[self._room], 3)
        self._attr_available = True
        self._attr_extra_state_attributes = {
            "model_version": MODEL_VERSION,
            "shadow_only": True,
            "horizon_minutes": settings["horizon_minutes"],
            "starting_temperature_c": temps[self._room],
            "initial_conduction_w": round(result.initial_conduction_w[self._room], 2),
            "emitter_release_w": round(sum(
                result.initial_emitter_release_w[emitter.name]
                for emitter in house.emitters if emitter.zone == self._room
            ), 2),
        }
