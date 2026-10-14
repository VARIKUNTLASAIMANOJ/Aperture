"""
Configuration mistakes must be caught by shape, before a call is dispatched.

The real failure this covers: `LIVEKIT_SIP_TRUNK_ID` was set to a SIP endpoint
hostname rather than a trunk id. LiveKit accepted the agent dispatch, the agent
joined and started greeting an empty room, and only the subsequent dial failed
— with `twirp error unknown: object cannot be found`, which names nothing.
"""

from __future__ import annotations

import pytest

from voice.dispatch import telephony_configured, trunk_id_problem


@pytest.fixture(autouse=True)
def _livekit_creds(monkeypatch):
    monkeypatch.setenv("LIVEKIT_URL", "wss://example.livekit.cloud")
    monkeypatch.setenv("LIVEKIT_API_KEY", "APIxxxx")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "secret")


def test_a_real_trunk_id_passes(monkeypatch):
    monkeypatch.setenv("LIVEKIT_SIP_TRUNK_ID", "ST_abc123def456")
    assert trunk_id_problem() is None
    assert telephony_configured()


def test_empty_trunk_is_reported(monkeypatch):
    monkeypatch.setenv("LIVEKIT_SIP_TRUNK_ID", "")
    assert "empty" in (trunk_id_problem() or "")
    assert not telephony_configured()


@pytest.mark.parametrize("pasted", [
    "sip:onboard-nsp9rk9n.sip.livekit.cloud",
    "onboard-nsp9rk9n.sip.livekit.cloud",
    "wss://onboard-nsp9rk9n.livekit.cloud",
])
def test_a_sip_endpoint_is_not_a_trunk_id(monkeypatch, pasted):
    """The exact mistake that produced a 404 mid-call."""
    monkeypatch.setenv("LIVEKIT_SIP_TRUNK_ID", pasted)
    problem = trunk_id_problem()
    assert problem and "not a trunk id" in problem
    assert "ST_" in problem                 # says what a correct value looks like
    assert not telephony_configured()


def test_arbitrary_junk_is_reported(monkeypatch):
    monkeypatch.setenv("LIVEKIT_SIP_TRUNK_ID", "my-trunk")
    problem = trunk_id_problem()
    assert problem and "ST_" in problem
    assert not telephony_configured()


def test_missing_livekit_credentials_fail_before_the_trunk(monkeypatch):
    monkeypatch.setenv("LIVEKIT_SIP_TRUNK_ID", "ST_abc123")
    monkeypatch.delenv("LIVEKIT_API_KEY", raising=False)
    assert not telephony_configured()


@pytest.mark.asyncio
async def test_place_call_refuses_before_dispatching_an_agent(monkeypatch):
    """
    No LiveKit session may be created with a bad trunk. The old behaviour
    dispatched an agent that talked to nobody and billed for the privilege.
    """
    import voice.dispatch as dispatch

    monkeypatch.setenv("LIVEKIT_SIP_TRUNK_ID", "sip:foo.sip.livekit.cloud")

    created = []
    monkeypatch.setattr(
        "livekit.api.LiveKitAPI",
        lambda **kw: created.append(kw) or pytest.fail("LiveKitAPI must not be constructed"),
    )

    with pytest.raises(dispatch.TelephonyNotConfigured) as exc:
        await dispatch.place_call(
            thread_id="t1", call_id=1, call_type="INITIAL",
            phone_number="+919876543210", state={},
        )
    assert "not a trunk id" in str(exc.value)
    assert created == []
