import time
from .const import DOMAIN, USER_POOL_ID, CLIENT_ID, REGION
import logging
from homeassistant.components.light import (
    LightEntity,
    ATTR_HS_COLOR,
    ATTR_BRIGHTNESS,
    SUPPORT_BRIGHTNESS,
    SUPPORT_COLOR,
)

from homeassistant.components.sensor import datetime
import aiohttp
import json
from warrant import Cognito
import re
from .device import RadiatorDevice
from .device_manager import device_manager
import asyncio
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    from .climate import RadiatorClimate  # Importa RadiatorClimate qui

    envID = config_entry.data["envID"]
    username = config_entry.data["username"]
    password = config_entry.data["password"]

    token = await hass.async_add_executor_job(login_with_srp, username, password)

    if token and envID:
        _LOGGER.debug("Token and envID successfully obtained. Retrieving sensors.")

        hass.data.setdefault(DOMAIN, {})
        hass.data[DOMAIN]["token"] = token
        hass.data[DOMAIN]["envID"] = envID
        hass.data[DOMAIN]["username"] = username
        hass.data[DOMAIN]["password"] = password

        devices = device_manager.get_devices()  # Ottieni i dispositivi dal manager
        _LOGGER.debug(
            f"Devices found: {[device.radiator['serial'] for device in devices]}"
        )

        if not devices:
            _LOGGER.error(
                "No devices found. Please ensure that climate entities are set up correctly."
            )
            return

        # Ottieni i dati delle luci
        radiators_lights = await get_sensor_data(token, envID)
        _LOGGER.info(f"Radiators lights data: {radiators_lights}")

        # Crea entità light
        lights = []
        for key, radiator in radiators_lights:  # Itera sulle tuple (key, value)
            if (
                isinstance(radiator, dict) and "serial" in radiator
            ):  # Verifica che il valore sia valido
                unique_id = f"{radiator['serial']}"
                lights.append(
                    RadiatorLight(
                        radiator,
                        unique_id,
                        unique_id=f"{radiator['serial']}_led",
                    )
                )
            else:
                _LOGGER.warning(
                    f"Skipping invalid radiator data for key {key}: {radiator}"
                )

        async_add_entities(lights)
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


async def get_sensor_data(token, envID):
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


import re


def extract_device_info(
    payload,
    nam_suffix="_NAM",
    led_suffix="_X_LED_MSP",  # Suffisso per luce
    led_enable_suffix="_X_LED_ENB",
    exclude_suffix="E_NAM",
):
    devices_info = []

    def find_device_keys(obj):
        if isinstance(obj, dict):
            for key, value in obj.items():
                # Verifica se il dispositivo ha un suffisso "_X_LED_ENB" (abilitazione della luce)
                if key.endswith(led_enable_suffix):
                    # Raccogli chiavi _NAM e aggiungi dettagli iniziali
                    if key.endswith(nam_suffix) and not key.startswith(exclude_suffix):
                        device_info = {
                            "serial": value,
                            "state": "OFF",  # Default a OFF
                            "color": {"h": 0, "s": 0, "v": 0},  # Default colore
                        }
                        devices_info.append((key, device_info))

                    # Gestisci chiave _X_LED_MSP per accensione e colore
                    if key.endswith(led_suffix) and isinstance(value, dict):
                        led_data = value.get("p", {})
                        # Stato accensione
                        device_info["state"] = "ON" if led_data.get("u") == 1 else "OFF"
                        # Colore HSV
                        color_data = led_data.get("v", {})
                        device_info["color"] = {
                            "h": color_data.get("h", 0),
                            "s": color_data.get("s", 0),
                            "v": color_data.get("v", 0),
                        }

                # Ricorsione per chiavi annidate
                find_device_keys(value)
        elif isinstance(obj, list):
            for item in obj:
                find_device_keys(item)

    # Esegui la ricerca nel payload
    find_device_keys(payload)
    return devices_info


