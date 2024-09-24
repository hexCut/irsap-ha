# Home Assistant IRSAP Integration

This custom integration for [Home Assistant](https://www.home-assistant.io) allows monitoring and controlling IRSAP radiators via AWS Cognito authentication and API requests. Radiator data is retrieved from the IRSAP API endpoint and displayed in Home Assistant as temperature sensors and on/off switches.

## Features

- **Temperature Monitoring**: Sensors display the current temperature of the installed radiators.
- **On/Off Control**: Switches allow you to turn radiators on or off directly from Home Assistant. (Actually not fully working)
- **Real-time Updates**: Radiator data is updated periodically through API requests to IRSAP.

### Data Retrieved from the IRSAP API

The integration connects to the IRSAP API endpoint and retrieves a JSON payload containing various information about the radiators, including:

- **Current Temperature**: The current temperature of each radiator is displayed (normalized for Home Assistant).
- **On/Off Status**: Switches control the on/off state of each radiator.
- **Additional Data**: Other technical information is retrieved, such as sensor temperature offset and window status (open/closed).

Example of data extracted from the payload JSON:

```json
{
  "data": {
    "getShadow": {
      "payload": "{\"version\":264,\"state\":{\"desired\":{\"DEV1_TMP\":2290,\"DEV2_TMP\":2300,\"DEV3_TMP\":2300}}}"
    }
  }
}
