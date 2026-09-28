"""Behavioral checks for room heat flow and geometry."""

from math import isclose

import pytest

from model import AirPath, Emitter, House, SetpointHeatProxy, Snapshot, Surface, effective_u, forecast, horizon_from_points, local_point_angles, r_for_layers
from power import coverage_adjusted_power


def test_shared_wall_moves_heat_once_and_conserves_energy():
    house = House({"stove": 100_000, "sov": 100_000}, (Surface("partition", "stove", "sov", 10, 1),))
    result = forecast(house, Snapshot({"stove": 25, "sov": 15}, 0), 60)
    assert result.initial_conduction_w == {"stove": -100, "sov": 100}
    assert isclose(result.temperatures_c["stove"] + result.temperatures_c["sov"], 40)


def test_outside_loss_and_emitter_stored_heat_have_expected_direction():
    house = House(
        {"stove": 300_000},
        (Surface("outer", "stove", "outside", 10, 0.5),),
        (Emitter("floor", "stove", 600),),
    )
    unheated = forecast(house, Snapshot({"stove": 20}, 0), 1800)
    heating = forecast(house, Snapshot({"stove": 20}, 0, emitter_input_w={"floor": 1500}), 1800)
    coasting = forecast(house, Snapshot({"stove": 20}, 0, emitter_stored_j={"floor": 300_000}), 1800)
    assert unheated.temperatures_c["stove"] < 20
    assert heating.temperatures_c["stove"] > unheated.temperatures_c["stove"]
    assert coasting.temperatures_c["stove"] > unheated.temperatures_c["stove"]
    assert heating.emitter_stored_j["floor"] > 0


def test_wall_parallel_paths_use_u_not_average_r():
    insulation_r = r_for_layers(((0.1, 0.04),), 0.17)
    frame_r = r_for_layers(((0.1, 0.12),), 0.17)
    u = effective_u(((0.8, insulation_r), (0.2, frame_r)))
    assert u > 1 / (0.8 * insulation_r + 0.2 * frame_r)


def test_horizon_interpolation_wraps_north():
    points = ((350, 10), (10, 30), (180, 0))
    assert isclose(horizon_from_points(points, 0), 20)
    assert isclose(horizon_from_points(points, 355), 15)


def test_skyline_angles_for_point_to_east():
    azimuth, elevation = local_point_angles(60, 10, 100, 60, 10.01, 200)
    assert isclose(azimuth, 90, abs_tol=0.1)
    assert elevation > 0


def test_invalid_surface_zone_rejected():
    house = House({"stove": 100_000}, (Surface("bad", "stove", "sov", 10, 1),))
    with pytest.raises(ValueError, match="Unknown surface zone"):
        forecast(house, Snapshot({"stove": 20}, 0), 60)


def test_measured_boundary_temperature_drives_heat_flow():
    house = House(
        {"stove": 100_000},
        (Surface("partition", "stove", "bod", 10, 1),),
        boundary_names=("bod",),
    )
    warmer = forecast(
        house,
        Snapshot({"stove": 20}, 0, boundary_temperatures_c={"bod": 25}),
        60,
    )
    colder = forecast(
        house,
        Snapshot({"stove": 20}, 0, boundary_temperatures_c={"bod": 15}),
        60,
    )
    assert warmer.initial_conduction_w["stove"] == 50
    assert colder.initial_conduction_w["stove"] == -50
    assert warmer.temperatures_c["stove"] > 20 > colder.temperatures_c["stove"]


def test_manual_floor_setting_warms_bad_then_adjacent_room_without_cooling():
    house = House(
        {"bad": 300_000, "soverom": 300_000},
        (Surface("partition", "bad", "soverom", 3, 1),),
        setpoint_heaters=(SetpointHeatProxy("bad_floor", "bad", 12),),
    )
    low = forecast(house, Snapshot({"bad": 21, "soverom": 20}, 0, heater_setpoints_c={"bad_floor": 18}), 1800)
    high = forecast(house, Snapshot({"bad": 21, "soverom": 20}, 0, heater_setpoints_c={"bad_floor": 25}), 1800)
    assert low.initial_setpoint_proxy_gain_w["bad_floor"] == 0
    assert high.initial_setpoint_proxy_gain_w["bad_floor"] == 48
    assert high.temperatures_c["bad"] > low.temperatures_c["bad"]
    assert high.temperatures_c["soverom"] > low.temperatures_c["soverom"]


def test_manual_setting_can_replace_outdoor_proxy_for_entry_wall():
    house = House({"stove": 300_000}, (Surface("entry", "stove", "vindfang_proxy", 4, 1),), boundary_names=("vindfang_proxy",))
    cold = forecast(house, Snapshot({"stove": 23}, 0, {"vindfang_proxy": 18}), 1800)
    warm = forecast(house, Snapshot({"stove": 23}, 0, {"vindfang_proxy": 21}), 1800)
    assert cold.initial_conduction_w["stove"] == -20
    assert warm.initial_conduction_w["stove"] == -8
    assert warm.temperatures_c["stove"] > cold.temperatures_c["stove"]


def test_partial_heater_history_does_not_claim_a_full_hour():
    assert isclose(coverage_adjusted_power(0, 1600, 0.25), 400)
    assert coverage_adjusted_power(0, None, None) == 0
    assert coverage_adjusted_power(0, 250, None) == 250
    assert coverage_adjusted_power(1000, 0, 1) == 0


def test_cellar_door_opening_cools_bod_and_then_adjacent_room():
    house = House(
        {"bod": 500_000, "stove": 2_000_000},
        surfaces=(Surface("partition", "stove", "bod", 5, 0.5),),
        boundary_names=("cellar",),
        air_paths=(AirPath("cellar_door", "bod", "cellar", 2, 60),),
    )
    starting = {"bod": 22, "stove": 23}
    closed = forecast(house, Snapshot(starting, 15, {"cellar": 12}, opening_fractions={"cellar_door": 0}), 1800)
    partly_open = forecast(house, Snapshot(starting, 15, {"cellar": 12}, opening_fractions={"cellar_door": 0.2}), 1800)
    open_door = forecast(house, Snapshot(starting, 15, {"cellar": 12}, opening_fractions={"cellar_door": 1}), 1800)
    assert closed.initial_air_path_w["bod"] == -20
    assert isclose(partly_open.initial_air_path_w["bod"], -136)
    assert open_door.initial_air_path_w["bod"] == -600
    assert open_door.temperatures_c["bod"] < partly_open.temperatures_c["bod"] < closed.temperatures_c["bod"]
    assert open_door.temperatures_c["stove"] < closed.temperatures_c["stove"]


def test_cellar_door_requires_valid_position_and_conductance():
    house = House({"bod": 500_000}, boundary_names=("cellar",),
                  air_paths=(AirPath("door", "bod", "cellar", 2, 60),))
    with pytest.raises(ValueError, match="Invalid opening fractions"):
        forecast(house, Snapshot({"bod": 22}, 15, {"cellar": 12}), 60)
    with pytest.raises(ValueError, match="Invalid air path conductance"):
        House({"bod": 500_000}, boundary_names=("cellar",),
              air_paths=(AirPath("door", "bod", "cellar", 60, 2),)).validate()
