import logging
import time
from datetime import datetime, timedelta
from homeassistant.components.climate import (
    ClimateEntity,
    HVACMode,  # Importa HVACMode
)
from homeassistant.components.climate.const import ClimateEntityFeature
from homeassistant.const import UnitOfTemperature  # Importa UnitOfTemperature
from .const import DOMAIN, USER_POOL_ID, CLIENT_ID, REGION
import aiohttp
import json
from warrant import Cognito

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up climate platform."""
    envID = config_entry.data["envID"]
    username = config_entry.data["username"]
    password = config_entry.data["password"]

    token = await hass.async_add_executor_job(login_with_srp, username, password)

    if token and envID:
        _LOGGER.debug("Token and envID successfully obtained. Retrieving radiators.")

        # Salviamo token ed envID nel contesto di Home Assistant
        hass.data.setdefault(DOMAIN, {})
        hass.data[DOMAIN]["token"] = token
        hass.data[DOMAIN]["envID"] = envID
        hass.data[DOMAIN]["username"] = username
        hass.data[DOMAIN]["password"] = password

        radiators = await get_radiators(token, envID)
        if radiators:
            entities = [
                RadiatorClimate(radiator, token, envID) for radiator in radiators
            ]
            async_add_entities(entities, True)  # Aggiungi le entità alla piattaforma
            _LOGGER.debug(f"Created {len(entities)} radiators.")
        else:
            _LOGGER.warning("No radiators found in the API.")
    else:
        _LOGGER.error("Unable to obtain the token or envID. Check configuration.")


def login_with_srp(username, password):
    """Log in and obtain the access token using Warrant."""
    try:
        u = Cognito(USER_POOL_ID, CLIENT_ID, username=username, user_pool_region=REGION)
        u.authenticate(password=password)
        _LOGGER.debug(f"Access Token: {u.access_token}")
        return u.access_token
    except Exception as e:
        _LOGGER.error(f"Error during login: {e}")
        return None


async def get_radiators(token, envID):
    """Fetch radiator data from the API."""
    url = (
        "https://flqpp5xzjzacpfpgkloiiuqizq.appsync-api.eu-west-1.amazonaws.com/graphql"
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    graphql_query = {
        "operationName": "GetShadow",
        "variables": {"envId": envID},
        "query": "query GetShadow($envId: ID!) {\n  getShadow(envId: $envId) {\n    envId\n    payload\n    __typename\n  }\n}\n",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url, json=graphql_query, headers=headers
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    payload = json.loads(data["data"]["getShadow"]["payload"])
                    _LOGGER.debug(f"Payload retrieved from API: {payload}")

                    return extract_device_info(payload["state"]["desired"])
                else:
                    _LOGGER.error(f"API request error: {response.status}")
                    return []
    except ValueError as e:
        _LOGGER.error(f"Error converting temperature: {e}")
        return []
    except Exception as e:
        _LOGGER.error(f"Error during API call: {e}")
        return []


def extract_device_info(
    payload,
    nam_suffix="_NAM",
    tmp_suffix="_TMP",
    enb_suffix="_ENB",
    exclude_suffix="E_NAM",
):
    devices_info = []

    def find_device_keys(obj):
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key.endswith(nam_suffix) and not key.startswith(exclude_suffix):
                    device_info = {
                        "serial": value,
                        "temperature": 0,  # Default a 0 se non trovata
                        "state": "OFF",  # Default a OFF se non trovato
                    }
                    corresponding_tmp_key = key[: -len(nam_suffix)] + tmp_suffix
                    corresponding_enb_key = key[: -len(nam_suffix)] + enb_suffix

                    # Trova la temperatura
                    if corresponding_tmp_key in obj:
                        tmp_value = obj[corresponding_tmp_key]
                        device_info["temperature"] = (
                            float(tmp_value) / 10 if tmp_value is not None else 0
                        )

                    # Trova lo stato (ON/OFF)
                    if corresponding_enb_key in obj:
                        enb_value = obj[corresponding_enb_key]
                        device_info["state"] = "HEAT" if enb_value == 1 else "OFF"

                    devices_info.append(device_info)
                find_device_keys(value)
        elif isinstance(obj, list):
            for item in obj:
                find_device_keys(item)

    find_device_keys(payload)
    return devices_info


def find_device_key_by_name(payload, device_name, nam_suffix="_NAM"):
    """Trova la chiave del dispositivo in base al nome."""
    for key, value in payload.items():
        if key.endswith(nam_suffix) and value == device_name:
            return key[
                : -len(nam_suffix)
            ]  # Restituisce il prefisso del dispositivo (es. 'PCM', 'PTO')
    return None


class RadiatorClimate(ClimateEntity):
    """Representation of a radiator climate entity."""

    _attr_should_poll = True  # polling update dei sensori 
    
    def __init__(self, radiator, token, envID):
        self._radiator = radiator
        self._name = f"Radiator {radiator['serial']}"
        self._unique_id = f"radiator_{radiator['serial']}"
        self._current_temperature = radiator.get("temperature", 0)
        self._target_temperature = 18.0  # Imposta una temperatura target predefinita
        self._state = radiator["state"]  # Usa il valore di _ENB per lo stato
        self._token = token
        self._envID = envID

        # Modalità HVAC supportate (HEAT, OFF, AUTO se supportato)
        self._attr_hvac_modes = [
            HVACMode.HEAT,
            HVACMode.OFF,
            HVACMode.AUTO,
        ]  # Usa HVACMode per le modalità

        # Imposta la modalità HVAC in base allo stato corrente
        if self._state == "HEAT":
            self._attr_hvac_mode = HVACMode.HEAT
        elif self._state == "OFF":
            self._attr_hvac_mode = HVACMode.OFF
        elif self._state == "AUTO":
            self._attr_hvac_mode = HVACMode.AUTO
        else:
            self._attr_hvac_mode = (
                HVACMode.OFF
            )  # Fallback in caso di valori non riconosciuti

        # Funzionalità supportate (es. temperatura target e accensione/spegnimento)
        self._attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TURN_OFF
        )

        _LOGGER.info(f"Initialized {self._name} with state {self._attr_hvac_mode}")

    @property
    def min_temp(self):
        """Restituisce la temperatura minima raggiungibile."""
        return 12  # Temperatura minima di 12 gradi

    @property
    def max_temp(self):
        """Restituisce la temperatura massima raggiungibile."""
        return 32  # Temperatura massima di 32 gradi

    @property
    def name(self):
        """Return the name of the climate device."""
        return self._name

    @property
    def unique_id(self):
        """Return a unique ID for the climate device."""
        return self._unique_id

    @property
    def temperature_unit(self):
        """Return the unit of measurement."""
        return UnitOfTemperature.CELSIUS  # Usa UnitOfTemperature

    @property
    def current_temperature(self):
        """Return the current temperature."""
        return self._current_temperature

    @property
    def target_temperature(self):
        """Return the target temperature."""
        return self._target_temperature

    @property
    def hvac_mode(self):
        """Return current HVAC mode."""
        return self._attr_hvac_mode

    @property
    def hvac_modes(self):
        """Return available HVAC modes."""
        return self._attr_hvac_modes

    # Funzione per inviare il payload aggiornato alle API
    async def _send_target_temperature_to_api(self, token, envID, updated_payload):
        """Invia il payload aggiornato alle API."""
        url = "https://flqpp5xzjzacpfpgkloiiuqizq.appsync-api.eu-west-1.amazonaws.com/graphql"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        # updated_payload = '{"id":"af9146eb-fe6f-47dc-a0b4-2727b711e4ef","clientId":"app-now2-1.9.19-2124-ios-0409cdbc-2bb4-4a56-9114-453920ab21df","timestamp":1727457952117,"version":231,"state":{"desired":{"Dqq_LTC":0,"Dqq_BOU":true,"Dqq_SRL":"20:0a:0d:a2:37:44","Dqq_FWV":"3.22","Dqq_PLV":-1,"Dqq_X_co2Value":65535,"Dqq_NEP":0,"Dqq_X_ipAddress":"192.168.4.205","Dqq_X_OpenWindowSensorEnabled":0,"Dqq_MID":"Dqq","Dqq_X_MOD":"","Dqq_SEC":{"t":1717972313,"v":0},"Dqq_STA":2,"Dqq_STC":{"t":1717972313,"v":0},"Dqq_X_lock":0,"Dqq_X_filPiloteEnabled":0,"Dqq_LUP":"2024-09-27T17:22:36.000Z","Dqq_LEC":0,"Dqq_X_temperatureSensorOffset":-50,"Dqq_X_hysteresis":2,"Dqq_X_filPiloteStatus":0,"Dqq_SHV":231,"Dqq_X_OpenWindowDetected":0,"Dqq_X_identify":0,"Dqq_TYP":"RE","Dqq_X_OpenWindowSensorOffTime":30,"Dqq_NTP":0,"Dqq_SLV":-74,"Dqq_X_vocValue":65535,"Dqq_CNT":"RE_20:0a:0d:a2:37:44","Dqq_ERR":[],"Dqq_X_standby":0,"Dqq_X_metricInterval":20,"Dqq_X_CPW":0,"Dqq_X_CAP":[1,4,8,14],"Dqq_X_LCA":14931,"Dqq_X_TMS":"","Dqq_X_NRV":13227,"Dqq_X_WFC":11,"D0S_SHV":231,"D0S_X_co2Value":65535,"D0S_X_filPiloteEnabled":0,"D0S_X_LCA":383190,"D0S_X_ipAddress":"192.168.4.69","D0S_X_CAP":[1,4,8,14],"D0S_TYP":"RE","D0S_X_CPW":0,"D0S_X_standby":0,"D0S_X_filPiloteStatus":0,"D0S_X_hysteresis":2,"D0S_X_metricInterval":20,"D0S_SEC":{"t":1698532927,"v":0},"D0S_MID":"D0S","D0S_X_OpenWindowSensorEnabled":0,"D0S_LUP":"2024-09-27T17:22:38.000Z","D0S_PLV":-1,"D0S_LEC":0,"D0S_STC":{"t":1698532927,"v":0},"D0S_STA":2,"D0S_FWV":"3.22","D0S_X_OpenWindowDetected":0,"D0S_BOU":true,"D0S_LTC":0,"D0S_X_temperatureSensorOffset":-50,"D0S_SRL":"20:0a:0d:a2:36:33","D0S_NEP":0,"D0S_X_MOD":"","D0S_SLV":-77,"D0S_X_identify":0,"D0S_ERR":[],"D0S_X_vocValue":65535,"D0S_NTP":0,"D0S_CNT":"RE_20:0a:0d:a2:36:33","D0S_X_lock":0,"D0S_X_OpenWindowSensorOffTime":30,"D0S_X_TMS":"","D0S_X_NRV":12785,"D0S_X_WFC":11,"DoZ_X_metricInterval":20,"DoZ_SLV":-89,"DoZ_TYP":"RE","DoZ_X_filPiloteEnabled":0,"DoZ_SEC":{"t":1726956807,"v":0},"DoZ_X_lock":0,"DoZ_SHV":231,"DoZ_X_temperatureSensorOffset":-40,"DoZ_X_co2Value":65535,"DoZ_X_OpenWindowSensorEnabled":0,"DoZ_X_vocValue":65535,"DoZ_X_LCA":891,"DoZ_X_CAP":[1,4,8,14],"DoZ_LUP":"2024-09-27T17:18:32.000Z","DoZ_LEC":0,"DoZ_X_CPW":0,"DoZ_PLV":-1,"DoZ_SRL":"20:0a:0d:a2:37:33","DoZ_LTC":0,"DoZ_MID":"DoZ","DoZ_X_hysteresis":2,"DoZ_STC":{"t":1726956807,"v":0},"DoZ_STA":2,"DoZ_X_OpenWindowDetected":0,"DoZ_X_filPiloteStatus":0,"DoZ_ERR":[],"DoZ_NTP":0,"DoZ_X_OpenWindowSensorOffTime":30,"DoZ_X_MOD":"","DoZ_CNT":"RE_20:0a:0d:a2:37:33","DoZ_X_ipAddress":"192.168.4.183","DoZ_FWV":"3.22","DoZ_BOU":true,"DoZ_X_identify":0,"DoZ_X_standby":0,"DoZ_NEP":0,"DoZ_X_TMS":"","DoZ_X_NRV":13585,"DoZ_X_WFC":6,"Dom_ERR":[],"Dom_BOU":true,"Dom_SHV":231,"Dom_STA":2,"Dom_TYP":"RE","Dom_SRL":"20:0a:0d:a2:36:5e","Dom_MID":"Dom","Dom_CNT":"RE_20:0a:0d:a2:36:5e","Dom_PLV":-1,"Dom_SLV":-70,"Dom_FWV":"3.22","Dom_LUP":"2024-09-27T17:22:40.000Z","Dom_LEC":0,"Dom_LTC":0,"Dom_SEC":{"t":1727308528,"v":0},"Dom_STC":{"t":1727308528,"v":0},"Dom_NEP":0,"Dom_NTP":0,"Dom_X_CAP":[1,4,8,14],"Dom_X_filPiloteEnabled":0,"Dom_X_filPiloteStatus":0,"Dom_X_identify":0,"Dom_X_standby":0,"Dom_X_lock":0,"Dom_X_metricInterval":20,"Dom_X_OpenWindowSensorEnabled":0,"Dom_X_OpenWindowSensorOffTime":30,"Dom_X_temperatureSensorOffset":-50,"Dom_X_ipAddress":"192.168.4.112","Dom_X_hysteresis":2,"Dom_X_vocValue":65535,"Dom_X_co2Value":65535,"Dom_X_OpenWindowDetected":0,"Dom_X_MOD":"","Dom_X_CPW":0,"Dom_X_LCA":622955,"Dom_X_TMS":"","Dom_X_NRV":13126,"Dom_X_WFC":11,"PCM_TSP":{"p":{"u":0,"v":180,"m":3,"k":"TEMPORARY"},"e":"2024-09-27T17:50:00.000Z"},"PCM_STA":2,"PCM_CSP":{"p":{"k":"CURRENT","m":3,"u":0,"v":180},"e":"2024-09-27T17:50:00.000Z"},"PCM_AIQ":null,"PCM_MSP":{"p":{"u":0,"v":350,"m":3,"k":"MANUAL"}},"PCM_ENB":1,"PCM_ORD":1,"PCM_OPW":0,"PCM_TMP":217,"PCM_NAM":"Ceci Bathroom","PCM_CLL":0,"PCM_HUM":null,"PCM_MOD":1,"PCM_ICN":5,"PCM_X_LED_CSP":{"p":{"k":"CURRENT","m":4,"u":1}},"PCM_X_ICN":27,"PDP_ICN":5,"PDP_OPW":0,"PDP_ORD":3,"PDP_ENB":1,"PDP_MOD":2,"PDP_HUM":null,"PDP_STA":2,"PDP_X_ICN":27,"PDP_MSP":{"p":{"u":0,"v":230,"m":3,"k":"MANUAL"}},"PDP_TSP":{"p":{"u":0,"v":200,"m":3,"k":"TEMPORARY"},"e":"1970-01-01T00:00:00.000Z"},"PDP_CSP":{"p":{"k":"CURRENT","m":3,"u":0,"v":180},"e":"2024-09-27T22:00:00.000Z"},"PDP_NAM":"Guest Bathroom","PDP_TMP":216,"PDP_CLL":0,"PDP_AIQ":null,"PDP_X_LED_CSP":{"p":{"k":"CURRENT","m":4,"u":1,"v":{"h":65535,"v":255,"s":255}}},"PDP_FSP":{"p":{"k":"FIL_PILOTE","m":1,"u":0,"v":0}},"PDP_WSC":"1f4ed155-6cb1-4cd6-a0ad-15f188cad4f6","PTO_MSP":{"p":{"u":0,"v":220,"m":3,"k":"MANUAL"}},"PTO_CLL":0,"PTO_NAM":"Edo Bathroom","PTO_TMP":227,"PTO_AIQ":null,"PTO_ORD":2,"PTO_ENB":1,"PTO_MOD":2,"PTO_HUM":null,"PTO_ICN":5,"PTO_X_ICN":27,"PTO_OPW":0,"PTO_X_LED_CSP":{"p":{"k":"CURRENT","m":4,"u":1}},"PTO_STA":2,"PTO_CSP":{"p":{"k":"CURRENT","m":3,"u":0,"v":180},"e":"2024-09-27T22:00:00.000Z"},"PTO_TSP":{"p":{"k":"TEMPORARY","m":3,"u":0,"v":145},"e":"2024-07-09T22:00:00.000Z"},"PTO_WSC":"08597a98-d225-45d9-ba7b-15dc9fbddb42","PUJ_NAM":"Master Bathroom","PUJ_X_ICN":4,"PUJ_ICN":5,"PUJ_MOD":1,"PUJ_ENB":1,"PUJ_MSP":{"p":{"u":0,"v":180,"m":3,"k":"MANUAL"}},"PUJ_TSP":{"p":{"u":0,"v":200,"m":3,"k":"TEMPORARY"},"e":"1970-01-01T00:00:00.000Z"},"PUJ_ORD":4,"PUJ_AIQ":null,"PUJ_CLL":0,"PUJ_CSP":{"p":{"k":"CURRENT","m":3,"u":0,"v":180},"e":"2106-02-07T06:28:15.000Z"},"PUJ_HUM":null,"PUJ_TMP":218,"PUJ_STA":2,"PUJ_OPW":0,"PUJ_X_LED_ENB":0,"PUJ_X_LED_MOD":0,"GfF_CLL":0,"GfF_MOD":2,"GfF_TMP":216,"GfF_OPW":0,"GfF_MID":"Dqq","GfF_STA":2,"GfF_LUP":1727457755729,"GfF_PLD":"PDP","GfF_X_LED_ENB":0,"GfF_CAP":{"CH":{"mode":"CH","daysGroupingModes":[0,1,2],"programmingModes":[0],"valueMin":12,"valueStep":0.1,"valueMax":32,"timeRangeStep":60,"dayMaxRangeCount":8},"SENSING":{"mode":"SENSING","sensors":{"TMP":{"accuracy":0,"valueMin":-1000,"valueMax":1000}}}},"GfF_TSP":{"p":{"k":"TEMPORARY","m":3,"u":0,"v":200}},"GfF_X_LED_MOD":0,"GfF_MSP":{"p":{"k":"MANUAL","m":3,"u":0,"v":230}},"GfF_ENB":1,"GfF_CSP":{"p":{"k":"CURRENT","m":3,"u":0,"v":180},"e":"2024-09-27T22:00:00.000Z"},"GZE_X_LED_MOD":0,"GZE_STA":2,"GZE_CSP":{"p":{"k":"CURRENT","m":3,"u":0,"v":180},"e":"2024-09-27T22:00:00.000Z"},"GZE_LUP":1727457759913,"GZE_CAP":{"CH":{"mode":"CH","daysGroupingModes":[0,1,2],"programmingModes":[0],"valueMin":12,"valueStep":0.1,"valueMax":32,"timeRangeStep":60,"dayMaxRangeCount":8},"SENSING":{"mode":"SENSING","sensors":{"TMP":{"accuracy":0,"valueMin":-1000,"valueMax":1000}}}},"GZE_TSP":{"p":{"k":"TEMPORARY","m":3,"u":0,"v":145},"e":"2024-07-09T22:00:00.000Z"},"GZE_PLD":"PTO","GZE_X_LED_ENB":0,"GZE_MID":"D0S","GZE_TMP":227,"GZE_X_LED_CSP":{"p":{"k":"CURRENT","m":4,"u":1}},"GZE_CLL":0,"GZE_MOD":2,"GZE_ENB":1,"GZE_OPW":0,"GZE_MSP":{"p":{"k":"MANUAL","m":3,"u":0,"v":220}},"GOv_OPW":0,"GOv_CLL":0,"GOv_TMP":217,"GOv_X_LED_CSP":{"p":{"k":"CURRENT","m":4,"u":1}},"GOv_ENB":1,"GOv_MOD":1,"GOv_MSP":{"p":{"k":"MANUAL","m":3,"u":0,"v":208}},"GOv_STA":2,"GOv_MID":"DoZ","GOv_PLD":"PCM","GOv_TSP":{"p":{"k":"TEMPORARY","m":3,"u":0,"v":180},"e":"2024-09-27T17:50:00.000Z"},"GOv_CAP":{"CH":{"mode":"CH","daysGroupingModes":[0,1,2],"programmingModes":[0],"valueMin":12,"valueStep":0.1,"valueMax":32,"timeRangeStep":60,"dayMaxRangeCount":8},"SENSING":{"mode":"SENSING","sensors":{"TMP":{"accuracy":0,"valueMin":-1000,"valueMax":1000}}}},"GOv_X_LED_MOD":0,"GOv_X_LED_ENB":0,"GOv_LUP":1727457511951,"GOv_CSP":{"p":{"k":"CURRENT","m":3,"u":0,"v":180},"e":"2024-09-27T17:50:00.000Z"},"GIt_MID":"Dom","GIt_CAP":{"CH":{"mode":"CH","daysGroupingModes":[0,1,2],"programmingModes":[0],"valueMin":12,"valueStep":0.1,"valueMax":32,"timeRangeStep":60,"dayMaxRangeCount":8},"SENSING":{"mode":"SENSING","sensors":{"TMP":{"accuracy":0,"valueMin":-1000,"valueMax":1000}}}},"GIt_LUP":1727457760754,"GIt_STA":2,"GIt_CSP":{"p":{"k":"CURRENT","m":3,"u":0,"v":180},"e":"2106-02-07T06:28:15.000Z"},"GIt_CLL":0,"GIt_ENB":1,"GIt_MOD":1,"GIt_MSP":{"p":{"k":"MANUAL","m":3,"u":0,"v":180}},"GIt_TSP":{"p":{"k":"TEMPORARY","m":3,"u":0,"v":200}},"GIt_TMP":218,"GIt_OPW":0,"GIt_X_LED_ENB":0,"GIt_X_LED_MOD":0,"GIt_PLD":"PUJ","WCV_MID":"D0S","WCV_DID":"D0S","WCV_CAP":[1,4,8],"WCV_BOU":true,"WCV_GID":"GZE","WqL_DID":"Dqq","WqL_BOU":true,"WqL_GID":"GfF","WqL_MID":"Dqq","WqL_CAP":[1,4,8],"WQ0_DID":"DoZ","WQ0_BOU":true,"WQ0_GID":"GOv","WQ0_MID":"DoZ","WQ0_CAP":[1,4,8],"Wk6_DID":"Dom","Wk6_BOU":true,"Wk6_MID":"Dom","Wk6_GID":"GIt","Wk6_CAP":[1,4,8],"E_MOD":0,"E_X_DevNames":{"qq":"Heater Guest Bath","0S":"Edo Bathroom","oZ":"Ceci Bathroom"},"E_PRS":["7fa670d7-9cdd-4a14-8724-5b1ad428a1a1"],"E_TIM":120,"E_SEA":1,"E_TZ":"Europe/Rome","E_STP":[{"u":0,"v":220,"m":1,"k":"COM"},{"u":0,"v":180,"m":1,"k":"ECO"},{"u":0,"v":50,"m":1,"k":"OFF"},{"u":0,"v":250,"m":2,"k":"COM"},{"u":0,"v":270,"m":2,"k":"ECO"},{"u":0,"v":360,"m":2,"k":"OFF"},{"u":2,"v":4,"m":5,"k":"4"},{"u":2,"v":1,"m":5,"k":"1"},{"u":2,"v":2,"m":5,"k":"2"},{"u":2,"v":3,"m":5,"k":"3"},{"u":2,"v":0,"m":5,"k":"0"},{"u":0,"v":400,"m":6,"k":"ON"},{"u":0,"v":400,"m":6,"k":"OFF"},{"u":1,"v":{"h":0,"v":0,"s":0},"m":4,"k":"LED_OFF","n":"Spento"}],"E_CTM":"2023-01-11T13:46:58.954Z","E_EXT":212,"E_EXH":83,"E_X_EcoComfort":1,"E_X_VAC":{"start":"1970-01-01T00:00:00.000Z","end":"1970-01-01T00:00:00.000Z"},"E_VER":1,"E_ID":"af9146eb-fe6f-47dc-a0b4-2727b711e4ef","E_CPC":0,"E_LOC":{"latLon":"45.46554,8.88882","address":{"country":"Italia","iso":"ITA","city":"Magenta","street":"Via Armando Diaz","postalCode":"20013","houseNumber":"29","state":"Lombardia"}},"E_WTH":200,"E_CLL":0,"E_WTD":{"current":{"dt":1727455354,"temperature":212,"humidity":83,"weather":200},"next":[],"dayDetails":{"sunrise":1727414270,"sunset":1727457165,"temperatures":{"min":194,"max":218}}},"E_NAM":"Diaz 29","E_SCH":[{"w":[[{"t":0,"s":"1#ECO"}],[{"t":0,"s":"1#ECO"}],[{"t":0,"s":"1#ECO"}],[{"t":0,"s":"1#ECO"}],[{"t":0,"s":"1#ECO"}],[{"t":0,"s":"1#ECO"}],[{"t":0,"s":"1#ECO"}]],"n":"","m":1,"k":"1f4ed155-6cb1-4cd6-a0ad-15f188cad4f6"},{"w":[[{"t":0,"s":"1#ECO"}],[{"t":0,"s":"1#ECO"}],[{"t":0,"s":"1#ECO"}],[{"t":0,"s":"1#ECO"}],[{"t":0,"s":"1#ECO"}],[{"t":0,"s":"1#ECO"}],[{"t":0,"s":"1#ECO"}]],"n":"","m":1,"k":"08597a98-d225-45d9-ba7b-15dc9fbddb42"}]}}}'
        json_payload = json.dumps(updated_payload)

        graphql_query = {
            "operationName": "UpdateShadow",
            "variables": {"envId": envID, "payload": json_payload},
            "query": (
                "mutation UpdateShadow($envId: ID!, $payload: AWSJSON!) {\n asyncUpdateShadow(envId: $envId, payload: $payload) {\n status\n code\n message\n payload\n __typename\n }\n}\n"
            ),
        }

        # Log del payload completo
        _LOGGER.info(f"Payload da inviare all'API: {graphql_query}")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, json=graphql_query, headers=headers
                ) as response:
                    if response.status == 200:
                        _LOGGER.info("Payload successfully sent to the API.")
                        return True
                    else:
                        _LOGGER.error(
                            f"API request error: {response.status} - {await response.text()}"
                        )
                        return False
        except Exception as e:
            _LOGGER.error(f"Error sending payload to API: {e}")
            return False

    async def find_device_key_by_name(payload, device_name, nam_suffix="_NAM"):
        """Trova la chiave del dispositivo in base al nome."""
        for key, value in payload.items():
            if key.endswith(nam_suffix) and value == device_name:
                return key[
                    : -len(nam_suffix)
                ]  # Restituisci il prefisso (es. 'PCM', 'PTO')
        return None

    import time

    async def generate_device_payload(
        self, payload, device_name, temperature=None, enable=None
    ):
        # Aggiorna il timestamp con il tempo attuale in millisecondi
        current_timestamp = int(time.time() * 1000)  # Tempo attuale in millisecondi
        payload["timestamp"] = current_timestamp  # Aggiorna il timestamp nel payload

        payload["clientId"] = (
            "app-now2-1.9.19-2124-ios-0409cdbc-2bb4-4a56-9114-453920ab21df"  # Aggiorna il clientId facendo finta di essere l'App su iOS
        )

        """Aggiorna il payload del dispositivo con una nuova temperatura o stato di accensione/spegnimento."""
        desired_payload = payload.get("state", {}).get(
            "desired", {}
        )  # Accedi a payload["state"]["desired"]

        # Cerca il device nel payload basato sul nome
        for key, value in desired_payload.items():
            if key.endswith("_NAM") and value == device_name:
                base_key = key[:-4]  # Ottieni la chiave di base senza il suffisso

                # Aggiorna la temperatura se fornita
                if temperature is not None:
                    msp_key = f"{base_key}_MSP"
                    if msp_key in desired_payload:
                        # Aggiorna il valore 'v' all'interno del dizionario
                        if "p" in desired_payload[msp_key]:
                            desired_payload[msp_key]["p"]["v"] = int(
                                temperature * 10
                            )  # Converti in decimi di grado
                        # Aggiorna lo stato di accensione/spegnimento se fornito
                        enable_key = f"{base_key}_ENB"
                        if enable_key in desired_payload:
                            desired_payload[enable_key] = 1
                        break

        # Rimuovi 'sk' se esistente
        desired_payload.pop("sk", None)

        # Aggiorna il payload originale
        payload["state"]["desired"] = desired_payload

        # Riordina il payload secondo l'ordine richiesto
        ordered_payload = {
            "id": payload.get("id"),
            "clientId": payload.get("clientId"),
            "timestamp": payload.get("timestamp"),
            "version": 226,  # Imposta la versione a 226
            "state": payload.get("state"),
        }

        return ordered_payload  # Restituisci il payload aggiornato

    async def generate_device_payload_for_hvac(
        self, payload, device_name, hvac_mode=None, enable=None
    ):
        # Aggiorna il timestamp con il tempo attuale in millisecondi
        current_timestamp = int(time.time() * 1000)  # Tempo attuale in millisecondi
        payload["timestamp"] = current_timestamp  # Aggiorna il timestamp nel payload

        payload["clientId"] = (
            "app-now2-1.9.19-2124-ios-0409cdbc-2bb4-4a56-9114-453920ab21df"  # Aggiorna il clientId facendo finta di essere l'App su iOS
        )

        """Aggiorna il payload del dispositivo con una nuova temperatura o stato di accensione/spegnimento."""
        desired_payload = payload.get("state", {}).get(
            "desired", {}
        )  # Accedi a payload["state"]["desired"]

        # Cerca il device nel payload basato sul nome
        for key, value in desired_payload.items():
            if key.endswith("_NAM") and value == device_name:
                base_key = key[:-4]  # Ottieni la chiave di base senza il suffisso

                if hvac_mode is not None:
                    enable_key = f"{base_key}_ENB"
                    if enable_key in desired_payload:
                        # Set the value based on the hvac_mode
                        desired_payload[enable_key] = 1 if hvac_mode == 1 else 0
                    break

        # Rimuovi 'sk' se esistente
        desired_payload.pop("sk", None)

        # Aggiorna il payload originale
        payload["state"]["desired"] = desired_payload

        # Riordina il payload secondo l'ordine richiesto
        ordered_payload = {
            "id": payload.get("id"),
            "clientId": payload.get("clientId"),
            "timestamp": payload.get("timestamp"),
            "version": 226,  # Imposta la versione a 226
            "state": payload.get("state"),
        }

        return ordered_payload  # Restituisci il payload aggiornato

    async def get_current_payload(self, token, envID):
        """Fetch the current device payload from the API."""
        url = "https://flqpp5xzjzacpfpgkloiiuqizq.appsync-api.eu-west-1.amazonaws.com/graphql"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        graphql_query = {
            "operationName": "GetShadow",
            "variables": {"envId": envID},
            "query": "query GetShadow($envId: ID!) {\n  getShadow(envId: $envId) {\n    envId\n    payload\n    __typename\n  }\n}\n",
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, json=graphql_query, headers=headers
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        payload = json.loads(data["data"]["getShadow"]["payload"])
                        return payload
                    else:
                        _LOGGER.error(f"Error fetching payload: {response.status}")
                        return None
        except Exception as e:
            _LOGGER.error(f"Exception during payload retrieval: {e}")
            return None

    # Modifica la funzione per accettare altri argomenti tramite kwargs
    async def async_set_temperature(self, **kwargs):
        "Imposta la temperatura target del radiatore."
        temperature = kwargs.get("temperature")  # Estrae la temperatura dai kwargs
        if temperature is None:
            _LOGGER.error("Nessuna temperatura fornita per il settaggio.")
            return

        username = self.hass.data[DOMAIN].get("username")
        password = self.hass.data[DOMAIN].get("password")

        token = await self.hass.async_add_executor_job(
            login_with_srp, username, password
        )
        envID = self.hass.data[DOMAIN].get("envID")

        if not token or not envID:
            _LOGGER.error("Token or envID not found in hass.data.")
            return

        device_name = self._name.replace("Radiator ", "")  # Usa il nome del dispositivo

        # Ottieni il payload attuale del dispositivo dalle API
        payload = await self.get_current_payload(token, envID)

        if payload is None:
            _LOGGER.error(f"Failed to retrieve current payload for {self._name}")
            return

        # Aggiorna il payload con la nuova temperatura
        updated_payload = await self.generate_device_payload(  # Add 'await' here if this method is async
            payload=payload,
            device_name=device_name,
            temperature=temperature,  # Passa la temperatura come keyword argument
        )

        # Invia il nuovo payload aggiornato alle API
        success = await self._send_target_temperature_to_api(
            token, envID, updated_payload
        )
        if success:
            self._target_temperature = temperature
            # Cambia lo stato in HEAT
            self._attr_hvac_mode = HVACMode.HEAT
            _LOGGER.info(
                f"Temperature set to {temperature} for {self._name}, mode changed to HEAT"
            )
        else:
            _LOGGER.error(f"Failed to update temperature for {self._name}")

    async def async_set_hvac_mode(self, hvac_mode):
        """Set new target HVAC mode."""
        username = self.hass.data[DOMAIN].get("username")
        password = self.hass.data[DOMAIN].get("password")

        token = await self.hass.async_add_executor_job(
            login_with_srp, username, password
        )
        envID = self.hass.data[DOMAIN].get("envID")

        if not token or not envID:
            _LOGGER.error("Token or envID not found in hass.data.")
            return

        if hvac_mode == HVACMode.OFF:
            _LOGGER.debug(f"Setting {self._radiator['serial']} to OFF")
            _LOGGER.info(f"Setting {self._radiator['serial']} to OFF")
            await self._set_radiator_state(False)

            device_name = self._name.replace(
                "Radiator ", ""
            )  # Usa il nome del dispositivo

            # Ottieni il payload attuale del dispositivo dalle API
            payload = await self.get_current_payload(token, envID)

            if payload is None:
                _LOGGER.error(f"Failed to retrieve current payload for {self._name}")
                return

            # Aggiorna il payload con la nuova temperatura
            updated_payload = await self.generate_device_payload_for_hvac(  # Add 'await' here if this method is async
                payload=payload,
                device_name=device_name,
                hvac_mode=0,
            )

            # Invia il nuovo payload aggiornato alle API
            success = await self._send_target_temperature_to_api(
                token, envID, updated_payload
            )

        elif hvac_mode == HVACMode.HEAT:
            _LOGGER.debug(f"Setting {self._radiator['serial']} to HEAT")
            await self._set_radiator_state(True)

            _LOGGER.info(f"Setting {self._radiator['serial']} to OFF")
            await self._set_radiator_state(False)

            device_name = self._name.replace(
                "Radiator ", ""
            )  # Usa il nome del dispositivo

            # Ottieni il payload attuale del dispositivo dalle API
            payload = await self.get_current_payload(token, envID)

            if payload is None:
                _LOGGER.error(f"Failed to retrieve current payload for {self._name}")
                return

            # Aggiorna il payload con la nuova temperatura
            updated_payload = await self.generate_device_payload_for_hvac(  # Add 'await' here if this method is async
                payload=payload,
                device_name=device_name,
                hvac_mode=1,
            )

            # Invia il nuovo payload aggiornato alle API
            success = await self._send_target_temperature_to_api(
                token, envID, updated_payload
            )

        else:
            _LOGGER.error(f"Unsupported HVAC mode: {hvac_mode}")
            return

        if success:
            # Aggiorna la modalità HVAC attuale
            self._attr_hvac_mode = hvac_mode
            self.async_write_ha_state()
        else:
            _LOGGER.error(f"Failed to update HVAC mode for {self._name}")

    async def _set_radiator_state(self, state):
        """Send request to set the radiator state."""
        _LOGGER.debug(
            f"Setting radiator state: {self._radiator['serial']} to {'on' if state else 'off'}"
        )

        url = "https://flqpp5xzjzacpfpgkloiiuqizq.appsync-api.eu-west-1.amazonaws.com/graphql"
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

        payload = {
            "operationName": "UpdateShadow",
            "variables": {
                "envId": self._envID,
                "payload": json.dumps(
                    {
                        "id": self._envID,
                        "clientId": "app-now2-1.9.19-2124-ios-0409cdbc-2bb4-4a56-9114-453920ab21df",
                        "timestamp": int(time.time() * 1000),
                        "version": 231,
                        "state": {
                            "desired": {
                                "PCM_ENB": 1 if state else 0,
                                "PCM_CLL": 0,
                                "PCM_MOD": 1,
                                "PCM_ICN": 5,
                                "PCM_X_ICN": 27,
                            }
                        },
                    }
                ),
            },
            "query": "mutation UpdateShadow($envId: ID!, $payload: AWSJSON!) {\n asyncUpdateShadow(envId: $envId, payload: $payload) {\n status\n code\n message\n payload\n __typename\n }\n}\n",
        }

        _LOGGER.debug(f"Payload sent: {payload}")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=payload) as response:
                    _LOGGER.debug(
                        f"API response: {response.status}, {await response.text()}"
                    )
                    if response.status == 200:
                        _LOGGER.debug(
                            f"Radiator state {self._radiator['serial']} updated successfully."
                        )
                        self._state = state
                    else:
                        _LOGGER.error(
                            f"Error updating radiator state {self._radiator['serial']}: {response.status}"
                        )
        except Exception as e:
            _LOGGER.error(
                f"Error setting radiator state {self._radiator['serial']}: {e}"
            )

    async def async_update(self):
        "Fetch new state data for this climate entity."
        _LOGGER.info(f"Updating radiator climate {self._name}")

        # Recupera token e envID
        token = self.hass.data[DOMAIN].get("token")
        envID = self.hass.data[DOMAIN].get("envID")

        if not token or not envID:
            _LOGGER.error("Token or envID not found in hass.data.")
            return

        # Ottieni il payload corrente dal dispositivo tramite le API
        payload = await self.get_current_payload(token, envID)

        if payload is None:
            _LOGGER.error(f"Failed to retrieve current payload for {self._name}")
            return

        # Cerca la temperatura nel payload (_TMP)
        device_name = self._name.replace("Radiator ", "")
        desired_payload = payload.get("state", {}).get("desired", {})

        for key, value in desired_payload.items():
            if key.endswith("_NAM") and value == device_name:
                base_key = key[:-4]  # Ottieni la chiave di base
                tmp_key = f"{base_key}_TMP"

                if tmp_key in desired_payload:
                    # Aggiorna la temperatura attuale del dispositivo
                    self._current_temperature = (
                        desired_payload[tmp_key] / 10
                    )  # In gradi Celsius

                break

 
    self.async_write_ha_state() # Notifica a Home Assistant che lo stato è cambiato
