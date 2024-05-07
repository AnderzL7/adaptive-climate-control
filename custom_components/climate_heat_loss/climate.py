"""Implmentation of the climate entity of Climate with heat loss calculation.

For more details please refer to the documentation at:
https://github.com/AnderzL7/climate_heat_loss
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import math
from typing import Any

import voluptuous as vol

from homeassistant.components.climate import (
    ATTR_PRESET_MODE,
    PLATFORM_SCHEMA,
    PRESET_ACTIVITY,
    PRESET_AWAY,
    PRESET_COMFORT,
    PRESET_ECO,
    PRESET_HOME,
    PRESET_NONE,
    PRESET_SLEEP,
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_TEMPERATURE,
    CONF_NAME,
    CONF_UNIQUE_ID,
    EVENT_HOMEASSISTANT_START,
    PRECISION_HALVES,
    PRECISION_TENTHS,
    PRECISION_WHOLE,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfTemperature,
)
from homeassistant.core import (
    DOMAIN as HA_DOMAIN,
    CoreState,
    Event,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.exceptions import ConditionError
from homeassistant.helpers import condition
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import (
    EventStateChangedData,
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.reload import async_setup_reload_service
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

# Custom imports
from homeassistant.helpers.template import Template
from enum import StrEnum

from .const import (
    CONF_HEATER,
    CONF_SENSOR,
    CONF_MIN_TEMP,
    CONF_MAX_TEMP,
    CONF_TARGET_TEMP,
    CONF_AC_MODE,
    CONF_MIN_DUR,
    CONF_COLD_TOLERANCE,
    CONF_HOT_TOLERANCE,
    CONF_KEEP_ALIVE,
    CONF_INITIAL_HVAC_MODE,
    CONF_PRECISION,
    CONF_TEMP_STEP,
    CONF_POWER_LIMIT,
    CONF_POWER_INPUT,
    CONF_WANTED_POWER_LIMIT,
    CONF_ABSOLUTE_POWER_LIMIT,
    CONF_POWER_LIMIT_DELAY,
    # CONF_POWER_LIMIT_NOTIFICATION,
    CONF_POWER_LIMIT_SCALE_FACTORS,
    CONF_HEAT_LOSS,
    CONF_HEAT_LOSS_ENERGY_LOSS,
    CONF_HEAT_LOSS_ENERGY_INPUT,
    CONF_HEAT_LOSS_DELAY,
    # CONF_HEAT_LOSS_PERIOD,
    # CONF_HEAT_LOSS_CONTRIBUTION,
    CONF_HEAT_LOSS_SCALE_FACTORS,
)

from .const import (
    CLIMATE_DEFAULT_NAME,
    CLIMATE_DEFAULT_TOLERANCE,
    HEAT_LOSS_DEFAULT_SCALE,
)

from .const import PLATFORMS, DOMAIN, LOGGER as _LOGGER


class ClimateActionState(StrEnum):
    """Enum that represents climate action states.

    For example used to force the heater to turn off when surpassing a power limit.
    """

    ON = "turn_on"
    OFF = "turn_off"
    IDLE = "idle"


CONF_PRESETS = {
    p: f"{p}_temp"
    for p in (
        PRESET_AWAY,
        PRESET_COMFORT,
        PRESET_ECO,
        PRESET_HOME,
        PRESET_SLEEP,
        PRESET_ACTIVITY,
    )
}


def validate_minute_key(key):
    """Validate the minute key."""
    # Ensure the key is an integer or a digit string and within the allowed range
    if isinstance(key, str) and key.isdigit():
        key = int(key)
    if not isinstance(key, int) or not 0 <= key <= 59:
        raise vol.Invalid("Key must be an integer between 0 and 59")
    return str(key)


class PowerLimitScaleKey(StrEnum):
    """The key for the power limit scale factor."""

    TURN_OFF = "turn_off"
    TURN_ON = "turn_on"
    TURN_OFF_DELAY = "turn_off_delay"
    TURN_ON_DELAY = "turn_on_delay"


def validate_power_limit_scale_key(key):
    """Validate the power limit scale key."""
    # Ensure the key is a string
    if not isinstance(key, str):
        raise vol.Invalid("Key must be a string")
    if key not in [
        PowerLimitScaleKey.TURN_OFF,
        PowerLimitScaleKey.TURN_ON,
        PowerLimitScaleKey.TURN_OFF_DELAY,
        PowerLimitScaleKey.TURN_ON_DELAY,
    ]:
        raise vol.Invalid(
            f"Key must be either '{PowerLimitScaleKey.TURN_OFF}', '{PowerLimitScaleKey.TURN_ON}', '{PowerLimitScaleKey.TURN_OFF_DELAY}' or '{PowerLimitScaleKey.TURN_ON_DELAY}'"
        )
    return key


power_scale_factor_schema = cv.schema_with_slug_keys(
    value_schema=cv.positive_float, slug_validator=validate_power_limit_scale_key
)


def require_power_limits_if_sensor_defined(obj):
    """Validate that either CONF_WANTED_POWER_LIMIT or CONF_ABSOLUTE_POWER_LIMIT is set if CONF_POWER_SENSOR is set."""

    def validate(obj):
        if (
            obj.get(CONF_WANTED_POWER_LIMIT) is None
            and obj.get(CONF_ABSOLUTE_POWER_LIMIT) is None
        ):
            raise vol.Invalid(
                f"Either {CONF_WANTED_POWER_LIMIT} or {CONF_ABSOLUTE_POWER_LIMIT} must be set when {CONF_POWER_INPUT} is present"
            )
        return obj

    return validate(obj)


def check_all_or_non(keys):
    """Validate that all or none of the keys are set."""

    def validate(obj):
        # Count how many of the specified keys are present and not None
        present_count = sum(1 for key in keys if obj.get(key) is not None)
        # Check if the count is neither all nor none
        if present_count not in (0, len(keys)):
            raise vol.Invalid(
                f"All or none of the following keys must be set: {', '.join(keys)}"
            )
        return obj

    return validate


def check_main_secondary(main_keys, secondary_keys):
    """Validate that secondary keys are set only if main keys are set."""

    def validate(obj):
        # If any of the main keys are set, return the object
        for key in main_keys:
            if obj.get(key) is not None:
                return obj

        # If none of the main keys are set, check if any of the secondary keys are set
        secondary_keys_present = False
        for key in secondary_keys:
            if obj.get(key) is not None:
                secondary_keys_present = True
                break

        # If secondary keys are set, raise an error as the main keys are not set
        if secondary_keys_present:
            raise vol.Invalid(
                f"Secondary keys {', '.join(secondary_keys)} must be set only if main keys {', '.join(main_keys)} are set"
            )

        return obj

    return validate


def validate_heat_loss_scale_factors(key):
    """Validate the heat loss scale keys."""
    # Ensure the key is a string
    if not isinstance(key, str):
        raise vol.Invalid("Key must be a string")
    if key not in ["hot_tolerance", "current_temp", "cold_tolerance"]:
        raise vol.Invalid(
            "Key must be either 'hot_tolerance', 'current_temp' or 'cold_tolerance'"
        )
    return key


PLATFORM_SCHEMA = (
    PLATFORM_SCHEMA.extend(
        {
            vol.Required(CONF_HEATER): cv.entity_id,
            vol.Required(CONF_SENSOR): cv.entity_id,
            vol.Optional(CONF_AC_MODE): cv.boolean,
            vol.Optional(CONF_MAX_TEMP): vol.Coerce(float),
            vol.Optional(CONF_MIN_DUR): cv.positive_time_period,
            vol.Optional(CONF_MIN_TEMP): vol.Coerce(float),
            vol.Optional(CONF_NAME, default=CLIMATE_DEFAULT_NAME): cv.string,
            vol.Optional(
                CONF_COLD_TOLERANCE, default=CLIMATE_DEFAULT_TOLERANCE
            ): vol.Coerce(float),
            vol.Optional(
                CONF_HOT_TOLERANCE, default=CLIMATE_DEFAULT_TOLERANCE
            ): vol.Coerce(float),
            vol.Optional(CONF_TARGET_TEMP): vol.Coerce(float),
            vol.Optional(CONF_KEEP_ALIVE): cv.positive_time_period,
            vol.Optional(CONF_INITIAL_HVAC_MODE): vol.In(
                [HVACMode.COOL, HVACMode.HEAT, HVACMode.OFF]
            ),
            vol.Optional(CONF_PRECISION): vol.In(
                [PRECISION_TENTHS, PRECISION_HALVES, PRECISION_WHOLE]
            ),
            vol.Optional(CONF_TEMP_STEP): vol.In(
                [PRECISION_TENTHS, PRECISION_HALVES, PRECISION_WHOLE]
            ),
            vol.Optional(CONF_UNIQUE_ID): cv.string,
        },
    )
    .extend({vol.Optional(v): vol.Coerce(float) for (k, v) in CONF_PRESETS.items()})
    .extend(
        {
            vol.Optional(CONF_HEAT_LOSS): vol.All(
                {
                    vol.Required(CONF_HEAT_LOSS_ENERGY_LOSS): vol.Any(
                        cv.entity_id, vol.Coerce(float), cv.template
                    ),
                    vol.Required(CONF_HEAT_LOSS_ENERGY_INPUT): vol.Any(
                        cv.entity_id, vol.Coerce(float), cv.template
                    ),
                    # vol.Optional(CONF_HEAT_LOSS_PERIOD): cv.positive_time_period,
                    # vol.Optional(CONF_HEAT_LOSS_CONTRIBUTION): vol.Any(
                    #     cv.entity_id, vol.Coerce(float), cv.template
                    # ),
                    vol.Optional(
                        CONF_HEAT_LOSS_DELAY, default=timedelta(minutes=5)
                    ): cv.positive_time_period,
                    vol.Optional(
                        CONF_HEAT_LOSS_SCALE_FACTORS
                    ): cv.schema_with_slug_keys(
                        value_schema=cv.positive_float,
                        slug_validator=validate_heat_loss_scale_factors,
                    ),
                },
                check_main_secondary(
                    [CONF_HEAT_LOSS_ENERGY_LOSS, CONF_HEAT_LOSS_ENERGY_INPUT],
                    [
                        CONF_HEAT_LOSS_SCALE_FACTORS,
                        CONF_HEAT_LOSS_DELAY,
                        # CONF_HEAT_LOSS_PERIOD,
                        # CONF_HEAT_LOSS_CONTRIBUTION,
                    ],
                ),
            ),
        }
    )
    .extend(
        {
            vol.Optional(CONF_POWER_LIMIT): vol.All(
                {
                    vol.Required(CONF_POWER_INPUT): vol.Any(cv.entity_id, cv.template),
                    vol.Optional(CONF_WANTED_POWER_LIMIT): vol.Any(
                        cv.positive_float, cv.entity_id, cv.template
                    ),
                    # vol.Optional(CONF_POWER_LIMIT_PERIOD): cv.positive_time_period,
                    vol.Optional(CONF_ABSOLUTE_POWER_LIMIT): vol.Any(
                        cv.positive_float, cv.entity_id, cv.template
                    ),
                    vol.Optional(
                        CONF_POWER_LIMIT_DELAY, default=timedelta(minutes=2)
                    ): cv.positive_time_period,
                    # vol.Optional(CONF_POWER_LIMIT_NOTIFICATION): cv.SERVICE_SCHEMA,
                    vol.Optional(
                        CONF_POWER_LIMIT_SCALE_FACTORS, default=HEAT_LOSS_DEFAULT_SCALE
                    ): vol.Any(
                        cv.schema_with_slug_keys(
                            value_schema=power_scale_factor_schema,
                            slug_validator=validate_minute_key,
                        ),
                        # vol.Any(cv.positive_float, power_scale_factor_schema),
                    ),
                },
                require_power_limits_if_sensor_defined,
            )
        }
    )
)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the Climate with heat loss platform."""

    await async_setup_reload_service(hass, DOMAIN, PLATFORMS)

    name: str = config[CONF_NAME]
    heater_entity_id: str = config[CONF_HEATER]
    sensor_entity_id: str = config[CONF_SENSOR]
    min_temp: float | None = config.get(CONF_MIN_TEMP)
    max_temp: float | None = config.get(CONF_MAX_TEMP)
    target_temp: float | None = config.get(CONF_TARGET_TEMP)
    ac_mode: bool | None = config.get(CONF_AC_MODE)
    min_cycle_duration: timedelta | None = config.get(CONF_MIN_DUR)
    cold_tolerance: float = config[CONF_COLD_TOLERANCE]
    hot_tolerance: float = config[CONF_HOT_TOLERANCE]
    keep_alive: timedelta | None = config.get(CONF_KEEP_ALIVE)
    initial_hvac_mode: HVACMode | None = config.get(CONF_INITIAL_HVAC_MODE)
    presets: dict[str, float] = {
        key: config[value] for key, value in CONF_PRESETS.items() if value in config
    }
    precision: float | None = config.get(CONF_PRECISION)
    target_temperature_step: float | None = config.get(CONF_TEMP_STEP)
    unit = hass.config.units.temperature_unit
    unique_id: str | None = config.get(CONF_UNIQUE_ID)

    power_limit: dict | None = config.get(CONF_POWER_LIMIT)
    if isinstance(power_limit, dict):
        power_input: str | Template | None = power_limit.get(CONF_POWER_INPUT)
        wanted_power_limit: float | str | Template | None = power_limit.get(
            CONF_WANTED_POWER_LIMIT
        )
        absolute_power_limit: float | str | Template | None = power_limit.get(
            CONF_ABSOLUTE_POWER_LIMIT
        )
        power_limit_delay: timedelta = power_limit.get(CONF_POWER_LIMIT_DELAY)
        # power_limit_notification: dict | None = config.get(CONF_POWER_LIMIT_NOTIFICATION)
        power_limit_scale_factors: dict[str, dict[str, float]] | None = power_limit.get(
            CONF_POWER_LIMIT_SCALE_FACTORS
        )

    heat_loss: dict | None = config.get(CONF_HEAT_LOSS)
    if isinstance(heat_loss, dict):
        heat_loss_energy_loss: float | str | Template | None = heat_loss.get(
            CONF_HEAT_LOSS_ENERGY_LOSS
        )
        heat_loss_delay: timedelta = heat_loss.get(CONF_HEAT_LOSS_DELAY)
        heat_loss_energy_input: float | str | Template | None = heat_loss.get(
            CONF_HEAT_LOSS_ENERGY_INPUT
        )
        heat_loss_energy_store_scale_factors: dict[str, float] | None = heat_loss.get(
            CONF_HEAT_LOSS_SCALE_FACTORS
        )
        # heat_loss_period: timedelta | None = heat_loss.get(CONF_HEAT_LOSS_PERIOD)
        # heat_loss_contribution: float | str | Template | None = heat_loss.get(
        #     CONF_HEAT_LOSS_CONTRIBUTION
        # )

    async_add_entities(
        [
            ClimateHeatLoss(
                name,
                heater_entity_id,
                sensor_entity_id,
                min_temp,
                max_temp,
                target_temp,
                ac_mode,
                min_cycle_duration,
                cold_tolerance,
                hot_tolerance,
                keep_alive,
                initial_hvac_mode,
                presets,
                precision,
                target_temperature_step,
                unit,
                unique_id,
                power_input,
                wanted_power_limit,
                absolute_power_limit,
                power_limit_delay,
                power_limit_scale_factors,
                # power_limit_notification,
                heat_loss_energy_loss,
                heat_loss_energy_input,
                heat_loss_delay,
                heat_loss_energy_store_scale_factors,
                # heat_loss_period,
                # heat_loss_contribution,
            )
        ]
    )


