"""Indoor perceived-temperature proxy, separate from the dry-bulb heat balance.

The apparent-temperature equation matches the existing temperature_feels_like
sensor. Its 0.35/0.60 blend matches the current Gaming/Sov climate templates.
Air speed means local indoor air speed, never unscaled outdoor weather wind.
"""

from __future__ import annotations

from math import exp, isfinite

def apparent_temperature_c(temperature_c: float, humidity_pct: float, air_speed_m_s: float = 0.0) -> float:
    """Return the existing apparent-temperature formula with explicit SI air speed."""
    if not all(isfinite(value) for value in (temperature_c, humidity_pct, air_speed_m_s)):
        raise ValueError("Non-finite comfort input")
    if not -40 <= temperature_c <= 60 or not 0 <= humidity_pct <= 100 or air_speed_m_s < 0:
        raise ValueError("Comfort input outside supported range")
    vapor_hpa = humidity_pct * 0.06105 * exp(17.27 * temperature_c / (237.7 + temperature_c))
    return temperature_c + 0.348 * vapor_hpa - 0.7 * air_speed_m_s - 4.25


def control_temperature_c(temperature_c: float, humidity_pct: float, air_speed_m_s: float = 0.0) -> float:
    """Match the existing humidity-sensitive blend used by Gaming and Sov."""
    apparent = apparent_temperature_c(temperature_c, humidity_pct, air_speed_m_s)
    weight = 0.6 if humidity_pct > 65 else 0.35
    return apparent * weight + temperature_c * (1 - weight)


def forecast_comfort_c(current_c: float, forecast_c: float, humidity_pct: float,
                       air_speed_m_s: float = 0.0) -> tuple[float, float]:
    """Return current and future perceived temperatures at constant moisture.

    This baseline conserves vapor pressure over the forecast interval. A later
    moisture-balance model can replace that assumption when humidity trends,
    ventilation and cooking/shower loads are measured well enough.
    """
    if not 0 <= humidity_pct <= 100:
        raise ValueError("Invalid relative humidity")
    vapor_hpa = humidity_pct * 0.06105 * exp(17.27 * current_c / (237.7 + current_c))
    future_saturation_hpa = 100 * 0.06105 * exp(17.27 * forecast_c / (237.7 + forecast_c))
    future_humidity = max(0.0, min(100.0, 100.0 * vapor_hpa / future_saturation_hpa))
    return (
        control_temperature_c(current_c, humidity_pct, air_speed_m_s),
        control_temperature_c(forecast_c, future_humidity, air_speed_m_s),
    )
