"""Cognito login and shared access-token cache for the IRSAP integration."""

import asyncio
import logging
import time

import boto3
from botocore.config import Config
from warrant import Cognito

from .const import (
    CLIENT_ID,
    COGNITO_CONNECT_TIMEOUT,
    COGNITO_READ_TIMEOUT,
    DOMAIN,
    LOGIN_TIMEOUT,
    REGION,
    TOKEN_MAX_AGE,
    USER_POOL_ID,
)

_LOGGER = logging.getLogger(__name__)

# boto3 waits up to 60 s per call by default and retries; bound it instead
COGNITO_CLIENT_CONFIG = Config(
    connect_timeout=COGNITO_CONNECT_TIMEOUT,
    read_timeout=COGNITO_READ_TIMEOUT,
    retries={"max_attempts": 2},
)

# Keys this module keeps in hass.data[DOMAIN]; async_unload_entry removes them.
AUTH_DATA_KEYS = ("username", "password", "token", "token_obtained_at", "token_lock")


def login_with_srp(username, password):
    "Log in and obtain the access token using Warrant (blocking)."
    try:
        u = Cognito(USER_POOL_ID, CLIENT_ID, username=username, user_pool_region=REGION)
        # warrant builds its boto3 client without timeouts; use one that has them
        u.client = boto3.client(
            "cognito-idp", region_name=REGION, config=COGNITO_CLIENT_CONFIG
        )
        u.authenticate(password=password)
        _LOGGER.debug("Cognito SRP login succeeded")
        return u.access_token
    except Exception as e:
        _LOGGER.error(f"Error during login: {e}")
        return None


def store_credentials(hass, username, password):
    """Remember the credentials used to obtain new tokens."""
    data = hass.data.setdefault(DOMAIN, {})
    data["username"] = username
    data["password"] = password


async def async_get_token(hass, failed_token=None):
    """Return a valid access token, logging in again only when needed.

    The token is cached in ``hass.data[DOMAIN]`` and reused until it is older
    than ``TOKEN_MAX_AGE``. Pass ``failed_token`` when an API call made with
    that token failed: a new login happens only if the cached token is still
    that one, so when several callers fail at the same time just one of them
    logs in and the others get the new token. A lock makes sure only one SRP
    login runs at a time.
    """
    data = hass.data.setdefault(DOMAIN, {})
    lock = data.setdefault("token_lock", asyncio.Lock())

    async with lock:
        token = data.get("token")
        age = time.monotonic() - data.get("token_obtained_at", 0)
        if token and age < TOKEN_MAX_AGE and (
            failed_token is None or token != failed_token
        ):
            return token

        username = data.get("username")
        password = data.get("password")
        if not username or not password:
            _LOGGER.error("IRSAP credentials not found in hass.data")
            return None

        _LOGGER.debug(
            "Obtaining a new IRSAP access token (%s)",
            "previous token rejected" if failed_token else "no valid cached token",
        )
        try:
            token = await asyncio.wait_for(
                hass.async_add_executor_job(login_with_srp, username, password),
                LOGIN_TIMEOUT,
            )
        except TimeoutError:
            _LOGGER.warning("IRSAP login timed out after %s seconds", LOGIN_TIMEOUT)
            return None
        if token:
            data["token"] = token
            data["token_obtained_at"] = time.monotonic()
        return token
