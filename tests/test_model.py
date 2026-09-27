"""Behavioral checks for room heat flow and geometry."""

from math import isclose

import pytest

from model import Emitter, House, Snapshot, Surface, effective_u, forecast, horizon_from_points, local_point_angles, r_for_layers


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
