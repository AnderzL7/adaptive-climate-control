# Climate with heat loss calculation

[![GitHub Release][releases-shield]][releases]
[![GitHub Activity][commits-shield]][commits]
[![License][license-shield]](LICENSE)

![Project Maintenance][maintenance-shield]

_Integration to integrate with [climate_heat_loss][climate_heat_loss]._

**This integration will set up the following platforms.**

Platform | Description
-- | --
`binary_sensor` | Show something `True` or `False`.
`sensor` | Show info from blueprint API.
`switch` | Switch something `True` or `False`.

## Installation

### Manual

1. Using the tool of choice open the directory (folder) for your HA configuration (where you find `configuration.yaml`).
1. If you do not have a `custom_components` directory (folder) there, you need to create it.
1. In the `custom_components` directory (folder) create a new folder called `climate_heat_loss`.
1. Download _all_ the files from the `custom_components/climate_heat_loss/` directory (folder) in this repository.
1. Place the files you downloaded in the new directory (folder) you created.
1. Restart Home Assistant
1. In the HA UI go to "Configuration" -> "Integrations" click "+" and search for "Climate with heat loss calculation"

### HACS

1. Open HACS in home assistant
2. Under the meatball menu in the top right -> "Add custom repository"
3. Copy the URL of this GitHub repository -> Click "Add"
4. Find Climate heat loss in the list and click "Install"

## Configuration is done in the UI

<!---->

## Contributions are welcome!

If you want to contribute to this please read the [Contribution guidelines](CONTRIBUTING.md)

***

[climate_heat_loss]: https://github.com/AnderzL7/climate_heat_loss
[commits-shield]: https://img.shields.io/github/commit-activity/y/AnderzL7/climate_heat_loss.svg?style=for-the-badge
[commits]: https://github.com/AnderzL7/climate_heat_loss/commits/main
[license-shield]: https://img.shields.io/github/license/AnderzL7/climate_heat_loss.svg?style=for-the-badge
[maintenance-shield]: https://img.shields.io/badge/maintainer-Anders%20Lund%20%40AnderzL7-blue.svg?style=for-the-badge
[releases-shield]: https://img.shields.io/github/release/AnderzL7/climate_heat_loss.svg?style=for-the-badge
[releases]: https://github.com/AnderzL7/climate_heat_loss/releases
