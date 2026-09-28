# Adaptive Climate Control

A Home Assistant climate-model project derived from
[`climate_heat_loss`](https://github.com/AnderzL7/climate_heat_loss), with its Git
history retained. The first release is **shadow only**: it publishes a 30-minute
temperature forecast for configured rooms and never calls a heater service.

## Status

The thermal model and a YAML-configured HA sensor adapter are under development.
Current predictions use provisional conductive surfaces, measured room and outside
temperature, measured floor-heater power where available, and an approximate
emitter heat lag. A house configuration may add low-gain proxy heat from an
independent thermostat's manually recorded setting; this is neither measured
heater power nor a command to that thermostat. The adapter can blend partial
rolling power history with a current reading. Provisional door paths can use
recorded positions; calibrated airflow, solar gain, sensor correction, heat
capacity, and control migration remain future work. Treat
the forecasts as diagnostics, not thermostat decisions.

## Installation

The repository can be added to HACS as a custom **Integration** repository, or
`custom_components/adaptive_climate_control/` can be copied into the HA config
directory. The integration currently uses YAML configuration under its own
`adaptive_climate_control:` key. An example structure is in
[`examples/shadow.yaml`](examples/shadow.yaml). Check the HA configuration after
copying the integration and YAML, then schedule a Core restart to load the new
integration. On a Raspberry Pi with fragile Zigbee connectivity, plan that
restart separately.

House-specific geometry, entity IDs, and tuning should be kept in private HA
configuration, not committed to this public repository.

After the integration has loaded once, edit its YAML model and call
`adaptive_climate_control.reload` from Developer Tools → Actions. The service
validates the whole new model before replacing the active one and immediately
refreshes existing forecast sensors. Invalid YAML or geometry leaves the
previous model active. The set of forecast room names and `horizon_minutes`
must stay the same; changing either requires a Core restart because they define
sensor identities. Updating Python files through HACS also requires a Core
restart; the reload service changes model settings, not loaded Python modules.

## Position-dependent openings

An optional `air_paths` list models heat exchange through an opening between a
forecast room and another room, a measured boundary, or outdoors. Each entry
specifies `name`, `zone_a`, `zone_b`, `position_entity`, and effective
`closed_conductance_w_k` and `open_conductance_w_k`. The position selector must
report `Closed`, `20%`, `40%`, `60%`, `80%`, or `Open`; intermediate positions
interpolate conductance. A closed door may retain nonzero leakage. Opening
conductance is a heat-balance approximation, not an airflow measurement; wind
and pressure effects are not yet modeled. All named boundaries need a
temperature entity. Forecast attributes expose opening fractions and initial
heat flow. Adding an opening only changes YAML and can use the reload service
once this integration version is loaded. Adding a forecast room also requires
a Core restart because it creates a new sensor identity.

## Pure model

`model.py` computes signed heat exchange across walls, emitter storage and
release, R/U values, and terrain-horizon interpolation. `observations.py`
contains bounded estimates for lagging sensors and humidity conversion.
`power.py` contains a provisional hard-veto heater ranking for future shadow
comparison. None of these modules imports Home Assistant. Run their checks with:

```text
python -m pytest -q tests
```

The current HA sensor adapter uses measured weighted-room inputs and the thermal
model. Peer-based sensor estimation and power-priority decisions are not yet wired
into HA.

## License

MIT, inherited from `climate_heat_loss`.
