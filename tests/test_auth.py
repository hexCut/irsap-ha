"""Token cache and lock."""

import asyncio
from unittest.mock import patch

from custom_components.irsap_ha import auth
from custom_components.irsap_ha.auth import async_get_token, store_credentials
from custom_components.irsap_ha.const import DOMAIN, TOKEN_MAX_AGE


async def test_token_is_reused(hass, mock_login):
    store_credentials(hass, "u", "p")
    assert await async_get_token(hass) == "token-1"
    assert await async_get_token(hass) == "token-1"
    assert mock_login.call_count == 1


async def test_token_expires(hass, mock_login):
    store_credentials(hass, "u", "p")
    with patch.object(auth.time, "monotonic", return_value=1000.0):
        assert await async_get_token(hass) == "token-1"
    with patch.object(auth.time, "monotonic", return_value=1000.0 + TOKEN_MAX_AGE + 1):
        assert await async_get_token(hass) == "token-2"
    assert mock_login.call_count == 2


async def test_concurrent_first_login_runs_once(hass):
    """N entities asking for a token at the same time trigger one SRP login."""
    store_credentials(hass, "u", "p")
    calls = []

    def slow_login(username, password):
        calls.append(1)
        import time

        time.sleep(0.05)
        return "token-1"

    with patch.object(auth, "login_with_srp", side_effect=slow_login):
        tokens = await asyncio.gather(*(async_get_token(hass) for _ in range(5)))
    assert tokens == ["token-1"] * 5
    assert len(calls) == 1


async def test_concurrent_forced_refresh_runs_once(hass, mock_login):
    """Several callers reporting the same rejected token cause one new login."""
    store_credentials(hass, "u", "p")
    old = await async_get_token(hass)
    tokens = await asyncio.gather(
        *(async_get_token(hass, failed_token=old) for _ in range(5))
    )
    assert tokens == ["token-2"] * 5
    assert mock_login.call_count == 2


async def test_failed_token_already_replaced(hass, mock_login):
    """A caller holding an old rejected token gets the current one, no login."""
    store_credentials(hass, "u", "p")
    await async_get_token(hass)
    await async_get_token(hass, failed_token="token-1")  # -> token-2
    assert await async_get_token(hass, failed_token="token-1") == "token-2"
    assert mock_login.call_count == 2


async def test_missing_credentials(hass, mock_login):
    hass.data.pop(DOMAIN, None)
    assert await async_get_token(hass) is None
    assert mock_login.call_count == 0
