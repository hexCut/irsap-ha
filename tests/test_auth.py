"""Token cache and lock."""

import asyncio
from unittest.mock import MagicMock, patch

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


async def test_login_timeout_returns_none_and_releases_lock(hass):
    """A hanging Cognito call can't stall the caller (or the next one)."""
    store_credentials(hass, "u", "p")
    calls = []

    def hanging_login(username, password):
        calls.append(1)
        if len(calls) == 1:
            import time

            time.sleep(0.5)
            return "late-token"
        return "token-2"

    with (
        patch.object(auth, "LOGIN_TIMEOUT", 0.1),
        # a plain function, not a Mock, so it really runs in the executor
        patch.object(auth, "login_with_srp", new=hanging_login),
    ):
        assert await async_get_token(hass) is None
        # the lock was released: the next caller can log in
        assert await async_get_token(hass) == "token-2"
    assert len(calls) == 2


def test_login_uses_cognito_client_with_timeouts():
    with (
        patch.object(auth, "Cognito") as cognito,
        patch.object(auth.boto3, "client") as client,
    ):
        cognito.return_value.access_token = "tok"
        assert auth.login_with_srp("u", "p") == "tok"

    _, kwargs = client.call_args
    config = kwargs["config"]
    assert config.connect_timeout == auth.COGNITO_CONNECT_TIMEOUT
    assert config.read_timeout == auth.COGNITO_READ_TIMEOUT
    assert cognito.return_value.client is client.return_value
    cognito.return_value.authenticate.assert_called_once_with(password="p")


def _jwks_response(keys):
    response = MagicMock()
    response.json.return_value = {"keys": keys}
    return response


def test_login_fetches_jwks_with_timeout_and_caches_it():
    with (
        patch.object(auth, "Cognito") as cognito,
        patch.object(auth.boto3, "client"),
        patch.object(auth.requests, "get", return_value=_jwks_response(["k1"])) as get,
    ):
        cognito.return_value.access_token = "tok"
        assert auth.login_with_srp("u", "p") == "tok"
        assert auth.login_with_srp("u", "p") == "tok"

    get.assert_called_once()  # cached for the second login
    assert get.call_args.args == (auth.JWKS_URL,)
    assert get.call_args.kwargs["timeout"] == (
        auth.COGNITO_CONNECT_TIMEOUT,
        auth.COGNITO_READ_TIMEOUT,
    )
    # warrant uses the pre-fetched keys instead of its own requests.get
    assert cognito.return_value.pool_jwk == {"keys": ["k1"]}


def test_failed_login_refetches_jwks():
    """After a failure (e.g. AWS rotated the keys) the next login refetches them."""
    with (
        patch.object(auth, "Cognito") as cognito,
        patch.object(auth.boto3, "client"),
        patch.object(auth.requests, "get", return_value=_jwks_response(["k"])) as get,
    ):
        cognito.return_value.authenticate.side_effect = IndexError("unknown kid")
        assert auth.login_with_srp("u", "p") is None
        cognito.return_value.authenticate.side_effect = None
        cognito.return_value.access_token = "tok"
        assert auth.login_with_srp("u", "p") == "tok"
    assert get.call_count == 2


def test_jwks_timeout_fails_login_cleanly():
    with (
        patch.object(auth, "Cognito"),
        patch.object(auth.boto3, "client"),
        patch.object(
            auth.requests, "get", side_effect=auth.requests.Timeout("jwks timed out")
        ),
    ):
        assert auth.login_with_srp("u", "p") is None
    assert auth._jwks_cache is None
