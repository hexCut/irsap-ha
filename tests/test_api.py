"""Calls to the IRSAP cloud API (GetShadow / UpdateShadow) and the retry helper."""

import json
from unittest.mock import patch

import aiohttp

from custom_components.irsap_ha import api
from custom_components.irsap_ha.api import (
    API_URL,
    async_fetch_shadow,
    async_get_shadow,
    async_update_shadow,
)
from custom_components.irsap_ha.auth import store_credentials


def _shadow_response(payload):
    """AppSync answer to GetShadow: the shadow is a JSON string inside JSON."""
    return {"data": {"getShadow": {"envId": "env-1", "payload": json.dumps(payload)}}}


def _sent_json(aioclient_mock, index=0):
    """Body of the index-th request recorded by the mocker."""
    _method, _url, data, _headers = aioclient_mock.mock_calls[index]
    return data


def _sent_headers(aioclient_mock, index=0):
    _method, _url, _data, headers = aioclient_mock.mock_calls[index]
    return headers


# --- GetShadow ---------------------------------------------------------------


async def test_get_shadow_returns_decoded_payload(hass, aioclient_mock, shadow):
    aioclient_mock.post(API_URL, json=_shadow_response(shadow))

    assert await async_get_shadow(hass, "tok", "env-1") == shadow

    body = _sent_json(aioclient_mock)
    assert body["operationName"] == "GetShadow"
    assert body["variables"] == {"envId": "env-1"}
    assert _sent_headers(aioclient_mock)["Authorization"] == "Bearer tok"


async def test_get_shadow_http_error_returns_none(hass, aioclient_mock):
    aioclient_mock.post(API_URL, status=401, text="Unauthorized")

    assert await async_get_shadow(hass, "expired", "env-1") is None


async def test_get_shadow_timeout_returns_none(hass, aioclient_mock):
    aioclient_mock.post(API_URL, exc=TimeoutError())

    assert await async_get_shadow(hass, "tok", "env-1") is None


async def test_get_shadow_connection_error_returns_none(hass, aioclient_mock):
    aioclient_mock.post(API_URL, exc=aiohttp.ClientConnectionError())

    assert await async_get_shadow(hass, "tok", "env-1") is None


async def test_get_shadow_graphql_error_returns_none(hass, aioclient_mock):
    """AppSync answers 200 with ``data: null`` when the query fails."""
    aioclient_mock.post(
        API_URL, json={"data": None, "errors": [{"message": "Unauthorized"}]}
    )

    assert await async_get_shadow(hass, "tok", "env-1") is None


async def test_get_shadow_payload_not_json_returns_none(hass, aioclient_mock):
    aioclient_mock.post(
        API_URL, json={"data": {"getShadow": {"envId": "env-1", "payload": "{oops"}}}
    )

    assert await async_get_shadow(hass, "tok", "env-1") is None


# --- UpdateShadow ------------------------------------------------------------


async def test_update_shadow_sends_payload_as_json_string(
    hass, aioclient_mock, shadow
):
    aioclient_mock.post(API_URL, json={"data": {"asyncUpdateShadow": {}}})

    assert await async_update_shadow(hass, "tok", "env-1", shadow) is True

    body = _sent_json(aioclient_mock)
    assert body["operationName"] == "UpdateShadow"
    assert body["variables"]["envId"] == "env-1"
    # AWSJSON: the payload travels as a string, not as a nested object
    assert isinstance(body["variables"]["payload"], str)
    assert json.loads(body["variables"]["payload"]) == shadow
    assert _sent_headers(aioclient_mock)["Authorization"] == "Bearer tok"


async def test_update_shadow_http_error_returns_false(
    hass, aioclient_mock, shadow, caplog
):
    aioclient_mock.post(API_URL, status=500, text="boom")

    assert await async_update_shadow(hass, "tok", "env-1", shadow) is False
    assert "500" in caplog.text


async def test_update_shadow_timeout_returns_false(hass, aioclient_mock, shadow):
    aioclient_mock.post(API_URL, exc=TimeoutError())

    assert await async_update_shadow(hass, "tok", "env-1", shadow) is False


# --- async_fetch_shadow: cached token, one re-login on failure ----------------


async def test_fetch_uses_cached_token(hass, mock_login, shadow):
    store_credentials(hass, "u", "p")
    with patch.object(api, "async_get_shadow", return_value=shadow) as get:
        token, payload = await async_fetch_shadow(hass, "env-1")

    assert (token, payload) == ("token-1", shadow)
    assert get.call_count == 1
    assert mock_login.call_count == 1


async def test_fetch_relogs_once_after_a_failure(hass, mock_login, shadow):
    """A rejected token (e.g. expired early) triggers exactly one new login."""
    store_credentials(hass, "u", "p")
    with patch.object(api, "async_get_shadow", side_effect=[None, shadow]) as get:
        token, payload = await async_fetch_shadow(hass, "env-1")

    assert (token, payload) == ("token-2", shadow)
    assert [c.args[1] for c in get.call_args_list] == ["token-1", "token-2"]
    assert mock_login.call_count == 2


async def test_fetch_gives_up_after_second_failure(hass, mock_login):
    store_credentials(hass, "u", "p")
    with patch.object(api, "async_get_shadow", return_value=None) as get:
        token, payload = await async_fetch_shadow(hass, "env-1")

    assert payload is None
    assert token == "token-2"
    assert get.call_count == 2


async def test_fetch_without_token_skips_the_api(hass):
    """No credentials (or login failed): no request is sent at all."""
    with patch.object(api, "async_get_shadow") as get:
        assert await async_fetch_shadow(hass, "env-1") == (None, None)
    get.assert_not_called()


async def test_fetch_relogin_failure_returns_none(hass, shadow):
    store_credentials(hass, "u", "p")
    with (
        patch(
            "custom_components.irsap_ha.auth.login_with_srp",
            side_effect=["token-1", None],
        ),
        patch.object(api, "async_get_shadow", return_value=None) as get,
    ):
        assert await async_fetch_shadow(hass, "env-1") == (None, None)
    assert get.call_count == 1
