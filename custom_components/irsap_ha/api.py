"""Calls to the IRSAP cloud API (AppSync GraphQL)."""

import asyncio
import contextvars
import copy
import functools
import json
import logging
import time

import aiohttp
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .auth import async_get_token
from .const import API_TIMEOUT, DOMAIN, WRITE_SETTLE_TIME

_LOGGER = logging.getLogger(__name__)

# Keys this module keeps in hass.data[DOMAIN]; async_unload_entry removes them.
WRITE_DATA_KEYS = ("write_lock", "last_write")

# True while a command decorated with serialize_writes is running
_writing = contextvars.ContextVar("irsap_writing", default=False)

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


# --- Commands: one read-modify-write at a time -------------------------------
#
# Every command reads the whole shadow, changes its own keys and writes the
# whole shadow back. Two commands running at the same time (e.g. an automation
# turning off every radiator) would both start from the same shadow, and the
# second write would undo the first. Commands therefore run one at a time, and
# each one builds on the previous write if the cloud doesn't reflect it yet.


def serialize_writes(method):
    """Run an entity command (read the shadow, change it, write it back) under
    a lock shared by every IRSAP entity. Don't call another decorated method
    from a decorated one: the lock is not re-entrant."""

    @functools.wraps(method)
    async def wrapper(self, *args, **kwargs):
        data = self.hass.data.setdefault(DOMAIN, {})
        lock = data.setdefault("write_lock", asyncio.Lock())
        async with lock:
            reset = _writing.set(True)
            try:
                return await method(self, *args, **kwargs)
            finally:
                _writing.reset(reset)

    return wrapper


def remember_write(hass, payload):
    """Keep the last payload written successfully, for the next command."""
    hass.data.setdefault(DOMAIN, {})["last_write"] = {
        "version": payload.get("version"),
        "payload": copy.deepcopy(payload),
        "at": time.monotonic(),
    }


def _base_for_write(hass, payload):
    """The shadow a command should change: the one just fetched, or the last
    one we wrote if the cloud still returns the version that write was based
    on (the write hasn't been applied yet)."""
    last = hass.data.get(DOMAIN, {}).get("last_write")
    if not last or time.monotonic() - last["at"] > WRITE_SETTLE_TIME:
        return payload
    if payload.get("version") != last["version"]:
        return payload
    _LOGGER.debug(
        "Shadow still at version %s right after a write: building on that write",
        payload.get("version"),
    )
    return copy.deepcopy(last["payload"])


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
    if payload is not None and _writing.get():
        payload = _base_for_write(hass, payload)
    return token, payload
