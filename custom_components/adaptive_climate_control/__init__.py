"""Set up shadow-only Adaptive Climate Control from domain-scoped YAML."""

from __future__ import annotations

import asyncio

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv, discovery
from homeassistant.helpers.reload import async_integration_yaml_config
from homeassistant.helpers.service import async_register_admin_service
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN
from .model import Emitter, House, SetpointHeatProxy, Surface


ROOM_SCHEMA = vol.Schema(
    {
        vol.Required("temperature_entity"): cv.entity_id,
        vol.Required("capacity_j_k"): vol.All(vol.Coerce(float), vol.Range(min=1)),
        vol.Optional("heating_power_entity"): cv.entity_id,
        vol.Optional("recent_heating_power_entity"): cv.entity_id,
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
EMITTER_SCHEMA = vol.Schema(
    {
        vol.Required("name"): cv.string,
        vol.Required("zone"): cv.string,
        vol.Required("release_time_s"): vol.All(vol.Coerce(float), vol.Range(min=1)),
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
        vol.Optional("emitters", default=list): [EMITTER_SCHEMA],
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
        emitters=tuple(Emitter(**emitter) for emitter in settings["emitters"]),
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
