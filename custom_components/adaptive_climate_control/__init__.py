"""Set up shadow-only Adaptive Climate Control from domain-scoped YAML."""

from __future__ import annotations

import asyncio
from math import isfinite

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv, discovery
from homeassistant.helpers.reload import async_integration_yaml_config
from homeassistant.helpers.service import async_register_admin_service
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN
from .model import AirPath, Emitter, House, SetpointHeatProxy, Surface


ROOM_SCHEMA = vol.Schema(
    {
        vol.Required("temperature_entity"): cv.entity_id,
        vol.Required("capacity_j_k"): vol.All(vol.Coerce(float), vol.Range(min=1)),
        vol.Optional("heating_power_entity"): cv.entity_id,
        vol.Optional("recent_heating_power_entity"): cv.entity_id,
        vol.Optional("humidity_entity"): cv.entity_id,
        vol.Optional("indoor_air_speed_entity"): cv.entity_id,
    }
)


def _numeric_source(value: float | str) -> float | str:
    """Accept a literal, entity ID, or HA template; resolve it at update time."""
    if isinstance(value, (int, float)):
        if not isfinite(float(value)):
            raise vol.Invalid("Numeric source must be finite")
        return float(value)
    if isinstance(value, str):
        if "{{" in value or "{%" in value:
            cv.template(value)  # Validate syntax without rendering.
            return value
        try:
            return float(value)
        except ValueError:
            return cv.entity_id(value)
    raise vol.Invalid("Expected number, entity ID, or template")


CONTROL_SCHEMA = vol.Schema(
    {
        vol.Required("target"): _numeric_source,
        vol.Required("heater_entity"): cv.entity_id,
        vol.Required("last_on_entity"): cv.entity_id,
        vol.Required("last_off_entity"): cv.entity_id,
        vol.Required("emitter_name"): cv.string,
        vol.Optional("comfort_limit"): _numeric_source,
        vol.Optional("absolute_limit"): _numeric_source,
        vol.Optional("power_peak_veto"): _numeric_source,
        vol.Optional("humidity_heat_request"): _numeric_source,
        vol.Optional("min_on_s", default=900): vol.All(vol.Coerce(float), vol.Range(min=0)),
        vol.Optional("min_off_s", default=900): vol.All(vol.Coerce(float), vol.Range(min=0)),
        vol.Optional("cold_tolerance_c", default=0.3): vol.All(vol.Coerce(float), vol.Range(min=0)),
        vol.Optional("hot_tolerance_c", default=0.3): vol.All(vol.Coerce(float), vol.Range(min=0)),
        vol.Optional("humidity_max_overshoot_c", default=0.5): vol.All(vol.Coerce(float), vol.Range(min=0)),
    }
)
SURFACE_SCHEMA = vol.Schema(
    {
        vol.Required("name"): cv.string,
        vol.Required("zone_a"): cv.string,
        vol.Required("zone_b"): cv.string,
        vol.Required("area_m2"): vol.All(vol.Coerce(float), vol.Range(min=0)),
        vol.Required("u_w_m2k"): vol.All(vol.Coerce(float), vol.Range(min=0)),
    }
)
AIR_PATH_SCHEMA = vol.Schema(
    {
        vol.Required("name"): cv.string,
        vol.Required("zone_a"): cv.string,
        vol.Required("zone_b"): cv.string,
        vol.Required("position_entity"): cv.entity_id,
        vol.Required("closed_conductance_w_k"): vol.All(vol.Coerce(float), vol.Range(min=0)),
        vol.Required("open_conductance_w_k"): vol.All(vol.Coerce(float), vol.Range(min=0)),
    }
)
EMITTER_SCHEMA = vol.Schema(
    {
        vol.Required("name"): cv.string,
        vol.Required("zone"): cv.string,
        vol.Required("release_time_s"): vol.All(vol.Coerce(float), vol.Range(min=1)),
        vol.Optional("temperature_entity"): cv.entity_id,
        vol.Optional("thermal_capacity_j_k"): vol.All(vol.Coerce(float), vol.Range(min=1)),
    }
)
SETPOINT_HEATER_SCHEMA = vol.Schema(
    {
        vol.Required("name"): cv.string,
        vol.Required("zone"): cv.string,
        vol.Required("setpoint_entity"): cv.entity_id,
        vol.Required("effective_conductance_w_k"): vol.All(vol.Coerce(float), vol.Range(min=0)),
    }
)
BOUNDARY_SCHEMA = vol.Schema({cv.string: cv.entity_id})
DOMAIN_SCHEMA = vol.Schema(
    {
        vol.Required("outside_entity"): cv.entity_id,
        vol.Required("rooms"): vol.Schema({cv.string: ROOM_SCHEMA}),
        vol.Optional("surfaces", default=list): [SURFACE_SCHEMA],
        vol.Optional("air_paths", default=list): [AIR_PATH_SCHEMA],
        vol.Optional("emitters", default=list): [EMITTER_SCHEMA],
        vol.Optional("shadow_controls", default=dict): vol.Schema({cv.string: CONTROL_SCHEMA}),
        vol.Optional("setpoint_heaters", default=list): [SETPOINT_HEATER_SCHEMA],
        vol.Optional("boundaries", default=dict): BOUNDARY_SCHEMA,
        vol.Optional("horizon_minutes", default=30): vol.All(vol.Coerce(int), vol.Range(min=1, max=240)),
    }
)
CONFIG_SCHEMA = vol.Schema({vol.Optional(DOMAIN): DOMAIN_SCHEMA}, extra=vol.ALLOW_EXTRA)


