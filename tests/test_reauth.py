"""Re-authentication when IRSAP rejects the saved credentials."""

from datetime import timedelta
from unittest.mock import patch

from botocore.exceptions import ClientError
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.irsap_ha import auth
from custom_components.irsap_ha.auth import IrsapAuthError
from custom_components.irsap_ha.const import TOKEN_MAX_AGE


def _client_error(code):
    return ClientError({"Error": {"Code": code, "Message": code}}, "InitiateAuth")


def _reauth_flows(hass):
    return [
        flow
        for flow in hass.config_entries.flow.async_progress()
        if flow["context"]["source"] == SOURCE_REAUTH
    ]


# --- login_with_srp: which errors mean "wrong credentials" ---------------


@pytest.mark.parametrize(
    "code", ["NotAuthorizedException", "UserNotFoundException"]
)
def test_rejected_credentials_raise(code):
    with (
        patch.object(auth, "Cognito") as cognito,
        patch.object(auth.boto3, "client"),
    ):
        cognito.return_value.authenticate.side_effect = _client_error(code)
        with pytest.raises(IrsapAuthError):
            auth.login_with_srp("u", "p")


@pytest.mark.parametrize(
    "error",
    [_client_error("TooManyRequestsException"), ConnectionError("no network")],
)
def test_other_errors_are_transient(error):
    """Throttling or network problems don't ask the user to re-authenticate."""
    with (
        patch.object(auth, "Cognito") as cognito,
        patch.object(auth.boto3, "client"),
    ):
        cognito.return_value.authenticate.side_effect = error
        assert auth.login_with_srp("u", "p") is None


# --- coordinator --------------------------------------------------------


async def test_rejected_at_setup_starts_reauth(
    hass, config_entry, mock_login, mock_get_shadow
):
    mock_login.side_effect = IrsapAuthError("rejected")
    config_entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    assert len(_reauth_flows(hass)) == 1


async def test_rejected_when_token_expires_starts_reauth(
    hass, config_entry, mock_login, mock_get_shadow
):
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert _reauth_flows(hass) == []

    # password changed in the IRSAP app; the cached token expires
    mock_login.side_effect = IrsapAuthError("rejected")
    with patch.object(
        auth.time, "monotonic", return_value=auth.time.monotonic() + TOKEN_MAX_AGE + 1
    ):
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
        await hass.async_block_till_done()

    assert len(_reauth_flows(hass)) == 1
    assert "token" not in hass.data["irsap_ha"]


async def test_network_failure_does_not_start_reauth(
    hass, config_entry, mock_login, mock_get_shadow
):
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    mock_login.side_effect = None
    mock_login.return_value = None  # login failed for a transient reason
    mock_get_shadow.side_effect = None
    mock_get_shadow.return_value = None
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done()

    assert _reauth_flows(hass) == []
    assert hass.states.get("climate.bagno_radiator").state == "unavailable"


async def test_command_with_rejected_credentials_raises(
    hass, config_entry, mock_login, mock_get_shadow
):
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    mock_login.side_effect = IrsapAuthError("rejected")
    mock_get_shadow.side_effect = None
    mock_get_shadow.return_value = None  # the cached token is refused

    async def _no_sleep(*args):
        return None

    with (
        patch("custom_components.irsap_ha.climate.asyncio.sleep", _no_sleep),
        pytest.raises(HomeAssistantError),
    ):
        await hass.services.async_call(
            "climate",
            "set_temperature",
            {"entity_id": "climate.bagno_radiator", "temperature": 23},
            blocking=True,
        )


# --- reauth flow --------------------------------------------------------


async def test_reauth_flow(hass, config_entry, mock_login, mock_get_shadow):
    mock_login.side_effect = IrsapAuthError("rejected")
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    (flow,) = _reauth_flows(hass)

    def _login(username, password):
        if password != "new-secret":
            raise IrsapAuthError("rejected")
        return "token-new"

    mock_login.side_effect = _login
    # the config flow logs in through its own import of login_with_srp
    with patch(
        "custom_components.irsap_ha.config_flow._sync_login_with_srp",
        side_effect=_login,
    ):
        result = await hass.config_entries.flow.async_configure(flow["flow_id"])
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "reauth_confirm"
        assert result["description_placeholders"]["username"] == "user@example.com"

        # still the wrong password
        result = await hass.config_entries.flow.async_configure(
            flow["flow_id"], {"password": "still-wrong"}
        )
        assert result["errors"] == {"base": "invalid_credentials"}

        # the right one: entry updated and reloaded
        result = await hass.config_entries.flow.async_configure(
            flow["flow_id"], {"password": "new-secret"}
        )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data["password"] == "new-secret"
    assert config_entry.data["username"] == "user@example.com"
    assert config_entry.data["envID"] == "env-1"
    assert config_entry.state is ConfigEntryState.LOADED
