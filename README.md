# Adaptive Climate Control

A Home Assistant climate-model project derived from
[`climate_heat_loss`](https://github.com/AnderzL7/climate_heat_loss), with its Git
history retained. The first release is **shadow only**: it publishes a 30-minute
temperature forecast for configured rooms and never calls a heater service.

## Status

The thermal model and a YAML-configured HA sensor adapter are under development.
Current predictions use provisional conductive surfaces, measured room and outside
temperature, measured heating power, and an approximate emitter heat lag. Openings,
solar gain, sensor correction, calibrated capacity, and control migration are
future work. Treat the forecasts as diagnostics, not thermostat decisions.

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
