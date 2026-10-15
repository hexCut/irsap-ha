"""Calls to the IRSAP cloud API (AppSync GraphQL)."""

import json
import logging

import aiohttp
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .auth import async_get_token
from .const import API_TIMEOUT

_LOGGER = logging.getLogger(__name__)

API_URL = (
    "https://flqpp5xzjzacpfpgkloiiuqizq.appsync-api.eu-west-1.amazonaws.com/graphql"
)

GET_SHADOW_QUERY = "query GetShadow($envId: ID!) {\n  getShadow(envId: $envId) {\n    envId\n    payload\n    __typename\n  }\n}\n"

UPDATE_SHADOW_MUTATION = "mutation UpdateShadow($envId: ID!, $payload: AWSJSON!) {\n asyncUpdateShadow(envId: $envId, payload: $payload) {\n status\n code\n message\n payload\n __typename\n }\n}\n"


def _headers(token):
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


async def async_get_shadow(hass, token, envID):
    "Fetch the environment shadow; return the decoded payload or None."
    graphql_query = {
        "operationName": "GetShadow",
        "variables": {"envId": envID},
        "query": GET_SHADOW_QUERY,
    }
    session = async_get_clientsession(hass)
    try:
        async with session.post(
            API_URL,
            json=graphql_query,
            headers=_headers(token),
            timeout=aiohttp.ClientTimeout(total=API_TIMEOUT),
        ) as response:
            if response.status != 200:
                _LOGGER.debug(f"GetShadow returned HTTP {response.status}")
                return None
            data = await response.json()
            return json.loads(data["data"]["getShadow"]["payload"])
    except Exception as e:
        _LOGGER.debug(f"GetShadow failed: {e!r}")
        return None


async def async_update_shadow(hass, token, envID, updated_payload):
    "Send an updated shadow payload; return True on HTTP 200."
    graphql_query = {
        "operationName": "UpdateShadow",
        "variables": {"envId": envID, "payload": json.dumps(updated_payload)},
        "query": UPDATE_SHADOW_MUTATION,
    }
    session = async_get_clientsession(hass)
    try:
        async with session.post(
            API_URL,
            json=graphql_query,
            headers=_headers(token),
            timeout=aiohttp.ClientTimeout(total=API_TIMEOUT),
        ) as response:
            if response.status == 200:
                return True
            _LOGGER.error(
                f"API request error: {response.status} - {await response.text()}"
            )
            return False
    except Exception as e:
        _LOGGER.error(f"Error sending payload to API: {e!r}")
        return False


async def async_fetch_shadow(hass, envID):
    """Fetch the shadow with the cached token; on failure log in again and retry.

    Returns ``(token, payload)``; ``payload`` is None if both attempts failed.
    The token is returned so write paths can reuse it for the UpdateShadow call.
    """
    token = await async_get_token(hass)
    if not token:
        return None, None
    payload = await async_get_shadow(hass, token, envID)
    if payload is None:
        # Il token potrebbe essere scaduto o rifiutato: ne chiede uno nuovo e riprova
        token = await async_get_token(hass, failed_token=token)
        if not token:
            return None, None
        payload = await async_get_shadow(hass, token, envID)
    return token, payload