def _build_house(settings: ConfigType) -> House:
    """Validate a complete model before making it visible to forecast sensors."""
    house = House(
        capacity_j_k={name: room["capacity_j_k"] for name, room in settings["rooms"].items()},
        surfaces=tuple(Surface(**surface) for surface in settings["surfaces"]),
        air_paths=tuple(AirPath(**{key: value for key, value in path.items() if key != "position_entity"})
                        for path in settings["air_paths"]),
        emitters=tuple(Emitter(**{key: value for key, value in emitter.items()
                                 if key != "temperature_entity"}) for emitter in settings["emitters"]),
        boundary_names=tuple(settings["boundaries"]),
        setpoint_heaters=tuple(
            SetpointHeatProxy(
                name=heater["name"],
                zone=heater["zone"],
                effective_conductance_w_k=heater["effective_conductance_w_k"],
            )
            for heater in settings["setpoint_heaters"]
        ),
    )
    house.validate()
    for room, control in settings["shadow_controls"].items():
        if room not in settings["rooms"]:
            raise ValueError(f"Unknown shadow control room {room!r}")
        if not any(emitter["name"] == control["emitter_name"] and emitter["zone"] == room
                   for emitter in settings["emitters"]):
            raise ValueError(f"Unknown shadow control emitter for {room!r}")
    return house


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Build a shadow model and register sensors plus a YAML settings reload."""
    if DOMAIN not in config:
        return True
    settings = config[DOMAIN]
    house = _build_house(settings)
    runtime = {
        "active": (house, settings),
        "entities": [],
        "generation": 0,
        "reload_lock": asyncio.Lock(),
    }
    hass.data[DOMAIN] = runtime

    async def async_reload_model(_: ServiceCall) -> None:
        """Swap validated YAML settings without unloading Python or sensors."""
        async with runtime["reload_lock"]:
            reloaded = await async_integration_yaml_config(hass, DOMAIN, raise_on_failure=True)
            if reloaded is None or DOMAIN not in reloaded:
                raise HomeAssistantError("Adaptive climate YAML is missing; previous model remains active")
            try:
                candidate = DOMAIN_SCHEMA(reloaded[DOMAIN])
                candidate_house = _build_house(candidate)
            except (vol.Invalid, ValueError) as err:
                raise HomeAssistantError(f"Invalid adaptive climate model; previous model remains active: {err}") from err

            _, previous = runtime["active"]
            if set(candidate["rooms"]) != set(previous["rooms"]):
                raise HomeAssistantError("Changing forecast rooms requires a Core restart; previous model remains active")
            if candidate["horizon_minutes"] != previous["horizon_minutes"]:
                raise HomeAssistantError("Changing forecast horizon requires a Core restart; previous model remains active")

            runtime["active"] = (candidate_house, candidate)
            runtime["generation"] += 1
            for entity in runtime["entities"]:
                if entity.entity_id is not None and entity.enabled:
                    await entity.async_update_ha_state(force_refresh=True)

    async_register_admin_service(hass, DOMAIN, "reload", async_reload_model, vol.Schema({}))
    hass.async_create_task(discovery.async_load_platform(hass, "sensor", DOMAIN, {}, config))
    return True
