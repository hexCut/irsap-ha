import logging
import aiohttp
from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.data_entry_flow import FlowResult
import voluptuous as vol
from .const import DOMAIN, USER_POOL_ID, CLIENT_ID, REGION
from warrant import Cognito
import asyncio

_LOGGER = logging.getLogger(__name__)

class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    "Handle a config flow for radiators integration."

    VERSION = 1

    async def async_step_user(self, user_input=None) -> FlowResult:
        "Handle the initial step."
        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(
                    {
                        vol.Required("username"): str,
                        vol.Required("password"): str,
                    }
                ),
            )

        # Estrazione delle credenziali dall'input dell'utente
        username = user_input["username"]
        password = user_input["password"]

        # Chiamiamo la funzione per ottenere il token e l'envID in modo asincrono
        token = await self.hass.async_add_executor_job(
            login_with_srp, username, password
        )

        if token is None:
            _LOGGER.error("Login failed, invalid credentials.")
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(
                    {
                        vol.Required("username"): str,
                        vol.Required("password"): str,
                    }
                ),
                errors={"base": "invalid_credentials"},
            )

        envID = await self.async_get_envID(username, password, token)

        if envID is None:
            _LOGGER.error("Failed to obtain envID.")
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(
                    {
                        vol.Required("username"): str,
                        vol.Required("password"): str,
                    }
                ),
                errors={"base": "envid_failed"},
            )

        # Se tutto è andato bene, salviamo l'entry
        return self.async_create_entry(
            title=username,
            data={
                "username": username,
                "password": password,
                "token": token,
                "envID": envID,
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return RadiatorsIntegrationOptionsFlow(config_entry)

    async def async_get_envID(self, username, password, token):
        """Asynchronous method to get envID."""
        return await self.hass.async_add_executor_job(
            envid_with_srp, username, password, token
        )

class RadiatorsIntegrationOptionsFlow(config_entries.OptionsFlow):
    "Handle the options flow for the integration."

    def __init__(self, config_entry):
        "Initialize the options flow."
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        "Manage the options."
        if user_input is not None:
            # Update the config entry options with new values
            return self.async_create_entry(title="", data=user_input)

        # Define the schema for the options form
        options_schema = vol.Schema(
            {
                vol.Required(
                    "username", default=self.config_entry.data.get("username")
                ): str,
                vol.Required(
                    "password", default=self.config_entry.data.get("password")
                ): str,
            }
        )

        return self.async_show_form(step_id="init", data_schema=options_schema)

    async def _update_options(self, user_input):
        "Update config entry options and reload entities."
        # Aggiorna le opzioni con le nuove credenziali
        self.hass.config_entries.async_update_entry(self.config_entry, data=user_input)

        # Ottieni il registro delle entità
        entity_registry = er.async_get(self.hass)

        # Elimina le entità esistenti create dall'integrazione
        entities = er.async_entries_for_config_entry(
            entity_registry, self.config_entry.entry_id
        )
        for entity in entities:
            entity_registry.async_remove(entity.entity_id)

        return self.async_create_entry(title="", data=user_input)

async def login_with_srp(username, password):
    "Log in and obtain the access token using Warrant."
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _sync_login_with_srp, username, password)

def _sync_login_with_srp(username, password):
    """Synchronous function to log in using Warrant."""
    try:
        u = Cognito(USER_POOL_ID, CLIENT_ID, username=username, user_pool_region=REGION)
        u.authenticate(password=password)
        _LOGGER.debug(f"Access Token: {u.access_token}")
        return u.access_token
    except Exception as e:
        _LOGGER.error(f"Error during login: {e}")
        return None

async def envid_with_srp(username, password, token):
    "Login and obtain the envID using Warrant."
    async with aiohttp.ClientSession() as session:
        url = "https://flqpp5xzjzacpfpgkloiiuqizq.appsync-api.eu-west-1.amazonaws.com/graphql"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        graphql_query = {
            "operationName": "ListEnvironments",
            "variables": {},
            "query": "query ListEnvironments {\n listEnvironments {\n environments {\n envId\n envName\n userRole\n __typename\n }\n __typename\n }\n}\n",
        }

        try:
            async with session.post(url, headers=headers, json=graphql_query) as response:
                if response.status == 200:
                    data = await response.json()
                    envId = data["data"]["listEnvironments"]["environments"][0]["envId"]
                    _LOGGER.debug(f"envId retrieved from API: {envId}")
                    return envId
                else:
                    _LOGGER.error(f"API request error: {response.status}")
                    return None
        except Exception as e:
            _LOGGER.error(f"Error during API call: {e}")
            return None
