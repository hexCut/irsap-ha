"""Shared Cognito access-token cache for the IRSAP integration."""

import logging
import time

from .const import DOMAIN, TOKEN_MAX_AGE

_LOGGER = logging.getLogger(__name__)


async def async_get_token(hass, login_func, force_refresh=False):
    """Return a valid access token, logging in again only when needed.

    ``login_func`` is the blocking ``login_with_srp(username, password)`` helper;
    it runs in the executor. The token is cached in ``hass.data[DOMAIN]`` together
    with the time it was obtained, and is reused until it is older than
    ``TOKEN_MAX_AGE`` or ``force_refresh`` is set (e.g. after an API error).
    """
    data = hass.data.setdefault(DOMAIN, {})
    token = data.get("token")
    obtained_at = data.get("token_obtained_at", 0)

    if (
        not force_refresh
        and token
        and time.monotonic() - obtained_at < TOKEN_MAX_AGE
    ):
        return token

    username = data.get("username")
    password = data.get("password")
    if not username or not password:
        _LOGGER.error("IRSAP credentials not found in hass.data")
        return None

    _LOGGER.debug("Obtaining a new IRSAP access token (forced: %s)", force_refresh)
    token = await hass.async_add_executor_job(login_func, username, password)
    if token:
        data["token"] = token
        data["token_obtained_at"] = time.monotonic()
    return token


def store_token(hass, token):
    """Store a token obtained elsewhere (e.g. during platform setup)."""
    if not token:
        return
    data = hass.data.setdefault(DOMAIN, {})
    data["token"] = token
    data["token_obtained_at"] = time.monotonic()
