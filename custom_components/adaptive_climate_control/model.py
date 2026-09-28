"""Deterministic thermal and sensor calculations for Adaptive Climate Control.

This module has no Home Assistant imports so recorded snapshots can be replayed.
All temperatures are Celsius, time is seconds, energy is joules, and power is watts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import atan2, cos, degrees, hypot, isfinite, radians
from collections.abc import Mapping


@dataclass(frozen=True)
class Surface:
    """One conductive connection, counted once between its two zones."""

    name: str
    zone_a: str
    zone_b: str  # "outside" is the outdoor zone.
    area_m2: float
    u_w_m2k: float

    @property
    def conductance_w_k(self) -> float:
        """Return heat flow per kelvin across this surface."""
        return self.area_m2 * self.u_w_m2k


@dataclass(frozen=True)
class AirPath:
    """An opening whose exchange changes with its recorded position."""

    name: str
    zone_a: str
    zone_b: str
    closed_conductance_w_k: float
    open_conductance_w_k: float

    def conductance_w_k(self, fraction: float) -> float:
        return self.closed_conductance_w_k + fraction * (
            self.open_conductance_w_k - self.closed_conductance_w_k
        )


@dataclass(frozen=True)
class Emitter:
    """An emitter whose stored heat is released with a first-order lag."""

    name: str
    zone: str
    release_time_s: float


@dataclass(frozen=True)
class SetpointHeatProxy:
    """Provisional room gain from an independently controlled heater setting.

    The setting alone does not report heater activity. For floor-sensor controls,
    it is also not a measured surface or air temperature. Calibrate the effective
    conductance against observed heater power and room trends before trusting it.
    """

    name: str
    zone: str
    effective_conductance_w_k: float


@dataclass(frozen=True)
class House:
    """Geometry and effective heat capacities for the current dwelling."""

    capacity_j_k: Mapping[str, float]
    surfaces: tuple[Surface, ...] = ()
    emitters: tuple[Emitter, ...] = ()
    boundary_names: tuple[str, ...] = ()
    setpoint_heaters: tuple[SetpointHeatProxy, ...] = ()
    air_paths: tuple[AirPath, ...] = ()

    def validate(self) -> None:
        """Reject invalid geometry and capacities before forecasting."""
        if not self.capacity_j_k:
            raise ValueError("At least one room is required")
        if len(set(self.boundary_names)) != len(self.boundary_names) or any(
            not name or name == "outside" or name in self.capacity_j_k
            for name in self.boundary_names
        ):
            raise ValueError("Invalid boundary name")
        for zone, capacity in self.capacity_j_k.items():
            if not zone or zone == "outside" or not isfinite(capacity) or capacity <= 0:
                raise ValueError(f"Invalid heat capacity for {zone!r}")
        for surface in self.surfaces:
            if surface.zone_a not in self.capacity_j_k:
                raise ValueError(f"Unknown surface zone {surface.zone_a!r}")
            if surface.zone_b != "outside" and surface.zone_b not in self.capacity_j_k and surface.zone_b not in self.boundary_names:
                raise ValueError(f"Unknown surface zone {surface.zone_b!r}")
            if surface.zone_a == surface.zone_b:
                raise ValueError(f"Surface {surface.name!r} connects a zone to itself")
            if not all(
                isfinite(value) and value >= 0
                for value in (surface.area_m2, surface.u_w_m2k)
            ):
                raise ValueError(f"Invalid surface {surface.name!r}")
        if len({path.name for path in self.air_paths}) != len(self.air_paths):
            raise ValueError("Duplicate air path name")
        for path in self.air_paths:
            if not path.name or path.zone_a not in self.capacity_j_k:
                raise ValueError(f"Invalid air path zone for {path.name!r}")
            if path.zone_b != "outside" and path.zone_b not in self.capacity_j_k and path.zone_b not in self.boundary_names:
                raise ValueError(f"Unknown air path boundary for {path.name!r}")
            if path.zone_a == path.zone_b or not all(
                isfinite(value) and value >= 0 for value in
                (path.closed_conductance_w_k, path.open_conductance_w_k)
            ) or path.open_conductance_w_k < path.closed_conductance_w_k:
                raise ValueError(f"Invalid air path conductance for {path.name!r}")
        for emitter in self.emitters:
            if emitter.zone not in self.capacity_j_k:
                raise ValueError(f"Unknown emitter zone {emitter.zone!r}")
            if not isfinite(emitter.release_time_s) or emitter.release_time_s <= 0:
                raise ValueError(f"Invalid release time for {emitter.name!r}")
        if len({heater.name for heater in self.setpoint_heaters}) != len(self.setpoint_heaters):
            raise ValueError("Duplicate setpoint heater name")
        for heater in self.setpoint_heaters:
            if not heater.name or heater.zone not in self.capacity_j_k:
                raise ValueError(f"Invalid setpoint heater zone for {heater.name!r}")
            if not isfinite(heater.effective_conductance_w_k) or heater.effective_conductance_w_k < 0:
                raise ValueError(f"Invalid setpoint heater conductance for {heater.name!r}")


@dataclass(frozen=True)
class Snapshot:
    """Measured or estimated starting conditions and constant inputs."""

    temperatures_c: Mapping[str, float]
    outside_c: float
    boundary_temperatures_c: Mapping[str, float] = field(default_factory=dict)
    emitter_stored_j: Mapping[str, float] = field(default_factory=dict)
    emitter_input_w: Mapping[str, float] = field(default_factory=dict)
    internal_gain_w: Mapping[str, float] = field(default_factory=dict)
    solar_gain_w: Mapping[str, float] = field(default_factory=dict)
    ventilation_loss_w: Mapping[str, float] = field(default_factory=dict)
    heater_setpoints_c: Mapping[str, float] = field(default_factory=dict)
    opening_fractions: Mapping[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class Forecast:
    """Prediction and signed initial heat-flow diagnostics."""

    temperatures_c: Mapping[str, float]
    emitter_stored_j: Mapping[str, float]
    initial_conduction_w: Mapping[str, float]
    initial_emitter_release_w: Mapping[str, float]
    initial_setpoint_proxy_gain_w: Mapping[str, float] = field(default_factory=dict)
    initial_air_path_w: Mapping[str, float] = field(default_factory=dict)


def _conduction(house: House, temperatures: Mapping[str, float], outside: float, boundaries: Mapping[str, float]) -> dict[str, float]:
    """Return signed heat flowing *into* each zone in watts."""
    result = dict.fromkeys(house.capacity_j_k, 0.0)
    for surface in house.surfaces:
        other = (
            outside if surface.zone_b == "outside"
            else temperatures[surface.zone_b] if surface.zone_b in temperatures
            else boundaries[surface.zone_b]
        )
        into_a = surface.conductance_w_k * (other - temperatures[surface.zone_a])
        result[surface.zone_a] += into_a
        if surface.zone_b in temperatures:
            result[surface.zone_b] -= into_a
    return result


def _air_exchange(house: House, temperatures: Mapping[str, float], outside: float,
                  boundaries: Mapping[str, float], fractions: Mapping[str, float]) -> dict[str, float]:
    """Return signed, position-dependent opening heat flow into each room."""
    result = dict.fromkeys(house.capacity_j_k, 0.0)
    for path in house.air_paths:
        other = (
            outside if path.zone_b == "outside"
            else temperatures[path.zone_b] if path.zone_b in temperatures
            else boundaries[path.zone_b]
        )
        into_a = path.conductance_w_k(fractions[path.name]) * (other - temperatures[path.zone_a])
        result[path.zone_a] += into_a
        if path.zone_b in temperatures:
            result[path.zone_b] -= into_a
    return result


def forecast(house: House, snapshot: Snapshot, horizon_s: float, step_s: float = 60.0) -> Forecast:
    """Integrate a simple multi-zone heat balance over the chosen horizon."""
    house.validate()
    if not isfinite(horizon_s) or horizon_s < 0 or not isfinite(step_s) or step_s <= 0:
        raise ValueError("Invalid forecast time")
    if set(snapshot.temperatures_c) != set(house.capacity_j_k):
        raise ValueError("A starting temperature is required for every zone")
    temperatures = {zone: float(value) for zone, value in snapshot.temperatures_c.items()}
    if not isfinite(snapshot.outside_c) or not all(map(isfinite, temperatures.values())):
        raise ValueError("Non-finite temperature")
    if set(snapshot.boundary_temperatures_c) != set(house.boundary_names):
        raise ValueError("A temperature is required for every boundary")
    if not all(map(isfinite, snapshot.boundary_temperatures_c.values())):
        raise ValueError("Non-finite boundary temperature")
    if set(snapshot.heater_setpoints_c) != {heater.name for heater in house.setpoint_heaters}:
        raise ValueError("A setting is required for every setpoint heater")
    if not all(map(isfinite, snapshot.heater_setpoints_c.values())):
        raise ValueError("Non-finite heater setpoint")
    if set(snapshot.opening_fractions) != {path.name for path in house.air_paths} or any(
        not isfinite(fraction) or not 0 <= fraction <= 1
        for fraction in snapshot.opening_fractions.values()
    ):
        raise ValueError("Invalid opening fractions")
    emitter_energy = {emitter.name: float(snapshot.emitter_stored_j.get(emitter.name, 0.0)) for emitter in house.emitters}
    if any(not isfinite(value) or value < 0 for value in emitter_energy.values()):
        raise ValueError("Invalid emitter energy")
    initial_conduction = _conduction(house, temperatures, snapshot.outside_c, snapshot.boundary_temperatures_c)
    initial_air_path = _air_exchange(house, temperatures, snapshot.outside_c,
                                     snapshot.boundary_temperatures_c, snapshot.opening_fractions)
    initial_release = {
        emitter.name: emitter_energy[emitter.name] / emitter.release_time_s
        for emitter in house.emitters
    }
    initial_setpoint_gain = {
        heater.name: heater.effective_conductance_w_k
        * max(0.0, snapshot.heater_setpoints_c[heater.name] - temperatures[heater.zone])
        for heater in house.setpoint_heaters
    }
    elapsed = 0.0
    while elapsed < horizon_s:
        dt = min(step_s, horizon_s - elapsed)
        into = _conduction(house, temperatures, snapshot.outside_c, snapshot.boundary_temperatures_c)
        air = _air_exchange(house, temperatures, snapshot.outside_c,
                            snapshot.boundary_temperatures_c, snapshot.opening_fractions)
        for zone in temperatures:
            into[zone] += air[zone] + (
                snapshot.internal_gain_w.get(zone, 0.0)
                + snapshot.solar_gain_w.get(zone, 0.0)
                - snapshot.ventilation_loss_w.get(zone, 0.0)
            )
        for heater in house.setpoint_heaters:
            into[heater.zone] += heater.effective_conductance_w_k * max(
                0.0, snapshot.heater_setpoints_c[heater.name] - temperatures[heater.zone]
            )
        for emitter in house.emitters:
            name = emitter.name
            release = emitter_energy[name] / emitter.release_time_s
            into[emitter.zone] += release
            input_w = snapshot.emitter_input_w.get(name, 0.0)
            if not isfinite(input_w) or input_w < 0:
                raise ValueError(f"Invalid emitter input for {name!r}")
            emitter_energy[name] = max(0.0, emitter_energy[name] + (input_w - release) * dt)
        temperatures = {
            zone: value + into[zone] * dt / house.capacity_j_k[zone]
            for zone, value in temperatures.items()
        }
        elapsed += dt
    return Forecast(temperatures, emitter_energy, initial_conduction, initial_release,
                    initial_setpoint_gain, initial_air_path)


def r_for_layers(layers_m_w_mk: tuple[tuple[float, float], ...], surface_r_m2k_w: float = 0.0) -> float:
    """Calculate area-specific resistance from homogeneous material layers."""
    resistance = surface_r_m2k_w
    for thickness_m, conductivity_w_mk in layers_m_w_mk:
        if thickness_m < 0 or conductivity_w_mk <= 0:
            raise ValueError("Invalid layer")
        resistance += thickness_m / conductivity_w_mk
    if not isfinite(resistance) or resistance <= 0:
        raise ValueError("Total R-value must be positive")
    return resistance


def effective_u(paths_fraction_r: tuple[tuple[float, float], ...]) -> float:
    """Combine parallel wall paths by area-weighting their U-values."""
    if not paths_fraction_r or abs(sum(f for f, _ in paths_fraction_r) - 1.0) > 1e-6:
        raise ValueError("Path fractions must sum to one")
    if any(f < 0 or r <= 0 or not isfinite(r) for f, r in paths_fraction_r):
        raise ValueError("Invalid wall path")
    return sum(f / r for f, r in paths_fraction_r)


def horizon_from_points(points_az_el: tuple[tuple[float, float], ...], azimuth_deg: float) -> float:
    """Interpolate skyline elevation around the circular 0/360-degree boundary."""
    if len(points_az_el) < 2:
        raise ValueError("At least two skyline points are required")
    if not isfinite(azimuth_deg):
        raise ValueError("Non-finite skyline azimuth")
    points = sorted(((az % 360.0, el) for az, el in points_az_el), key=lambda item: item[0])
    if any(not isfinite(az) or not isfinite(el) for az, el in points):
        raise ValueError("Non-finite skyline point")
    if any(points[i][0] == points[i + 1][0] for i in range(len(points) - 1)):
        raise ValueError("Duplicate skyline azimuth")
    azimuth = azimuth_deg % 360.0
    for index, (low_az, low_el) in enumerate(points):
        high_az, high_el = points[(index + 1) % len(points)]
        span = (high_az - low_az) % 360.0
        distance = (azimuth - low_az) % 360.0
        if distance <= span:
            return low_el + (high_el - low_el) * distance / span
    raise AssertionError("No skyline interval found")


def local_point_angles(
    home_lat_deg: float,
    home_lon_deg: float,
    observer_alt_m: float,
    point_lat_deg: float,
    point_lon_deg: float,
    point_alt_m: float,
) -> tuple[float, float]:
    """Return local bearing and elevation for a nearby skyline point."""
    radius_m = 6_371_000.0
    north_m = radius_m * radians(point_lat_deg - home_lat_deg)
    east_m = radius_m * cos(radians((home_lat_deg + point_lat_deg) / 2)) * radians(
        point_lon_deg - home_lon_deg
    )
    distance_m = hypot(north_m, east_m)
    if distance_m == 0:
        raise ValueError("Skyline point must be away from observer")
    return (
        degrees(atan2(east_m, north_m)) % 360.0,
        degrees(atan2(point_alt_m - observer_alt_m, distance_m)),
    )
