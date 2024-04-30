"""Custom integration to integrate climate_heat_loss with Home Assistant.

For more details about this integration, please refer to
https://github.com/AnderzL7/climate_heat_loss
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .const import PLATFORMS, DOMAIN, STARTUP_MESSAGE


from .const import LOGGER as _LOGGER


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Handle removal of an entry."""
    if unloaded := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
    return unloaded


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup(hass, entry)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the platforms."""
    _LOGGER.info(STARTUP_MESSAGE)

    # TODO: Implement

    return True