class ClimateHeatLoss(ClimateEntity, RestoreEntity):
    """Representation of a Climate with heat loss calcualtion climate entity."""

    _attr_should_poll = False
    _enable_turn_on_off_backwards_compatibility = False

    def __init__(
        self,
        name: str,
        heater_entity_id: str,
        sensor_entity_id: str,
        min_temp: float | None,
        max_temp: float | None,
        target_temp: float | None,
        ac_mode: bool | None,
        min_cycle_duration: timedelta | None,
        cold_tolerance: float,
        hot_tolerance: float,
        keep_alive: timedelta | None,
        initial_hvac_mode: HVACMode | None,
        presets: dict[str, float],
        precision: float | None,
        target_temperature_step: float | None,
        unit: UnitOfTemperature,
        unique_id: str | None,
        power_input: str | Template | None,
        wanted_power_limit: float | str | Template | None,
        absolute_power_limit: float | str | Template | None,
        power_limit_delay: timedelta,
        power_limit_scale_factors: dict[str, dict[str, float]] | None,
        # power_limit_notification: IDK,
        heat_loss_energy_loss: float | str | Template | None,
        heat_loss_energy_input: float | str | Template | None,
        heat_loss_delay: timedelta,
        heat_loss_energy_store_scale_factors: dict[str, float] | None,
        # heat_loss_period: timedelta | None,
        # heat_loss_contribution: float | str | Template | None,
    ) -> None:
        """Initialize the climate entity."""
        self._attr_name = name
        self.heater_entity_id = heater_entity_id
        self.sensor_entity_id = sensor_entity_id
        self.ac_mode = ac_mode
        self.min_cycle_duration = min_cycle_duration
        self._cold_tolerance = cold_tolerance
        self._hot_tolerance = hot_tolerance
        self._keep_alive = keep_alive
        self._hvac_mode = initial_hvac_mode
        self._saved_target_temp = target_temp or next(iter(presets.values()), None)
        self._temp_precision = precision
        self._temp_target_temperature_step = target_temperature_step
        if self.ac_mode:
            self._attr_hvac_modes = [HVACMode.COOL, HVACMode.OFF]
        else:
            self._attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
        self._active = False
        self._cur_temp: float | None = None
        self._temp_lock = asyncio.Lock()
        self._min_temp = min_temp
        self._max_temp = max_temp
        self._attr_preset_mode = PRESET_NONE
        self._target_temp: float | None = target_temp
        self._attr_temperature_unit = unit
        self._attr_unique_id = unique_id
        self._attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.TURN_OFF
            | ClimateEntityFeature.TURN_ON
        )
        if len(presets):
            self._attr_supported_features |= ClimateEntityFeature.PRESET_MODE
            self._attr_preset_modes = [PRESET_NONE, *presets.keys()]
        else:
            self._attr_preset_modes = [PRESET_NONE]
        self._presets = presets

        self._power_limit_heater_state: ClimateActionState | None = None
        self._heat_loss_heater_state: ClimateActionState | None = None

        self._wanted_power_limit_off_since: datetime | None = None
        self._wanted_power_limit_idle_since: datetime | None = None
        self._absolute_power_limit_off_since: datetime | None = None
        self._absolute_power_limit_idle_since: datetime | None = None
        self._heat_loss_too_hot_since: datetime | None = None
        self._heat_loss_too_cold_since: datetime | None = None
        self._heat_loss_idle_since: datetime | None = None
        self._heat_loss_current_state_since: datetime | None = None

        self._power_input = power_input
        self._wanted_power_limit = wanted_power_limit
        self._absolute_power_limit = absolute_power_limit
        self._power_limit_delay = power_limit_delay
        self._power_limit_scale_factors = power_limit_scale_factors

        self._heat_loss_energy_loss = heat_loss_energy_loss
        self._heat_loss_energy_input = heat_loss_energy_input
        # self._heat_loss_delay = timedelta(minutes=5)
        self._heat_loss_delay = heat_loss_delay
        self._heat_loss_energy_store_scale_factors = (
            heat_loss_energy_store_scale_factors
        )
        # self._heat_loss_period = heat_loss_period

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added."""
        await super().async_added_to_hass()

        # Add listener
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, [self.sensor_entity_id], self._async_sensor_changed
            )
        )
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, [self.heater_entity_id], self._async_switch_changed
            )
        )

        if self._keep_alive:
            self.async_on_remove(
                async_track_time_interval(
                    self.hass, self._async_control_heating, self._keep_alive
                )
            )

        if self._heat_loss_energy_loss is not None or self._power_input is not None:
            self.async_on_remove(
                async_track_time_interval(
                    self.hass,
                    self._async_check_heat_loss_power_limit,
                    timedelta(seconds=30),
                )
            )

        @callback
        def _async_startup(_: Event | None = None) -> None:
            """Init on startup."""
            sensor_state = self.hass.states.get(self.sensor_entity_id)
            if sensor_state and sensor_state.state not in (
                STATE_UNAVAILABLE,
                STATE_UNKNOWN,
            ):
                self._async_update_temp(sensor_state)
                self.async_write_ha_state()
            switch_state = self.hass.states.get(self.heater_entity_id)
            if switch_state and switch_state.state not in (
                STATE_UNAVAILABLE,
                STATE_UNKNOWN,
            ):
                self.hass.async_create_task(
                    self._check_switch_initial_state(), eager_start=True
                )

        if self.hass.state is CoreState.running:
            _async_startup()
        else:
            self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_START, _async_startup)

        # Check If we have an old state
        if (old_state := await self.async_get_last_state()) is not None:
            # If we have no initial temperature, restore
            if self._target_temp is None:
                # If we have a previously saved temperature
                if old_state.attributes.get(ATTR_TEMPERATURE) is None:
                    if self.ac_mode:
                        self._target_temp = self.max_temp
                    else:
                        self._target_temp = self.min_temp
                    _LOGGER.warning(
                        "Undefined target temperature, falling back to %s",
                        self._target_temp,
                    )
                else:
                    self._target_temp = float(old_state.attributes[ATTR_TEMPERATURE])
            if (
                self.preset_modes
                and old_state.attributes.get(ATTR_PRESET_MODE) in self.preset_modes
            ):
                self._attr_preset_mode = old_state.attributes.get(ATTR_PRESET_MODE)
            if not self._hvac_mode and old_state.state:
                self._hvac_mode = HVACMode(old_state.state)

        else:
            # No previous state, try and restore defaults
            if self._target_temp is None:
                if self.ac_mode:
                    self._target_temp = self.max_temp
                else:
                    self._target_temp = self.min_temp
            _LOGGER.warning(
                "No previously saved temperature, setting to %s", self._target_temp
            )

        # Set default state to off
        if not self._hvac_mode:
            self._hvac_mode = HVACMode.OFF

    @property
    def precision(self) -> float:
        """Return the precision of the system."""
        if self._temp_precision is not None:
            return self._temp_precision
        return super().precision

    @property
    def target_temperature_step(self) -> float:
        """Return the supported step of target temperature."""
        if self._temp_target_temperature_step is not None:
            return self._temp_target_temperature_step
        # if a target_temperature_step is not defined, fallback to equal the precision
        return self.precision

    @property
    def current_temperature(self) -> float | None:
        """Return the sensor temperature."""
        return self._cur_temp

    @property
    def hvac_mode(self) -> HVACMode | None:
        """Return current operation."""
        return self._hvac_mode

    @property
    def hvac_action(self) -> HVACAction:
        """Return the current running hvac operation if supported.

        Need to be one of CURRENT_HVAC_*.
        """
        if self._hvac_mode == HVACMode.OFF:
            return HVACAction.OFF
        if not self._is_device_active:
            return HVACAction.IDLE
        if self.ac_mode:
            return HVACAction.COOLING
        return HVACAction.HEATING

    @property
    def target_temperature(self) -> float | None:
        """Return the temperature we try to reach."""
        return self._target_temp

    @property
    def power_limit_action_state(self) -> ClimateActionState | None:
        """Return the current power limit action state."""
        return self._power_limit_heater_state

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set hvac mode."""
        if hvac_mode == HVACMode.HEAT:
            self._hvac_mode = HVACMode.HEAT
            await self._async_control_heating(force=True)
        elif hvac_mode == HVACMode.COOL:
            self._hvac_mode = HVACMode.COOL
            await self._async_control_heating(force=True)
        elif hvac_mode == HVACMode.OFF:
            self._hvac_mode = HVACMode.OFF
            if self._is_device_active:
                await self._async_heater_turn_off()
        else:
            _LOGGER.error("Unrecognized hvac mode: %s", hvac_mode)
            return
        # Ensure we update the current operation after changing the mode
        self.async_write_ha_state()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is None:
            return
        self._target_temp = float(temperature)
        await self._async_control_heating(force=True)
        self.async_write_ha_state()

    @property
    def min_temp(self) -> float:
        """Return the minimum temperature."""
        if self._min_temp is not None:
            return self._min_temp

        # get default temp from super class
        return super().min_temp

    @property
    def max_temp(self) -> float:
        """Return the maximum temperature."""
        if self._max_temp is not None:
            return self._max_temp

        # Get default temp from super class
        return super().max_temp

    async def _async_sensor_changed(self, event: Event[EventStateChangedData]) -> None:
        """Handle temperature changes."""
        new_state = event.data["new_state"]
        if new_state is None or new_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return

        self._async_update_temp(new_state)
        await self._async_control_heating()
        self.async_write_ha_state()

    async def _check_switch_initial_state(self) -> None:
        """Prevent the device from keep running if HVACMode.OFF."""
        if self._hvac_mode == HVACMode.OFF and self._is_device_active:
            _LOGGER.warning(
                (
                    "The climate mode is OFF, but the switch device is ON. Turning off"
                    " device %s"
                ),
                self.heater_entity_id,
            )
            await self._async_heater_turn_off()

    @callback
    def _async_switch_changed(self, event: Event[EventStateChangedData]) -> None:
        """Handle heater switch state changes."""
        new_state = event.data["new_state"]
        old_state = event.data["old_state"]
        if new_state is None:
            return
        if old_state is None:
            self.hass.async_create_task(
                self._check_switch_initial_state(), eager_start=True
            )
        self.async_write_ha_state()

    @callback
    def _async_update_temp(self, state: State) -> None:
        """Update thermostat with latest state from sensor."""
        try:
            cur_temp = float(state.state)
            if not math.isfinite(cur_temp):
                raise ValueError(f"Sensor has illegal state {state.state}")
            self._cur_temp = cur_temp
        except ValueError as ex:
            _LOGGER.error("Unable to update from sensor: %s", ex)

    async def _async_check_heat_loss_power_limit(self, _=None) -> None:
        """Check if the heater should be turned off due to heat loss or power limit."""

        old_power_limit_state = self._power_limit_heater_state
        old_heat_loss_state = self._heat_loss_heater_state

        await self._async_apply_power_limit_state()
        await self._async_apply_heat_loss_state()

        if (
            self._power_limit_heater_state != old_power_limit_state
            or self._heat_loss_heater_state != old_heat_loss_state
        ):
            _LOGGER.debug(
                "Running control heating due to power limit or heat loss change. Power limit from %s to %s, heat loss from %s to %s",
                old_power_limit_state,
                self._power_limit_heater_state,
                old_heat_loss_state,
                self._heat_loss_heater_state,
            )
            await self._async_control_heating(
                skip_heat_loss=True, skip_power_limit=True
            )
        self.async_write_ha_state()

    def _get_current_lower_upper_scale_keys(self) -> tuple[int | None, int | None]:
        """Get the current lower and upper scale keys."""
        if self._power_limit_scale_factors is None:
            return None, None
        minute = datetime.now().minute

        if str(minute) in self._power_limit_scale_factors:
            return minute, None
        keys = sorted([int(k) for k in self._power_limit_scale_factors if k.isdigit()])

        lower = None
        upper = None

        for k in keys:
            if k > minute:
                upper = k
                break
            else:
                lower = k

        return lower, upper

    def _get_current_power_limit_scale_value(
        self, lower: int | None, upper: int | None, scale_key: PowerLimitScaleKey
    ) -> float:
        """Get the current power scale factor."""
        if lower is None and upper is None:
            return 1.0
        minute = datetime.now().minute

        scale_dict = self._power_limit_scale_factors

        lowerValue = None
        upperValue = None

        if (
            lower is not None
            and str(lower) in scale_dict
            and scale_key in scale_dict[str(lower)]
        ):
            lowerValue = scale_dict[str(lower)][scale_key]
        if (
            upper is not None
            and str(upper) in scale_dict
            and scale_key in scale_dict[str(upper)]
        ):
            upperValue = scale_dict[str(upper)][scale_key]

        if lowerValue is None and upperValue is None:
            return 1.0

        if lowerValue is None:
            return upperValue
        if upperValue is None:
            return lowerValue

        # Calculate the weighted average
        return (upperValue * (minute - lower) + lowerValue * (upper - minute)) / (
            upper - lower
        )

    async def _get_value_from_template_str_float(self, value: str | Template | float):
        """Get the value from a template, a string or a float and return as float."""
        if isinstance(value, Template) and value.ensure_valid:
            new_value = value.async_render()
            if not isinstance(new_value, str | int | float):
                if new_value is None:
                    return None
                _LOGGER.error(
                    "Invalid template value: %s, expected string or float", new_value
                )
                return None
        elif isinstance(value, str) and cv.entity_id(value):
            new_value = self.hass.states.get(value).state
        elif isinstance(value, float):
            new_value = value
        else:
            _LOGGER.error(
                "Invalid value: %s, expected template, string or float", value
            )
            return None

        if isinstance(new_value, str):
            if new_value.lower() in ["unavailable", "unknown"]:
                return None
            try:
                new_value = float(new_value)
            except ValueError:
                _LOGGER.error(
                    "Rendered template value is not a float string: %s", new_value
                )
                return None

        if not isinstance(new_value, float):
            new_value = float(new_value)

        return new_value

    def _get_absolute_power_limit_state(
        self,
        power_input: float,
        power_scale_factor: float,
        absolute_power_limit: float,
        delay_scale_factor: float,
    ) -> ClimateActionState | None:
        """Get the state of the absolute power limit."""
        if power_input * power_scale_factor > absolute_power_limit:
            self._absolute_power_limit_idle_since = None
            if self._absolute_power_limit_off_since is None:
                self._absolute_power_limit_off_since = datetime.now()
            elif (
                self._absolute_power_limit_off_since.timestamp()
                + (self._power_limit_delay.total_seconds() * delay_scale_factor)
                < datetime.now().timestamp()
            ):
                return ClimateActionState.OFF
        if power_input * power_scale_factor < absolute_power_limit:
            self._absolute_power_limit_off_since = None
            if self._absolute_power_limit_idle_since is None:
                self._absolute_power_limit_idle_since = datetime.now()
            elif (
                self._absolute_power_limit_idle_since.timestamp()
                + (self._power_limit_delay.total_seconds() * delay_scale_factor)
                < datetime.now().timestamp()
            ):
                return ClimateActionState.IDLE

    def _get_wanted_power_limit_state(
        self,
        power_input: float,
        power_scale_factor: float,
        wanted_power_limit: float,
        delay_scale_factor: float,
    ) -> ClimateActionState | None:
        if power_input * power_scale_factor > wanted_power_limit:
            self._wanted_power_limit_idle_since = None
            if self._wanted_power_limit_off_since is None:
                self._wanted_power_limit_off_since = datetime.now()
            elif (
                self._wanted_power_limit_off_since.timestamp()
                + (self._power_limit_delay.total_seconds() * delay_scale_factor)
                < datetime.now().timestamp()
            ):
                return ClimateActionState.OFF
        elif power_input * power_scale_factor < wanted_power_limit:
            self._wanted_power_limit_off_since = None
            if self._wanted_power_limit_idle_since is None:
                self._wanted_power_limit_idle_since = datetime.now()
            elif (
                self._wanted_power_limit_idle_since.timestamp()
                + (self._power_limit_delay.total_seconds() * delay_scale_factor)
                < datetime.now().timestamp()
            ):
                return ClimateActionState.IDLE

    async def _async_apply_power_limit_state(self) -> None:
        """Apply the power limit state."""
        if self._power_input is None or (
            self._wanted_power_limit is None and self._absolute_power_limit is None
        ):
            self._power_limit_heater_state = ClimateActionState.IDLE
            return

        if self._is_device_active:
            power_scale_key = PowerLimitScaleKey.TURN_OFF
            delay_scale_key = PowerLimitScaleKey.TURN_OFF_DELAY
        else:
            power_scale_key = PowerLimitScaleKey.TURN_ON
            delay_scale_key = PowerLimitScaleKey.TURN_ON_DELAY

        lower, upper = self._get_current_lower_upper_scale_keys()
        power_scale_factor = self._get_current_power_limit_scale_value(
            lower, upper, power_scale_key
        )
        delay_scale_factor = self._get_current_power_limit_scale_value(
            lower, upper, delay_scale_key
        )

        power_input = await self._get_value_from_template_str_float(self._power_input)

        if power_input is None:
            return

        wanted_power_state: ClimateActionState | None = None
        absolute_power_state: ClimateActionState | None = None

        if self._wanted_power_limit is not None:
            wanted_power_limit = await self._get_value_from_template_str_float(
                self._wanted_power_limit
            )
            if wanted_power_limit is not None:
                wanted_power_state = self._get_wanted_power_limit_state(
                    power_input,
                    power_scale_factor,
                    wanted_power_limit,
                    delay_scale_factor,
                )

        if self._absolute_power_limit is not None:
            absolute_power_limit = await self._get_value_from_template_str_float(
                self._absolute_power_limit
            )

            if absolute_power_limit is not None:
                absolute_power_state = self._get_absolute_power_limit_state(
                    power_input,
                    power_scale_factor,
                    absolute_power_limit,
                    delay_scale_factor,
                )

        if wanted_power_state == ClimateActionState.OFF:
            self._power_limit_heater_state = ClimateActionState.OFF
        elif absolute_power_state == ClimateActionState.OFF:
            self._power_limit_heater_state = ClimateActionState.OFF
        elif wanted_power_state in (
            ClimateActionState.IDLE,
            None,
        ) and absolute_power_state in (ClimateActionState.IDLE, None):
            self._power_limit_heater_state = ClimateActionState.IDLE

        _LOGGER.debug(
            "Power limit state: wanted_power_state=%s, absolute_power_state=%s, power_limit_heater_state=%s",
            wanted_power_state,
            absolute_power_state,
            self._power_limit_heater_state,
        )

    def get_heat_loss_scale_factor(self):
        """Calculate the scale factor based on the current temperature."""
        DEFAULT_SCALE_FACTOR = 1.0

        if self._target_temp is None or self._cur_temp is None:
            return DEFAULT_SCALE_FACTOR

        hot_tolerance_factor = (
            self._heat_loss_energy_store_scale_factors.get(
                "hot_tolerance", DEFAULT_SCALE_FACTOR
            )
            if self._heat_loss_energy_store_scale_factors is not None
            else DEFAULT_SCALE_FACTOR
        )
        current_temp_factor = (
            self._heat_loss_energy_store_scale_factors.get(
                "current_temp", DEFAULT_SCALE_FACTOR
            )
            if self._heat_loss_energy_store_scale_factors is not None
            else DEFAULT_SCALE_FACTOR
        )
        cold_tolerance_factor = (
            self._heat_loss_energy_store_scale_factors.get(
                "cold_tolerance", DEFAULT_SCALE_FACTOR
            )
            if self._heat_loss_energy_store_scale_factors is not None
            else DEFAULT_SCALE_FACTOR
        )

        if hot_tolerance_factor == current_temp_factor == cold_tolerance_factor:
            return hot_tolerance_factor

        temp_scale_lower = self._cur_temp - self._cold_tolerance
        temp_scale_middle = self._cur_temp
        temp_scale_upper = self._cur_temp + self._hot_tolerance

        # Calculate scale factor based on target temperature
        if self._target_temp <= temp_scale_lower:
            return cold_tolerance_factor
        elif self._target_temp >= temp_scale_upper:
            return hot_tolerance_factor
        elif self._target_temp == temp_scale_middle:
            return current_temp_factor
        else:
            if self._target_temp < temp_scale_middle:
                # Calculate linear interpolation between lower and middle
                fraction = (self._target_temp - temp_scale_lower) / (
                    temp_scale_middle - temp_scale_lower
                )
                return cold_tolerance_factor + fraction * (
                    current_temp_factor - cold_tolerance_factor
                )
            else:
                # Calculate linear interpolation between middle and upper
                fraction = (self._target_temp - temp_scale_middle) / (
                    temp_scale_upper - temp_scale_middle
                )
                return current_temp_factor + fraction * (
                    hot_tolerance_factor - current_temp_factor
                )

    async def _async_apply_heat_loss_state(self) -> None:
        """Apply the heat loss state."""
        if self._heat_loss_energy_loss is None or self._heat_loss_energy_input is None:
            _LOGGER.debug("Heat loss energy loss or energy input is None")
            self._heat_loss_heater_state = ClimateActionState.IDLE
            return

        old_still_valid = self._heat_loss_current_state_since is not None and (
            self._heat_loss_current_state_since.timestamp()
            + self._heat_loss_delay.total_seconds()
            > datetime.now().timestamp()
        )
        old_state = self._heat_loss_heater_state

        energy_loss = await self._get_value_from_template_str_float(
            self._heat_loss_energy_loss
        )
        energy_input = await self._get_value_from_template_str_float(
            self._heat_loss_energy_input
        )

        if energy_loss is None or energy_input is None:
            _LOGGER.debug(
                "Calculated energy loss or energy input is None. Energy loss: %s, Energy input: %s",
                energy_loss,
                energy_input,
            )
            return

        scale_factor = self.get_heat_loss_scale_factor()

        within_tolerance = (
            self._target_temp >= self._cur_temp - self._cold_tolerance
            and self._target_temp <= self._cur_temp + self._hot_tolerance
        )

        scaled_energy_input = energy_input * scale_factor

        current_state_since = (
            datetime.now().timestamp() - self._heat_loss_current_state_since.timestamp()
            if self._heat_loss_current_state_since is not None
            else None
        )

        _LOGGER.debug(
            "Energy loss: %s, Energy input: %s, Scale factor: %s, Within tolerance: %s, energy_input * scale_factor: %s",
            energy_loss,
            energy_input,
            scale_factor,
            within_tolerance,
            scaled_energy_input,
        )

        if scaled_energy_input < energy_loss and within_tolerance:
            self._heat_loss_too_hot_since = None
            self._heat_loss_idle_since = None
            too_cold_since = (
                datetime.now().timestamp() - self._heat_loss_too_cold_since.timestamp()
                if self._heat_loss_too_cold_since is not None
                else None
            )
            if self._heat_loss_too_cold_since is None:
                _LOGGER.debug("Setting heat_loss_too_cold_since to now")
                self._heat_loss_too_cold_since = datetime.now()
            elif (
                old_state != ClimateActionState.ON
                and (
                    self._heat_loss_too_cold_since.timestamp()
                    + self._heat_loss_delay.total_seconds()
                    < datetime.now().timestamp()
                )
                and not old_still_valid
            ):
                _LOGGER.debug(
                    "Setting heat_loss_state to ON. Old state: %s, old_still_valid: %s, current_state_since(seconds since): %s, heat_loss_too_cold_since(seconds since): %s",
                    old_state,
                    old_still_valid,
                    current_state_since,
                    too_cold_since,
                )
                self._heat_loss_heater_state = ClimateActionState.ON
                self._heat_loss_current_state_since = datetime.now()
            else:
                _LOGGER.debug(
                    "Not setting heat_loss_state to ON. Old state: %s, old_still_valid: %s, heat_loss_too_cold_since(seconds since): %s",
                    old_state,
                    old_still_valid,
                    datetime.now().timestamp()
                    - self._heat_loss_too_cold_since.timestamp(),
                )
        elif scaled_energy_input > energy_loss and within_tolerance:
            self._heat_loss_too_cold_since = None
            self._heat_loss_idle_since = None
            too_hot_since = (
                datetime.now().timestamp() - self._heat_loss_too_hot_since.timestamp()
                if self._heat_loss_too_hot_since is not None
                else None
            )

            if self._heat_loss_too_hot_since is None:
                _LOGGER.debug("Setting heat_loss_too_hot_since to now")
                self._heat_loss_too_hot_since = datetime.now()
            elif (
                old_state != ClimateActionState.OFF
                and (
                    self._heat_loss_too_hot_since.timestamp()
                    + self._heat_loss_delay.total_seconds()
                    < datetime.now().timestamp()
                )
                and not old_still_valid
            ):
                _LOGGER.debug(
                    "Setting heat_loss_state to OFF. Old state: %s, old_still_valid: %s, current_state_since(seconds since): %s, heat_loss_too_hot_since(seconds since): %s",
                    old_state,
                    old_still_valid,
                    current_state_since,
                    too_hot_since,
                )
                self._heat_loss_heater_state = ClimateActionState.OFF
                self._heat_loss_current_state_since = datetime.now()
            else:
                _LOGGER.debug(
                    "Not setting heat_loss_state to OFF. Old state: %s, old_still_valid: %s, heat_loss_too_hot_since(seconds since): %s",
                    old_state,
                    old_still_valid,
                    too_hot_since,
                )
        else:
            self._heat_loss_too_cold_since = None
            self._heat_loss_too_hot_since = None
            idle_since = (
                datetime.now().timestamp() - self._heat_loss_idle_since.timestamp()
                if self._heat_loss_idle_since is not None
                else None
            )

            if self._heat_loss_idle_since is None and within_tolerance:
                _LOGGER.debug("Setting heat_loss_idle_since to now")
                self._heat_loss_idle_since = datetime.now()
            elif (
                old_state != ClimateActionState.IDLE
                and not within_tolerance
                or (
                    self._heat_loss_idle_since is not None
                    and self._heat_loss_idle_since.timestamp()
                    + self._heat_loss_delay.total_seconds()
                    < datetime.now().timestamp()
                    and not old_still_valid
                )
            ):
                _LOGGER.debug(
                    "Setting heat_loss_state to IDLE. Old state: %s, old_still_valid: %s, current_state_since(seconds since): %s, heat_loss_idle_since(seconds since): %s",
                    old_state,
                    old_still_valid,
                    current_state_since,
                    idle_since,
                )
                self._heat_loss_heater_state = ClimateActionState.IDLE
                self._heat_loss_current_state_since = datetime.now()
            else:
                _LOGGER.debug(
                    "Not setting heat_loss_state to IDLE. Old state: %s, old_still_valid: %s, heat_loss_idle_since(seconds since): %s",
                    old_state,
                    old_still_valid,
                    idle_since,
                )

    async def _async_control_heating(
        self,
        time: datetime | None = None,
        force: bool = False,
        skip_power_limit: bool = False,
        skip_heat_loss: bool = False,
    ) -> None:
        """Check if we need to turn heating on or off."""
        async with self._temp_lock:
            if not self._active and None not in (
                self._cur_temp,
                self._target_temp,
            ):
                self._active = True
                _LOGGER.info(
                    (
                        "Obtained current and target temperature. "
                        "Climate with heat loss active. %s, %s"
                    ),
                    self._cur_temp,
                    self._target_temp,
                )

            if not self._active or self._hvac_mode == HVACMode.OFF:
                return

            if not skip_power_limit:
                await self._async_apply_power_limit_state()

            if not skip_heat_loss:
                await self._async_apply_heat_loss_state()

            if self._power_limit_heater_state is ClimateActionState.OFF:
                if self._is_device_active:
                    _LOGGER.info(
                        "Turning off heater %s due to power limit",
                        self.heater_entity_id,
                    )
                    await self._async_heater_turn_off()
                else:
                    _LOGGER.info(
                        "Heater %s is already off due to power limit",
                        self.heater_entity_id,
                    )
                return

            # If the `force` argument is True, we
            # ignore `min_cycle_duration`.
            # If the `time` argument is not none, we were invoked for
            # keep-alive purposes, and `min_cycle_duration` is irrelevant.
            if not force and time is None and self.min_cycle_duration:
                if self._is_device_active:
                    current_state = STATE_ON
                else:
                    current_state = HVACMode.OFF
                try:
                    long_enough = condition.state(
                        self.hass,
                        self.heater_entity_id,
                        current_state,
                        self.min_cycle_duration,
                    )
                except ConditionError:
                    long_enough = False

                if not long_enough:
                    return

            assert self._cur_temp is not None and self._target_temp is not None
            too_cold = self._target_temp >= self._cur_temp + self._cold_tolerance
            too_hot = self._cur_temp >= self._target_temp + self._hot_tolerance
            if self._is_device_active:
                if self._heat_loss_heater_state == ClimateActionState.OFF or (
                    ((self.ac_mode and too_cold) or (not self.ac_mode and too_hot))
                    and self._heat_loss_heater_state != ClimateActionState.ON
                ):
                    _LOGGER.info("Turning off heater %s", self.heater_entity_id)
                    await self._async_heater_turn_off()
                elif time is not None:
                    # The time argument is passed only in keep-alive case
                    _LOGGER.info(
                        "Keep-alive - Turning on heater heater %s",
                        self.heater_entity_id,
                    )
                    await self._async_heater_turn_on()
            elif self._heat_loss_heater_state == ClimateActionState.ON or (
                ((self.ac_mode and too_hot) or (not self.ac_mode and too_cold))
                and self._heat_loss_heater_state != ClimateActionState.OFF
            ):
                _LOGGER.info("Turning on heater %s", self.heater_entity_id)
                await self._async_heater_turn_on()
            elif time is not None:
                # The time argument is passed only in keep-alive case
                _LOGGER.info(
                    "Keep-alive - Turning off heater %s", self.heater_entity_id
                )
                await self._async_heater_turn_off()

    @property
    def _is_device_active(self) -> bool | None:
        """If the toggleable device is currently active."""
        if not self.hass.states.get(self.heater_entity_id):
            return None

        return self.hass.states.is_state(self.heater_entity_id, STATE_ON)

    async def _async_heater_turn_on(self) -> None:
        """Turn heater toggleable device on."""
        data = {ATTR_ENTITY_ID: self.heater_entity_id}
        await self.hass.services.async_call(
            HA_DOMAIN, SERVICE_TURN_ON, data, context=self._context
        )

    async def _async_heater_turn_off(self) -> None:
        """Turn heater toggleable device off."""
        data = {ATTR_ENTITY_ID: self.heater_entity_id}
        await self.hass.services.async_call(
            HA_DOMAIN, SERVICE_TURN_OFF, data, context=self._context
        )

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set new preset mode."""
        if preset_mode not in (self.preset_modes or []):
            raise ValueError(
                f"Got unsupported preset_mode {preset_mode}. Must be one of"
                f" {self.preset_modes}"
            )
        if preset_mode == self._attr_preset_mode:
            # I don't think we need to call async_write_ha_state if we didn't change the state
            return
        if preset_mode == PRESET_NONE:
            self._attr_preset_mode = PRESET_NONE
            self._target_temp = self._saved_target_temp
            await self._async_control_heating(force=True)
        else:
            if self._attr_preset_mode == PRESET_NONE:
                self._saved_target_temp = self._target_temp
            self._attr_preset_mode = preset_mode
            self._target_temp = self._presets[preset_mode]
            await self._async_control_heating(force=True)

        self.async_write_ha_state()
