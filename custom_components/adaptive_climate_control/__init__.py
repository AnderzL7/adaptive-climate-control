"""Set up shadow-only Adaptive Climate Control from domain-scoped YAML."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, discovery
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN
from .model import Emitter, House, Surface


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
BOUNDARY_SCHEMA = vol.Schema({cv.string: cv.entity_id})
DOMAIN_SCHEMA = vol.Schema(
    {
        vol.Required("outside_entity"): cv.entity_id,
        vol.Required("rooms"): vol.Schema({cv.string: ROOM_SCHEMA}),
        vol.Optional("surfaces", default=list): [SURFACE_SCHEMA],
        vol.Optional("emitters", default=list): [EMITTER_SCHEMA],
        vol.Optional("boundaries", default=dict): BOUNDARY_SCHEMA,
        vol.Optional("horizon_minutes", default=30): vol.All(vol.Coerce(int), vol.Range(min=1, max=240)),
    }
)
CONFIG_SCHEMA = vol.Schema({vol.Optional(DOMAIN): DOMAIN_SCHEMA}, extra=vol.ALLOW_EXTRA)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Build a model and register prediction sensors; never control an actuator."""
    if DOMAIN not in config:
        return True
    settings = config[DOMAIN]
    house = House(
        capacity_j_k={name: room["capacity_j_k"] for name, room in settings["rooms"].items()},
        surfaces=tuple(Surface(**surface) for surface in settings["surfaces"]),
        emitters=tuple(Emitter(**emitter) for emitter in settings["emitters"]),
        boundary_names=tuple(settings["boundaries"]),
    )
    house.validate()
    hass.data[DOMAIN] = {"house": house, "settings": settings}
    hass.async_create_task(discovery.async_load_platform(hass, "sensor", DOMAIN, {}, config))
    return True
