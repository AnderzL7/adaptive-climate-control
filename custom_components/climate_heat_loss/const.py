"""Constants for climate_heat_loss."""

from logging import Logger, getLogger
from typing import Final

from homeassistant.const import Platform

LOGGER: Logger = getLogger(__package__)

NAME: Final = "Climate with heat loss calculation"
DOMAIN: Final = "climate_heat_loss"
VERSION: Final = "0.0.0"
ISSUE_URL: Final = "https://github.com/AnderzL7/climate_heat_loss/issues"

STARTUP_MESSAGE: Final = f"""
-------------------------------------------------------------------
{NAME}
Version: {VERSION}
This is a custom integration!
If you have ANY issues with this you need to open an issue here:
{ISSUE_URL}
-------------------------------------------------------------------
"""

PLATFORMS: list[Platform] = [
    Platform.CLIMATE,
]

# Default Climate configuration keys
CONF_HEATER: Final = "heater"
CONF_SENSOR: Final = "target_sensor"
CONF_MIN_TEMP: Final = "min_temp"
CONF_MAX_TEMP: Final = "max_temp"
CONF_TARGET_TEMP: Final = "target_temp"
CONF_AC_MODE: Final = "ac_mode"
CONF_MIN_DUR: Final = "min_cycle_duration"
CONF_COLD_TOLERANCE: Final = "cold_tolerance"
CONF_HOT_TOLERANCE: Final = "hot_tolerance"
CONF_KEEP_ALIVE: Final = "keep_alive"
CONF_INITIAL_HVAC_MODE: Final = "initial_hvac_mode"
CONF_PRECISION: Final = "precision"
CONF_TEMP_STEP: Final = "target_temp_step"

# Power peak control configuration keys
CONF_POWER_LIMIT: Final = "power_limit"
CONF_POWER_INPUT: Final = "power_input"
CONF_WANTED_POWER_LIMIT: Final = "wanted_power_limit"
CONF_ABSOLUTE_POWER_LIMIT: Final = "absolute_power_limit"
CONF_POWER_LIMIT_DELAY: Final = "delay"
# CONF_POWER_LIMIT_NOTIFICATION: Final = "_power_limit_notification"
CONF_POWER_LIMIT_SCALE_FACTORS: Final = "power_limit_scale_factors"

# Heat loss calculation configuration keys
CONF_HEAT_LOSS: Final = "heat_loss"
CONF_HEAT_LOSS_ENERGY_LOSS: Final = "energy_loss"
CONF_HEAT_LOSS_ENERGY_INPUT: Final = "energy_input"
CONF_HEAT_LOSS_DELAY: Final = "delay"
# CONF_HEAT_LOSS_PERIOD: Final = "period"
# CONF_HEAT_LOSS_CONTRIBUTION: Final = "contribution"
CONF_HEAT_LOSS_SCALE_FACTORS: Final = "energy_store_scale_factors"

# Defaults
CLIMATE_DEFAULT_NAME: Final = "Climate with heat loss calculation"
CLIMATE_DEFAULT_TOLERANCE: Final = 0.3
HEAT_LOSS_DEFAULT_SCALE = 1.0
