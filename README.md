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

[!["Buy Me A Coffee"](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://www.buymeacoffee.com/rsplab){:target="_blank"}

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

## Contributions are welcome

https://buymeacoffee.com/rsplab

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
