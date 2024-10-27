import asyncio
import logging
import time
from homeassistant.components.climate import (
    ClimateEntity,
    HVACMode,
)
from homeassistant.components.climate.const import ClimateEntityFeature
from homeassistant.const import UnitOfTemperature
from homeassistant.helpers.entity_platform import (
    AddEntitiesCallback,
)  # Importa UnitOfTemperature
from .const import DOMAIN, USER_POOL_ID, CLIENT_ID, REGION
import aiohttp
import json
from warrant import Cognito
import re
from .device import RadiatorDevice
from .device_manager import device_manager

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass, config_entry, async_add_entities: AddEntitiesCallback
):
    from .sensor import RadiatorSensor

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
        _LOGGER.debug(
            f"Retrieved radiators: {radiators}"
        )  # Log per verificare i radiatori

        for r in radiators:
            device = RadiatorDevice(r, token, envID)
            device_manager.add_device(device)  # Aggiungi il dispositivo al manager
            climate_entity = RadiatorClimate(
                r, token, envID, unique_id=f"{r['serial']}_climate"
            )
            async_add_entities([climate_entity], True)

    else:
        _LOGGER.error("Unable to obtain the token or envID. Check configuration.")


def login_with_srp(username, password):
    "Log in and obtain the access token using Warrant."
    try:
        u = Cognito(USER_POOL_ID, CLIENT_ID, username=username, user_pool_region=REGION)
        u.authenticate(password=password)
        _LOGGER.debug(f"Access Token: {u.access_token}")
        return u.access_token
    except Exception as e:
        _LOGGER.error(f"Error during login: {e}")
        return None


async def get_radiators(token, envID):
    "Fetch radiator data from the API."
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
    srl_suffix="_SRL",
    exclude_suffix="E_NAM",
):
    devices_info = []

    # Trova tutte le chiavi _NAM, _SRL, _FWV, _TYP e _X_ipAddress in ordine
    nam_keys = []
    srl_keys = []
    fwv_keys = []
    typ_keys = []
    ip_keys = []

    def find_device_keys(obj):
        if isinstance(obj, dict):
            for key, value in obj.items():
                # Raccogli chiavi _NAM e aggiungi i dettagli iniziali
                if key.endswith(nam_suffix) and not key.startswith(exclude_suffix):
                    device_info = {
                        "serial": value,
                        "temperature": 0,  # Default a 0 se non trovata
                        "state": "OFF",  # Default a OFF se non trovato
                    }
                    nam_keys.append((key, device_info))

                # Trova chiavi _SRL, _FWV, _TYP, _X_ipAddress e aggiungile agli elenchi
                if re.match(r"^D[a-zA-Z]{2}_SRL$", key):
                    srl_keys.append((key, value))
                elif re.match(r"^D[a-zA-Z]{2}_FWV$", key):
                    fwv_keys.append((key, value))
                elif re.match(r"^D[a-zA-Z]{2}_TYP$", key):
                    typ_keys.append((key, value))
                elif re.match(r"^D[a-zA-Z]{2}_X_ipAddress$", key):
                    ip_keys.append((key, value))

                # Ricorsione per trovare chiavi nested
                find_device_keys(value)
        elif isinstance(obj, list):
            for item in obj:
                find_device_keys(item)

    # Esegui la ricerca di chiavi nel payload
    find_device_keys(payload)

    # Associa ogni _NAM ai suoi corrispondenti attributi in ordine di apparizione
    for i, (nam_key, device_info) in enumerate(nam_keys):
        base_key = nam_key[: -len(nam_suffix)]
        corresponding_tmp_key = base_key + tmp_suffix
        corresponding_enb_key = base_key + enb_suffix

        # Trova la temperatura
        if corresponding_tmp_key in payload:
            tmp_value = payload[corresponding_tmp_key]
            device_info["temperature"] = (
                float(tmp_value) / 10 if tmp_value is not None else 0
            )

        # Trova lo stato (ON/OFF)
        if corresponding_enb_key in payload:
            enb_value = payload[corresponding_enb_key]
            device_info["state"] = "HEAT" if enb_value == 1 else "OFF"

        # Associa SRL, FWV, TYP e IP in base alla posizione dell'indice
        if i < len(srl_keys):
            device_info["mac"] = srl_keys[i][1]
        if i < len(fwv_keys):
            device_info["firmware"] = fwv_keys[i][1]
        if i < len(typ_keys):
            device_info["model"] = typ_keys[i][1]
        if i < len(ip_keys):
            device_info["ip_address"] = ip_keys[i][1]

        devices_info.append(device_info)

    return devices_info