class RadiatorLight(LightEntity):
    "Representation of a radiator light entity."

    def __init__(self, radiator, device, unique_id):
        self._radiator = radiator
        self._device = device  # Store device reference
        self._attr_name = f"{radiator['serial']} LED"
        self._attr_unique_id = unique_id
        self._attr_icon = "mdi:led-strip-variant"
        self._radiator_serial = radiator["serial"]
        self._model = radiator.get("model", "Modello Sconosciuto")
        self._attr_native_value = radiator.get("ip_address", "IP non disponibile")
        self._sw_version = radiator.get("firmware")
        self._attr_is_on = False  # Stato iniziale (spento)
        self._attr_hs_color = None  # Colore iniziale
        self._attr_brightness = 255  # Luminosità massima iniziale

    @property
    def native_value(self):
        return self._attr_native_value

    @property
    def unique_id(self):
        return self._attr_unique_id

    @property
    def device_info(self):
        """Associa il sensore al dispositivo climate con il seriale corrispondente."""
        return {
            "identifiers": {
                (DOMAIN, self._radiator["serial"])
            },  # Use device serial number
            "name": f"{self._radiator['serial']}",
            "model": self._radiator.get("model", "Unknown Model"),
            "manufacturer": "IRSAP",
            "sw_version": self._radiator.get("firmware", "Unknown Firmware"),
        }

    @property
    def is_on(self):
        return self._attr_is_on

    @property
    def hs_color(self):
        return self._attr_hs_color

    @property
    def brightness(self):
        return self._attr_brightness

    @property
    def supported_features(self):
        return SUPPORT_BRIGHTNESS | SUPPORT_COLOR

    async def async_turn_on(self, **kwargs):
        """Accende la luce e aggiorna i parametri come colore e luminosità."""
        await asyncio.sleep(1)
        # Leggi i parametri di colore e luminosità
        hs_color = kwargs.get(ATTR_HS_COLOR, self._attr_hs_color)
        brightness = kwargs.get(ATTR_BRIGHTNESS, self._attr_brightness)

        username = self.hass.data[DOMAIN].get("username")
        password = self.hass.data[DOMAIN].get("password")

        token = await self.hass.async_add_executor_job(
            login_with_srp, username, password
        )
        envID = self.hass.data[DOMAIN].get("envID")

        if not token or not envID:
            _LOGGER.error("Token or envID not found in hass.data")
            return

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

        updated_payload = await self.generate_device_payload(  # Add 'await' here if this method is async
            payload=payload,
            device_name=self._attr_name.replace("Radiator", "").strip(),
            light_state=True,  # La luce è accesa
            color=hs_color,
            brightness=brightness,
        )

        # Invia il nuovo payload aggiornato alle API
        success = await self._send_light_status_to_api(token, envID, updated_payload)
        if success:
            # Aggiorna lo stato interno
            self._attr_is_on = True
            self._attr_hs_color = hs_color
            self._attr_brightness = brightness
            self.async_write_ha_state()
        else:
            _LOGGER.error(f"Failed to update light for {self._attr_name}")

    async def async_turn_off(self, **kwargs):
        """Spegne la luce."""
        await asyncio.sleep(1)
        # Leggi i parametri di colore e luminosità
        hs_color = kwargs.get(ATTR_HS_COLOR, self._attr_hs_color)
        brightness = 0

        username = self.hass.data[DOMAIN].get("username")
        password = self.hass.data[DOMAIN].get("password")

        token = await self.hass.async_add_executor_job(
            login_with_srp, username, password
        )
        envID = self.hass.data[DOMAIN].get("envID")

        if not token or not envID:
            _LOGGER.error("Token or envID not found in hass.data")
            return

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

        updated_payload = await self.generate_device_payload(  # Add 'await' here if this method is async
            payload=payload,
            device_name=self._attr_name.replace("Radiator", "").strip(),
            light_state=False,  # La luce è spenta
            color=hs_color,
            brightness=brightness,
        )

        # Invia il nuovo payload aggiornato alle API
        success = await self._send_light_status_to_api(token, envID, updated_payload)
        if success:
            # Aggiorna lo stato interno
            self._attr_is_on = False
            self._attr_hs_color = hs_color
            self._attr_brightness = brightness
            self.async_write_ha_state()
        else:
            _LOGGER.error(f"Failed to update light for {self._attr_name}")

    async def _send_led_command(self, payload):
        """Invia il comando per gestire lo stato del LED."""
        key = f"{self._radiator_serial}_LED_MSP"  # Costruisci la chiave per il dispositivo
        # Implementa la chiamata API o il comando verso il radiatore
        await self._radiator.send_command(key, payload)

    async def async_update(self):
        if getattr(self, "_pending_update", False):
            # Evita l'aggiornamento se è in corso un'impostazione temperatura
            self._pending_update = False
            return
        _LOGGER.debug(f"Updating radiator climate {self._attr_name}")

        # Rimuove "Radiator" dal nome dell'entità, se presente, per facilitare il matching
        device_name = self._attr_name.replace("Radiator", "").strip()

        # Recupera token e envID
        username = self.hass.data[DOMAIN]["username"]
        password = self.hass.data[DOMAIN]["password"]
        envID = self.hass.data[DOMAIN].get("envID")

        retry_count = 0
        max_retries = 3
        tmp_value = None
        last_valid_brightness = (
            self._attr_brightness
        )  # Memorizza l'ultima brightness valida
        last_valid_hs_color = self._attr_hs_color  # Memorizza l'ultima hs_color valida

        while tmp_value is None and retry_count < max_retries:
            retry_count += 1
            _LOGGER.debug(
                f"Attempt {retry_count}: Retrieving payload for {self._attr_name}"
            )

            # Ottieni un nuovo token e payload ad ogni retry
            token = await self.hass.async_add_executor_job(
                login_with_srp, username, password
            )
            if not token or not envID:
                _LOGGER.error("Token or envID not found in hass.data")
                return

            payload = await self.get_current_payload(token, envID)
            if payload is None:
                _LOGGER.warning(
                    f"Failed to retrieve payload for {self._attr_name} on attempt {retry_count}"
                )
                await asyncio.sleep(1)  # Attende prima di riprovare
                continue

            # Accesso al desired_payload
            desired_payload = payload.get("state", {}).get("desired", {})
            for key, value in desired_payload.items():
                if key.endswith("_NAM") and value == device_name:
                    base_key = key[:-4]  # Ottieni la chiave base
                    msp_key = f"{base_key}_X_LED_MSP"
                    enb_key = f"{base_key}_X_LED_ENB"

                    # Ottieni colore e luminosità
                    msp_value = desired_payload.get(msp_key, None)
                    if (
                        msp_value["p"]["v"] is not None
                    ):  # Se il valore è valido, esci dal ciclo di retry
                        self._attr_hs_color = (
                            msp_value["p"]["v"]["h"],
                            msp_value["p"]["v"]["s"],
                        )
                        self._attr_brightness = msp_value["p"]["v"]["v"]
                    # Controlla e aggiorna modalità di funzionamento (es. HEAT, OFF)
                    if enb_key in desired_payload:
                        enb_value = desired_payload.get(enb_key, 0)
                        self._attr_is_on = 1 if enb_value == 1 else 0

                _LOGGER.debug(
                    f"Final state for {self._attr_name}: Color={self._attr_brightness}, ON/OFF mode={self._attr_is_on}"
                )

            if msp_value is None:
                _LOGGER.warning(
                    f"Light info is None for {self._attr_name}. Retrying..."
                )
                await asyncio.sleep(1)  # Attende prima di riprovare

        # Se la temperatura è None dopo i tentativi, registra un avviso e imposta a 0
        if msp_value is None:
            _LOGGER.warning(
                f"Light info for {self._attr_name} remains None after {retry_count} retries;"
            )
            self._attr_hs_color = last_valid_hs_color
            self._attr_brightness = last_valid_brightness
            await self.hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": f"Device {self._attr_name} Issue",
                    "message": "Light infos are set to previous state due to an invalid value received (None). Please check the device and try to reset it.",
                    "notification_id": f"radiator_{self._attr_name}_brightness_warning",
                },
            )
        else:
            await self.hass.services.async_call(
                "persistent_notification",
                "dismiss",
                {"notification_id": f"radiator_{self._attr_name}_brightness_warning"},
            )

    async def generate_device_payload(
        self, payload, device_name, light_state=None, color=None, brightness=None
    ):
        # Aggiorna il timestamp con il tempo attuale in millisecondi
        current_timestamp = int(time.time() * 1000)  # Tempo attuale in millisecondi
        payload["timestamp"] = current_timestamp  # Aggiorna il timestamp nel payload

        payload["clientId"] = (
            "app-now2-1.9.38-2143-ios-bdd093f2-8e08-4541-8a7e-800c23274f21"  # Fake clientId iOS
        )

        # "Aggiorna il payload del dispositivo con una nuova temperatura o stato di accensione/spegnimento"
        desired_payload = payload.get("state", {}).get(
            "desired", {}
        )  # Accedi a payload["state"]["desired"]

        timestamp_24h_future = int(time.time()) + 24 * 3600
        time_24h_future = time.strftime(
            "%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(timestamp_24h_future)
        )

        # Cerca il device nel payload basato sul nome
        for key, value in desired_payload.items():
            if key.endswith("_NAM") and value == device_name:
                base_key = key[:-4]  # Ottieni la chiave di base senza il suffisso

                # Aggiorna la temperatura se fornita
                if light_state is not None:
                    # Aggiorna _MSP
                    led_enb_key = f"{base_key}_LED_ENB"
                    desired_payload[led_enb_key] = 1 if light_state else 0

                    led_msp_key = f"{base_key}_LED_MSP"
                    if led_msp_key in desired_payload:
                        desired_payload[led_msp_key] = {
                            "p": {
                                # "k": "MANUAL",
                                # "m": 4,
                                "u": 0,
                                "v": {"h": color[0], "s": color[1], "v": brightness},
                            },
                            "m": "4",
                        }

        # Rimuovi 'sk' se esistente
        desired_payload.pop("sk", None)

        # Aggiorna il payload originale
        payload["state"]["desired"] = desired_payload

        # Riordina il payload secondo l'ordine richiesto
        ordered_payload = {
            # "version": payload.get("version"),
            # "sk": payload.get("sk"),
            "id": payload.get("id"),
            "clientId": payload.get("clientId"),
            "timestamp": payload.get("timestamp"),
            "version": payload.get("version"),
            "state": payload["state"],
        }

        return ordered_payload  # Restituisci il payload aggiornato

    # Funzione per inviare il payload aggiornato alle API
    async def _send_light_status_to_api(self, token, envID, updated_payload):
        "Invia il payload aggiornato alle API."
        url = "https://flqpp5xzjzacpfpgkloiiuqizq.appsync-api.eu-west-1.amazonaws.com/graphql"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        json_payload = json.dumps(updated_payload)
        # _LOGGER.info(f"Payload to send: {json_payload}")

        graphql_query = {
            "operationName": "UpdateShadow",
            "variables": {"envId": envID, "payload": json_payload},
            "query": (
                "mutation UpdateShadow($envId: ID!, $payload: AWSJSON!) {\n asyncUpdateShadow(envId: $envId, payload: $payload) {\n status\n code\n message\n payload\n __typename\n }\n}\n"
            ),
        }

        # _LOGGER.info(f"graphql_query to send: {graphql_query}")

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
