# Home Assistant - Custom Components IRSAP Integration

[hacs]: https://github.com/hacs/integration
[githubrelease]: https://github.com/hexCut/irsap-ha/releases
[maintenancebadge]: https://img.shields.io/badge/Maintained%3F-Yes-brightgreen.svg
[maintenance]: https://github.com/hexCut/irsap-ha/graphs/commit-activity
[github issues]: https://github.com/hexCut/irsap-ha/issues

[![hacs][hacsbadge]][hacs] 

[![GitHub latest release]][githubrelease] ![GitHub Release Date] [![Maintenancebadge]][maintenance] [![GitHub issuesbadge]][github issues]

---

## Information

This custom integration for [Home Assistant](https://www.home-assistant.io) allows monitoring and controlling IRSAP radiators via AWS Cognito authentication and API requests. Radiator data is retrieved from the IRSAP API endpoint and displayed in Home Assistant as a climate entity


## Features

- **Temperature Monitoring**: Sensors display the current temperature of the installed radiators.
- **On/Off Control**: Switches allow you to turn radiators on or off directly from Home Assistant.
- **Real-time Updates**: Radiator data is updated periodically through API requests to IRSAP.

### Data Retrieved from the IRSAP API

The integration connects to the IRSAP API endpoint and retrieves a JSON payload containing various information about the radiators, including:

- **Current Temperature**: The current temperature of each radiator is displayed (normalized for Home Assistant).
- **HVAC Mode**: Switches control the on/off state of each radiator.

## Installation

Easiest install is via [HACS](https://hacs.xyz/):

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=hexCut&repository=irsap-ha&category=integration)

`HACS -> Integrations -> Explore & Add Repositories -> IRSAP NOW Integration`

OR

1. Click on HACS in the Home Assistant menu
2. Click on Add Custom Repositories
3. Add the following GitHub repo
```
https://github.com/hexCut/irsap-ha
```
4. Click on `Integrations`
5. Click the `EXPLORE & ADD REPOSITORIES` button
6. Search for `IRSAP NOW Integration`
7. Click the `INSTALL THIS REPOSITORY IN HACS` button
8. Restart Home Assistant

## Configuration

### Config flow

To configure this integration go to: `Configurations` -> `Integrations` -> `ADD INTEGRATIONS` button, search for `IRSAP NOW Integration` and configure the component.

You can also use following [My Home Assistant](http://my.home-assistant.io/) link

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=irsap-ha)

### Setup

Now the integration is added to HACS and available in the normal HA integration installation

1. In the HomeAssistant left menu, click `Configuration`
2. Click `Integrations`
3. Click `ADD INTEGRATION`
4. Type `IRSAP NOW Integration` and select it
5. Enter the details:
   1. **Username**: Your username to login via IRSAP Now App
   2. **Password**: Your password to login via IRSAP Now App

### Options

Open the integration and click `Configure` to change:

- **Username / Password**: the IRSAP Now credentials (they are checked before being saved).
- **Update interval**: how often the IRSAP cloud is read, in seconds (default `60`, range `30`-`3600`). All radiators, LEDs and diagnostic sensors share a single request per interval. Changes sent from Home Assistant are applied immediately regardless of this value.

If you prefer to drive updates yourself (e.g. from an automation calling `homeassistant.update_entity`), turn off *Enable polling for changes* in the integration's *System options*: the integration then stops its own timer, and `update_entity` on any IRSAP entity refreshes all of them.

Requires Home Assistant 2024.11.0 or newer.

### Heating activity (`hvac_action`)

Besides the mode (heat / off), each radiator reports what it is actually doing: *heating*, *idle* (setpoint reached) or *off*.

- **One radiator in the home:** the value comes from the radiator's own heat call (`E_CLL`), read only when the radiator itself wrote the cloud state last. Right after a command from Home Assistant or the app, the action is estimated until the radiator reports again.
- **Several radiators:** the cloud has no per-radiator heat call, so the action is *estimated* from the measured temperature and the setpoint, with the radiator's own hysteresis, read from the cloud (0.2 °C on firmware 3.22: it heats until the room is that much above the setpoint and starts again that much below it). It can differ from what the radiator is really doing.

The radiator sends a new temperature reading only every few minutes (20 on firmware 3.22), so the action can lag behind the real heating by that much.

### Diagnostic sensors

Each radiator also has diagnostic sensors (Wi-Fi signal, IP address, last update, hysteresis, temperature offset, open window, pilot wire, child lock and, on the models that have them, CO2, VOC and air quality). They are listed under *Diagnostic* on the device page and are refreshed with the rest of the data.

- Values have proper units: Wi-Fi in dBm, hysteresis and temperature offset in °C, open-window off time in minutes, CO2 in ppm.
- A measurement the radiator doesn't have (the cloud reports `65535` or nothing) is created **disabled**, so it doesn't clutter the UI. If the radiator later reports a real value, the sensor is enabled again automatically. A sensor you disabled yourself is never re-enabled.

## Development

```
pip install -r requirements_test.txt
pytest
```

## Contributions are welcome

[!["Buy Me A Coffee"](https://www.buymeacoffee.com/assets/img/custom_images/yellow_img.png)](https://www.buymeacoffee.com/rsplab)

---

## Trademark Legal Notices

All product names, trademarks and registered trademarks in the images in this repository, are property of their respective owners.
All images in this repository are used by the author for identification purposes only.
The use of these names, trademarks and brands appearing in these image files, do not imply endorsement.

[hacs]: https://github.com/hacs/integration
[hacsbadge]: https://img.shields.io/badge/HACS-Custom-orange.svg
[github latest release]: https://img.shields.io/github/v/release/hexCut/irsap-ha
[githubrelease]: https://github.com/hexCut/irsap-ha/releases
[github release date]: https://img.shields.io/github/release-date/hexCut/irsap-ha
[maintenancebadge]: https://img.shields.io/badge/Maintained%3F-Yes-brightgreen.svg
[maintenance]: https://github.com/hexCut/irsap-ha/graphs/commit-activity
[github issuesbadge]: https://img.shields.io/github/issues/irsap-ha/issues
[github issues]: https://github.com/hexCut/irsap-ha/issues