def find_device_key_by_name(payload, device_name, nam_suffix="_NAM"):
    "Trova la chiave del dispositivo in base al nome."
    for key, value in payload.items():
        if key.endswith(nam_suffix) and value == device_name:
            return key[
                : -len(nam_suffix)
            ]  # Restituisce il prefisso del dispositivo (es. 'PCM', 'PTO')
    return None


class RadiatorClimate(ClimateEntity):
    "Representation of a radiator climate entity."

    def __init__(self, radiator, token, envID, unique_id):
        self._radiator = radiator
        self._device = RadiatorDevice(radiator, token, envID)
        self._attr_name = f"{radiator['serial']} Climate"
        self._attr_unique_id = unique_id
        self._current_temperature = radiator.get("temperature", 0)
        self._target_temperature = 18.0  # Imposta una temperatura target predefinita
        self._state = radiator["state"]  # Usa il valore di _ENB per lo stato
        self._token = token
        self._envID = envID
        self._serial_number = radiator.get("mac")
        self._sw_version = radiator.get("firmware")
        self._model = radiator.get("model")

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

        _LOGGER.info(f"Initialized {self._attr_name} with state {self._attr_hvac_mode}")

    @property
    def min_temp(self):
        "Restituisce la temperatura minima raggiungibile."
        return 12  # Temperatura minima di 12 gradi

    @property
    def max_temp(self):
        "Restituisce la temperatura massima raggiungibile."
        return 32  # Temperatura massima di 32 gradi

    @property
    def name(self):
        "Return the name of the climate device."
        return self._attr_name

    @property
    def unique_id(self):
        "Return a unique ID for the climate device."
        return self._attr_unique_id

    @property
    def temperature_unit(self):
        "Return the unit of measurement."
        return UnitOfTemperature.CELSIUS  # Usa UnitOfTemperature

    @property
    def current_temperature(self):
        "Return the current temperature."
        return self._current_temperature

    @property
    def target_temperature(self):
        "Return the target temperature."
        return self._target_temperature

    @property
    def hvac_mode(self):
        "Return current HVAC mode."
        return self._attr_hvac_mode

    @property
    def hvac_modes(self):
        "Return available HVAC modes."
        return self._attr_hvac_modes

    @property
    def extra_state_attributes(self):
        """Return additional attributes like IP address."""
        return {
            "min_temperature": self._radiator.get("min_temperature"),
            "max_temperature": self._radiator.get("max_temperature"),
        }

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {
                (DOMAIN, self._device.radiator["serial"])
            },  # Use device serial number
            "name": self._device.radiator["serial"],
            "model": self._device.radiator.get("model", "Unknown model"),
            "manufacturer": "IRSAP",
            "sw_version": self._device.radiator.get("firmware", "unknown"),
        }

    # Funzione per inviare il payload aggiornato alle API
    async def _send_target_temperature_to_api(self, token, envID, updated_payload):
        "Invia il payload aggiornato alle API."
        url = "https://flqpp5xzjzacpfpgkloiiuqizq.appsync-api.eu-west-1.amazonaws.com/graphql"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        json_payload = json.dumps(updated_payload)

        graphql_query = {
            "operationName": "UpdateShadow",
            "variables": {"envId": envID, "payload": json_payload},
            "query": (
                "mutation UpdateShadow($envId: ID!, $payload: AWSJSON!) {\n asyncUpdateShadow(envId: $envId, payload: $payload) {\n status\n code\n message\n payload\n __typename\n }\n}\n"
            ),
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, json=graphql_query, headers=headers
                ) as response:
                    if response.status == 200:
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
        "Trova la chiave del dispositivo in base al nome."
        for key, value in payload.items():
            if key.endswith(nam_suffix) and value == device_name:
                return key[
                    : -len(nam_suffix)
                ]  # Restituisci il prefisso (es. 'PCM', 'PTO')
        return None

    async def generate_device_payload(
        self, payload, device_name, temperature=None, enable=None
    ):
        # Aggiorna il timestamp con il tempo attuale in millisecondi
        current_timestamp = int(time.time() * 1000)  # Tempo attuale in millisecondi
        payload["timestamp"] = current_timestamp  # Aggiorna il timestamp nel payload

        payload["clientId"] = (
            "app-now2-1.9.19-2124-ios-0409cdbc-2bb4-4a56-9114-453920ab21df"  # Fake clientId iOS
        )

        # "Aggiorna il payload del dispositivo con una nuova temperatura o stato di accensione/spegnimento"
        desired_payload = payload.get("state", {}).get(
            "desired", {}
        )  # Accedi a payload["state"]["desired"]

        # Cerca il device nel payload basato sul nome
        for key, value in desired_payload.items():
            if key.endswith("_NAM") and value == device_name:
                base_key = key[:-4]  # Ottieni la chiave di base senza il suffisso

                # Aggiorna la temperatura se fornita
                if temperature is not None:
                    # Aggiorna _MSP
                    msp_key = f"{base_key}_MSP"
                    if msp_key in desired_payload:
                        if "p" in desired_payload[msp_key]:
                            desired_payload[msp_key]["p"]["v"] = int(temperature * 10)

                    # Aggiorna _TSP con il formato richiesto
                    tsp_key = f"{base_key}_TSP"
                    if tsp_key in desired_payload:
                        desired_payload[tsp_key] = {
                            "p": {
                                "u": 0,
                                "v": int(temperature * 10),
                                "m": 3,
                                # "k": "TEMPORARY",
                                "k": "MANUAL",
                            },
                            # "e": "1970-01-01T00:00:00.000Z",
                        }

                    # Aggiorna _CSP con il formato richiesto
                    csp_key = f"{base_key}_CSP"
                    if csp_key in desired_payload:
                        desired_payload[csp_key] = {
                            "p": {
                                "k": "CURRENT",
                                "m": 3,
                                "u": 0,
                                "v": int(temperature * 10),
                            },
                            "e": "1970-01-01T00:00:00.000Z",
                        }

                    # Aggiorna lo stato di accensione/spegnimento se fornito
                    enable_key = f"{base_key}_ENB"
                    if enable_key in desired_payload:
                        desired_payload[enable_key] = 1

                # Aggiorna _CLL se presente, impostandolo a 1
                cll_key = f"{base_key}_CLL"
                if cll_key in desired_payload:
                    desired_payload[cll_key] = 1  # Imposta _CLL a 1

                break
            else:
                # Se non è il device_name, cerca _TSP
                tsp_key = f"{key[:-4]}_TSP"  # Costruisci il _TSP basato sulla chiave
                if tsp_key in desired_payload:
                    tsp_value = desired_payload[tsp_key]
                    if (
                        isinstance(tsp_value, dict)
                        and "p" in tsp_value
                        and tsp_value["p"].get("k") == "TEMPORARY"
                        and tsp_value["p"].get("m") == 3
                        and tsp_value["p"].get("u") == 0
                    ):
                        tsp_value["p"]["v"] = int(
                            temperature * 10
                        )  # Aggiorna il valore 'v'

                # Aggiorna _CLL a 0 se prima era 1
                cll_key = f"{key[:-4]}_CLL"  # Costruisci la chiave _CLL
                if cll_key in desired_payload and desired_payload[cll_key] == 1:
                    desired_payload[cll_key] = 1  # Imposta _CLL a 0

                # Aggiorna _CPC a 0 se prima era 1
                cpc_key = f"{key[:-4]}_CPC"  # Costruisci la chiave _CPC
                if cpc_key in desired_payload and desired_payload[cpc_key] == 1:
                    desired_payload[cpc_key] = 1  # Imposta _CPC a 0

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

    async def generate_state_payload(self, payload, device_name, enable):
        "Aggiorna il payload del dispositivo solo per lo stato di accensione/spegnimento."
        current_timestamp = int(time.time() * 1000)  # Tempo attuale in millisecondi
        payload["timestamp"] = current_timestamp  # Aggiorna il timestamp nel payload

        desired_payload = payload.get("state", {}).get(
            "desired", {}
        )  # Accedi a payload["state"]["desired"]

        # Cerca il device nel payload basato sul nome
        for key, value in desired_payload.items():
            if key.endswith("_NAM") and value == device_name:
                base_key = key[:-4]  # Ottieni la chiave di base senza il suffisso

                # Aggiorna lo stato di accensione/spegnimento se fornito
                enable_key = f"{base_key}_ENB"
                if enable_key in desired_payload:
                    desired_payload[enable_key] = enable  # Imposta a 1 (on) o 0 (off)

                # Aggiorna _CLL se presente, impostandolo a 1
                cll_key = f"{base_key}_CLL"
                if cll_key in desired_payload:
                    desired_payload[cll_key] = 1  # Imposta _CLL a 1

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

        # "Aggiorna il payload del dispositivo con una nuova temperatura o stato di accensione/spegnimento"
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
        "Fetch the current device payload from the API."
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
                        return None
        except Exception as e:
            _LOGGER.error(f"Exception during payload retrieval: {e}")
            return None

    # Modifica la funzione per accettare altri argomenti tramite kwargs
    async def async_set_temperature(self, **kwargs):
        "Imposta la temperatura target del radiatore."
        temperature = kwargs.get("temperature")  # Estrae la temperatura dai kwargs

        username = self.hass.data[DOMAIN].get("username")
        password = self.hass.data[DOMAIN].get("password")

        token = await self.hass.async_add_executor_job(
            login_with_srp, username, password
        )
        envID = self.hass.data[DOMAIN].get("envID")

        if not token or not envID:
            _LOGGER.error("Token or envID not found in hass.data")
            return

        device_name = self._attr_name.replace("Radiator ", "")  # Use the device name

        # Function to handle token regeneration and payload retrieval
        async def retrieve_payload(token, envID):
            "Attempt to retrieve the payload, regenerate the token if it fails"
            payload = await self.get_current_payload(token, envID)
            if payload is None:
                # Regenerate token and retry
                token = await self.hass.async_add_executor_job(
                    login_with_srp, username, password
                )
                if not token:
                    _LOGGER.error("Failed to regenerate token")
                    return None, None
                # Try to retrieve payload again
                payload = await self.get_current_payload(token, envID)
            return token, payload

        # Retrieve the payload and handle token regeneration if necessary
        token, payload = await retrieve_payload(token, envID)

        if payload is None:
            _LOGGER.error(
                f"Failed to retrieve payload after token regeneration for {self._attr_name}"
            )
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
        else:
            _LOGGER.error(f"Failed to update temperature for {self._attr_name}")

    async def async_set_hvac_mode(self, hvac_mode):
        "Set new target HVAC mode."
        username = self.hass.data[DOMAIN].get("username")
        password = self.hass.data[DOMAIN].get("password")

        token = await self.hass.async_add_executor_job(
            login_with_srp, username, password
        )
        envID = self.hass.data[DOMAIN].get("envID")

        if not token or not envID:
            _LOGGER.error("Token or envID not found in hass.data")
            return

        if hvac_mode == HVACMode.OFF:
            _LOGGER.debug(f"Setting {self._radiator['serial']} to OFF")
            await self._set_radiator_state(False)

            device_name = self._attr_name.replace(
                "Radiator ", ""
            )  # Usa il nome del dispositivo

            # Ottieni il payload attuale del dispositivo dalle API
            payload = await self.get_current_payload(token, envID)

            if payload is None:
                _LOGGER.error(
                    f"Failed to retrieve current payload for {self._attr_name}"
                )
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

            device_name = self._attr_name.replace(
                "Radiator ", ""
            )  # Usa il nome del dispositivo

            # Ottieni il payload attuale del dispositivo dalle API
            payload = await self.get_current_payload(token, envID)

            if payload is None:
                _LOGGER.error(
                    f"Failed to retrieve current payload for {self._attr_name}"
                )
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
            _LOGGER.error(f"Failed to update HVAC mode for {self._attr_name}")

    async def _set_radiator_state(self, state):
        "Send request to set the radiator state."
        _LOGGER.debug(
            f"Setting radiator state: {self._radiator['serial']} to {'on' if state else 'off'}"
        )

        username = self.hass.data[DOMAIN].get("username")
        password = self.hass.data[DOMAIN].get("password")

        token = await self.hass.async_add_executor_job(
            login_with_srp, username, password
        )
        envID = self.hass.data[DOMAIN].get("envID")

        if not token or not envID:
            _LOGGER.error("Token or envID not found in hass.data")
            return

        device_name = self._attr_name.replace("Radiator ", "")  # Use the device name

        # Function to handle token regeneration and payload retrieval
        async def retrieve_payload(token, envID):
            "Attempt to retrieve the payload, regenerate the token if it fails."
            payload = await self.get_current_payload(token, envID)
            if payload is None:
                _LOGGER.warning(
                    f"Failed to retrieve current payload for {self._attr_name}. Regenerating token."
                )
                # Regenerate token and retry
                token = await self.hass.async_add_executor_job(
                    login_with_srp, username, password
                )
                if not token:
                    _LOGGER.error("Failed to regenerate token")
                    return None, None
                # Try to retrieve payload again
                payload = await self.get_current_payload(token, envID)
            return token, payload

        # Retrieve the payload and handle token regeneration if necessary
        token, payload = await retrieve_payload(token, envID)

        if payload is None:
            _LOGGER.error(
                f"Failed to retrieve payload after token regeneration for {self._attr_name}"
            )
            return

        # Aggiornamento del payload solo per lo stato
        updated_payload = await self.generate_state_payload(
            payload=payload,
            device_name=device_name,
            enable=1 if state else 0,  # Imposta enable in base allo stato
        )

        # Invia il nuovo payload aggiornato alle API
        success = await self._send_target_temperature_to_api(
            token, envID, updated_payload
        )
        if success:
            self._state = state  # Aggiorna lo stato interno del radiatore
            if state:
                self._attr_hvac_mode = HVACMode.HEAT  # Imposta lo stato HVAC a HEAT
            else:
                self._attr_hvac_mode = HVACMode.OFF  # Spegni l'HVAC se lo stato è off
        else:
            _LOGGER.error(f"Failed to update radiator state for {self._attr_name}")

    async def async_update(self):
        "Fetch new state data for this climate entity."
        _LOGGER.info(f"Updating radiator climate {self._attr_name}")

        # Recupera token e envID
        token = self.hass.data[DOMAIN].get("token")
        envID = self.hass.data[DOMAIN].get("envID")

        if not token or not envID:
            _LOGGER.error("Token or envID not found in hass.data")
            return

        # Function to handle token regeneration and payload retrieval
        async def retrieve_payload(token, envID):
            "Attempt to retrieve the payload, regenerate the token if it fails."
            payload = await self.get_current_payload(token, envID)
            if payload is None:
                _LOGGER.warning(
                    f"Failed to retrieve current payload for {self._attr_name}. Regenerating token."
                )
                # Regenerate token and retry
                token = await self.hass.async_add_executor_job(
                    login_with_srp,
                    self.hass.data[DOMAIN]["username"],
                    self.hass.data[DOMAIN]["password"],
                )
                if not token:
                    _LOGGER.error("Failed to regenerate token")
                    return None, None
                # Try to retrieve payload again
                payload = await self.get_current_payload(token, envID)
            return token, payload

        # Retrieve the payload and handle token regeneration if necessary
        token, payload = await retrieve_payload(token, envID)

        if payload is None:
            _LOGGER.error(
                f"Failed to retrieve payload after token regeneration for {self._attr_name}"
            )
            return

        # Cerca la temperatura nel payload (_TMP)
        device_name = self._attr_name.replace("Radiator ", "")
        desired_payload = payload.get("state", {}).get("desired", {})

        # Loop through payload items to find the matching device
        for key, value in desired_payload.items():
            if key.endswith("_NAM") and value == device_name:
                base_key = key[:-4]  # Ottieni la chiave di base
                tmp_key = f"{base_key}_TMP"
                msp_key = f"{base_key}_MSP"
                tsp_key = f"{base_key}_TSP"
                enb_key = f"{base_key}_ENB"  # Key for enabling state

                if tmp_key in desired_payload:
                    # Se il valore è None, invia una notifica e imposta a 0
                    tmp_value = desired_payload.get(tmp_key, 0)
                    retry_count = 0
                    max_retries = 5
                    while tmp_value is None and retry_count < max_retries:
                        retry_count += 1
                        _LOGGER.warning(
                            f"Attempt {retry_count}: Temperature is None for {self._attr_name}. Retrying..."
                        )
                        await asyncio.sleep(
                            1
                        )  # Wait before retrying (you can adjust the wait time)

                    if tmp_value is None:
                        _LOGGER.warning(
                            f"Received None for {self._attr_name}, setting temperature to 0"
                        )
                        self._current_temperature = 0

                        # Create a persistent notification
                        await self.hass.services.async_call(
                            "persistent_notification",
                            "create",
                            {
                                "title": f"Device {self._attr_name} Issue",
                                "message": "Temperature is set to 0 due to an invalid value received (None). Please check the device.",
                                "notification_id": f"radiator_{self._attr_name}_temperature_warning",
                            },
                        )
                    else:
                        self._current_temperature = tmp_value / 10  # In gradi Celsius

                        # Dismiss any existing persistent notification if the value is valid
                        await self.hass.services.async_call(
                            "persistent_notification",
                            "dismiss",
                            {
                                "notification_id": f"radiator_{self._attr_name}_temperature_warning",
                            },
                        )

                    # Check for _MSP, _TSP, and _CSP keys to find the setpoint
                    for sp_key in [msp_key, tsp_key]:
                        if sp_key in desired_payload:
                            sp_value = (
                                desired_payload[sp_key].get("p", {}).get("v", None)
                            )
                            if sp_value is not None:
                                self._target_temperature = (
                                    sp_value / 10
                                )  # Imposta il setpoint in gradi Celsius
                                _LOGGER.info(
                                    f"Setpoint for {self._attr_name} found: {self._target_temperature}"
                                )

                    # Check the _ENB key and set the state accordingly
                    if enb_key in desired_payload:
                        enb_value = desired_payload.get(enb_key, 0)
                        if enb_value == 0:
                            self._attr_hvac_mode = HVACMode.OFF
                        elif enb_value == 1:
                            self._attr_hvac_mode = HVACMode.HEAT

                break
