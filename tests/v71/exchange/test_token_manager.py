"""Unit tests for ``src/core/v71/exchange/token_manager.py``.

Spec sources:
  - docs/v71/06_AGENTS_SPEC.md §5 Test Strategy verification (22 cases)
  - docs/v71/12_SECURITY.md §6 (token plaintext must never be logged)
  - docs/v71/KIWOOM_API_ANALYSIS.md §1 (au10001 OAuth contract)
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from src.core.v71.exchange.token_manager import (
    DEFAULT_REFRESH_WINDOW_SECONDS,
    KST,
    LIVE_BASE_URL,
    PAPER_BASE_URL,
    V71TokenAuthError,
    V71TokenInfo,
    V71TokenManager,
    V71TokenRequestError,
    _mask_token,
)

# ---------------------------------------------------------------------------
# Group 1 -- happy path
# ---------------------------------------------------------------------------


async def test_get_token_first_call_issues_and_caches(
    make_transport, make_token_response, fixed_clock_utc,
):
    transport = make_transport([{"status": 200, "json": make_token_response(token="AAAA1111bbbbcccc")}])
    async with httpx.AsyncClient(transport=transport) as client:
        mgr = V71TokenManager(
            app_key="ak", app_secret="as", is_paper=True,
            http_client=client, clock=fixed_clock_utc,
        )
        token = await mgr.get_token()
        assert token == "AAAA1111bbbbcccc"
        assert mgr.current_token is not None
        assert transport.calls == 1


async def test_get_token_cached_within_window(
    make_transport, make_token_response, fixed_clock_utc,
):
    # 24h TTL, refresh window 5m -- still cached after 60s.
    transport = make_transport([{"status": 200, "json": make_token_response(ttl_seconds=86400)}])
    async with httpx.AsyncClient(transport=transport) as client:
        mgr = V71TokenManager(
            app_key="k", app_secret="s", is_paper=True,
            http_client=client, clock=fixed_clock_utc,
        )
        t1 = await mgr.get_token()
        fixed_clock_utc.advance(seconds=60)
        t2 = await mgr.get_token()
        assert t1 == t2
        assert transport.calls == 1


async def test_refresh_force_issues_new(
    make_transport, make_token_response, fixed_clock_utc,
):
    transport = make_transport([
        {"status": 200, "json": make_token_response(token="FIRST123abcdEFGH")},
        {"status": 200, "json": make_token_response(token="SECOND12abcdEFGH")},
    ])
    async with httpx.AsyncClient(transport=transport) as client:
        mgr = V71TokenManager(
            app_key="k", app_secret="s", is_paper=True,
            http_client=client, clock=fixed_clock_utc,
        )
        t1 = await mgr.get_token()
        info = await mgr.refresh()
        assert t1 == "FIRST123abcdEFGH"
        assert info.token == "SECOND12abcdEFGH"
        assert mgr.current_token is info
        assert transport.calls == 2


# ---------------------------------------------------------------------------
# Group 2 -- concurrency
# ---------------------------------------------------------------------------


async def test_get_token_single_flight_under_concurrent_calls(
    make_transport, make_token_response, fixed_clock_utc,
):
    transport = make_transport([{"status": 200, "json": make_token_response()}])
    async with httpx.AsyncClient(transport=transport) as client:
        mgr = V71TokenManager(
            app_key="k", app_secret="s", is_paper=True,
            http_client=client, clock=fixed_clock_utc,
        )
        results = await asyncio.gather(*[mgr.get_token() for _ in range(100)])
        assert len(set(results)) == 1
        assert transport.calls == 1, "double-checked locking must single-flight refresh"


async def test_concurrent_refresh_after_window_opens(
    make_transport, make_token_response, fixed_clock_utc, kst,
):
    # Anchor expires_at to the fake clock so refresh-window math is deterministic.
    now_fake = fixed_clock_utc()
    transport = make_transport([
        {"status": 200, "json": make_token_response(
            token="EARLY123abcdABCD",
            expires_at=(now_fake + timedelta(seconds=600)).astimezone(kst),
        )},
        {"status": 200, "json": make_token_response(
            token="LATER123abcdABCD",
            expires_at=(now_fake + timedelta(seconds=950)).astimezone(kst),
        )},
    ])
    async with httpx.AsyncClient(transport=transport) as client:
        mgr = V71TokenManager(
            app_key="k", app_secret="s", is_paper=True,
            http_client=client, clock=fixed_clock_utc,
        )
        await mgr.get_token()
        # Step well into the refresh window (TTL 600, window 300 -> 350s in).
        fixed_clock_utc.advance(seconds=350)
        results = await asyncio.gather(*[mgr.get_token() for _ in range(50)])
        assert len(set(results)) == 1
        assert results[0] == "LATER123abcdABCD"
        assert transport.calls == 2


# ---------------------------------------------------------------------------
# Group 3 -- time-dependent behaviour
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "remaining_seconds,window,expect_refresh",
    [
        (301, 300, False),   # outside window
        (300, 300, True),    # boundary -- threshold inclusive
        (60, 300, True),     # inside window
        (0, 300, True),      # already expired
    ],
)
async def test_should_refresh_at_boundary(
    remaining_seconds, window, expect_refresh,
):
    now = datetime(2026, 4, 27, 0, 0, tzinfo=timezone.utc)
    info = V71TokenInfo(
        token="WQJaXXXXabcdABCD",
        token_type="bearer",
        expires_at=now + timedelta(seconds=remaining_seconds),
        issued_at=now,
        is_paper=False,
    )
    assert info.should_refresh(window_seconds=window, now=now) is expect_refresh


async def test_get_token_after_full_expiry(
    make_transport, make_token_response, fixed_clock_utc, kst,
):
    now_fake = fixed_clock_utc()
    transport = make_transport([
        {"status": 200, "json": make_token_response(
            token="FIRST111abcdABCD",
            expires_at=(now_fake + timedelta(seconds=120)).astimezone(kst),
        )},
        {"status": 200, "json": make_token_response(
            token="SECOND2abcdABCD8",
            expires_at=(now_fake + timedelta(seconds=320)).astimezone(kst),
        )},
    ])
    async with httpx.AsyncClient(transport=transport) as client:
        mgr = V71TokenManager(
            app_key="k", app_secret="s", is_paper=True,
            http_client=client, clock=fixed_clock_utc,
            refresh_window_seconds=10,
        )
        first = await mgr.get_token()
        fixed_clock_utc.advance(seconds=200)  # past first expiry
        second = await mgr.get_token()
        assert first == "FIRST111abcdABCD"
        assert second == "SECOND2abcdABCD8"
        assert transport.calls == 2


# ---------------------------------------------------------------------------
# Group 4 -- response validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "missing_key",
    [
        "token",
        "expires_dt",
    ],
)
async def test_response_missing_required_field_raises(
    make_transport, make_token_response, fixed_clock_utc, missing_key,
):
    payload = make_token_response()
    payload.pop(missing_key)
    transport = make_transport([{"status": 200, "json": payload}])
    async with httpx.AsyncClient(transport=transport) as client:
        mgr = V71TokenManager(
            app_key="k", app_secret="s", is_paper=True,
            http_client=client, clock=fixed_clock_utc,
        )
        with pytest.raises(V71TokenAuthError):
            await mgr.get_token()


@pytest.mark.parametrize("bad_format", ["abc", "", "2026-04-27", "20269999999999"])
async def test_invalid_expires_dt_format(
    make_transport, make_token_response, fixed_clock_utc, bad_format,
):
    payload = make_token_response()
    payload["expires_dt"] = bad_format
    transport = make_transport([{"status": 200, "json": payload}])
    async with httpx.AsyncClient(transport=transport) as client:
        mgr = V71TokenManager(
            app_key="k", app_secret="s", is_paper=True,
            http_client=client, clock=fixed_clock_utc,
        )
        with pytest.raises(V71TokenAuthError):
            await mgr.get_token()


async def test_return_code_nonzero(
    make_transport, make_token_response, fixed_clock_utc,
):
    payload = make_token_response(return_code=8030)
    transport = make_transport([{"status": 200, "json": payload}])
    async with httpx.AsyncClient(transport=transport) as client:
        mgr = V71TokenManager(
            app_key="k", app_secret="s", is_paper=True,
            http_client=client, clock=fixed_clock_utc,
        )
        with pytest.raises(V71TokenAuthError):
            await mgr.get_token()


@pytest.mark.parametrize("status_code", [400, 401, 429, 500, 503])
async def test_http_error_raises_request_error(
    make_transport, fixed_clock_utc, status_code,
):
    transport = make_transport([{"status": status_code, "json": {"return_msg": "denied"}}])
    async with httpx.AsyncClient(transport=transport) as client:
        mgr = V71TokenManager(
            app_key="k", app_secret="s", is_paper=True,
            http_client=client, clock=fixed_clock_utc,
        )
        with pytest.raises(V71TokenRequestError):
            await mgr.get_token()


async def test_transport_error_raises_request_error(
    make_transport, fixed_clock_utc,
):
    transport = make_transport([{"raise": httpx.ConnectError("boom")}])
    async with httpx.AsyncClient(transport=transport) as client:
        mgr = V71TokenManager(
            app_key="k", app_secret="s", is_paper=True,
            http_client=client, clock=fixed_clock_utc,
        )
        with pytest.raises(V71TokenRequestError):
            await mgr.get_token()


# ---------------------------------------------------------------------------
# Group 5 -- revoke
# ---------------------------------------------------------------------------


async def test_revoke_clears_state_and_calls_server(
    make_transport, make_token_response, fixed_clock_utc,
):
    transport = make_transport([
        {"status": 200, "json": make_token_response()},
        {"status": 200, "json": {"return_code": 0}},
    ])
    async with httpx.AsyncClient(transport=transport) as client:
        mgr = V71TokenManager(
            app_key="k", app_secret="s", is_paper=True,
            http_client=client, clock=fixed_clock_utc,
        )
        await mgr.get_token()
        await mgr.revoke()
        assert mgr.current_token is None
        assert transport.calls == 2


async def test_revoke_continues_on_server_failure(
    make_transport, make_token_response, fixed_clock_utc, caplog,
):
    transport = make_transport([
        {"status": 200, "json": make_token_response()},
        {"status": 500, "json": {"return_msg": "server died"}},
    ])
    async with httpx.AsyncClient(transport=transport) as client:
        mgr = V71TokenManager(
            app_key="k", app_secret="s", is_paper=True,
            http_client=client, clock=fixed_clock_utc,
        )
        await mgr.get_token()
        with caplog.at_level(logging.WARNING):
            await mgr.revoke()
        assert mgr.current_token is None  # state still cleared


# ---------------------------------------------------------------------------
# Group 6 -- security regression
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("", "****"),
        ("abc", "****"),
        ("1234567", "****"),         # below min length
        ("12345678", "1234****5678"),  # exact min
        ("WQJaSECRETtokenABCD", "WQJa****ABCD"),
    ],
)
def test_mask_token_boundary(raw, expected):
    assert _mask_token(raw) == expected


async def test_logs_never_contain_plaintext_token(
    make_transport, make_token_response, fixed_clock_utc, caplog,
):
    secret = "PLAINTEXT-token-DO-NOT-LEAK-1234"
    transport = make_transport([
        {"status": 200, "json": make_token_response(token=secret)},
        {"status": 200, "json": {"return_code": 0}},
        {"status": 200, "json": make_token_response(token=secret + "B")},
    ])
    async with httpx.AsyncClient(transport=transport) as client:
        mgr = V71TokenManager(
            app_key="k", app_secret="s", is_paper=True,
            http_client=client, clock=fixed_clock_utc,
        )
        with caplog.at_level(logging.DEBUG):
            await mgr.get_token()
            await mgr.revoke()
            await mgr.get_token()
    # Hard regression: the token plaintext must never appear in any log line.
    for record in caplog.records:
        assert secret not in record.getMessage()
        # The middle bytes should also be redacted.
        assert "PLAINTEXT-token-DO-NOT-LEA" not in record.getMessage()


def test_token_info_repr_does_not_leak_token():
    secret = "PLAINTEXTSECRETtoken1234"
    info = V71TokenInfo(
        token=secret,
        token_type="bearer",
        expires_at=datetime.now(KST) + timedelta(hours=1),
        issued_at=datetime.now(timezone.utc),
        is_paper=False,
    )
    text = repr(info)
    assert secret not in text
    assert "PLAINTEXTSECRET" not in text


def test_token_manager_repr_does_not_leak_secrets():
    secret_key = "SUPER-SECRET-APP-KEY-1234"
    secret_secret = "SUPER-SECRET-APP-SECRET-XYZ"
    mgr = V71TokenManager(
        app_key=secret_key, app_secret=secret_secret, is_paper=True,
    )
    text = repr(mgr)
    assert secret_key not in text
    assert secret_secret not in text


async def test_scrub_response_body_redacts_secrets(
    make_transport, fixed_clock_utc,
):
    transport = make_transport([
        {"status": 400, "json": {"return_msg": "echo: SUPER-SECRET-APP-KEY-1234"}},
    ])
    async with httpx.AsyncClient(transport=transport) as client:
        mgr = V71TokenManager(
            app_key="SUPER-SECRET-APP-KEY-1234",
            app_secret="SUPER-SECRET-APP-SECRET-XYZ",
            is_paper=True,
            http_client=client,
            clock=fixed_clock_utc,
        )
        with pytest.raises(V71TokenRequestError) as excinfo:
            await mgr.get_token()
        assert "SUPER-SECRET-APP-KEY-1234" not in str(excinfo.value)


# ---------------------------------------------------------------------------
# Group 7 -- configuration / edges
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "is_paper,expected_base",
    [
        (True, PAPER_BASE_URL),
        (False, LIVE_BASE_URL),
    ],
)
def test_base_url_resolved_from_paper_flag(is_paper, expected_base):
    mgr = V71TokenManager(app_key="k", app_secret="s", is_paper=is_paper)
    assert mgr.base_url == expected_base
    assert mgr.is_paper is is_paper


def test_base_url_must_be_https():
    with pytest.raises(ValueError, match="https://"):
        V71TokenManager(app_key="k", app_secret="s", base_url="http://api.kiwoom.com")


def test_explicit_base_url_overrides_default():
    mgr = V71TokenManager(
        app_key="k",
        app_secret="s",
        is_paper=True,
        base_url="https://custom.kiwoom.dev",
    )
    assert mgr.base_url == "https://custom.kiwoom.dev"


@pytest.mark.parametrize(
    "key,secret",
    [("", "x"), ("x", ""), ("", "")],
)
def test_empty_credentials_rejected(key, secret):
    with pytest.raises(ValueError):
        V71TokenManager(app_key=key, app_secret=secret)


@pytest.mark.parametrize("window", [-1, -3600])
def test_negative_refresh_window_rejected(window):
    with pytest.raises(ValueError):
        V71TokenManager(app_key="k", app_secret="s", refresh_window_seconds=window)


@pytest.mark.parametrize("timeout", [0, -5.0])
def test_non_positive_timeout_rejected(timeout):
    with pytest.raises(ValueError):
        V71TokenManager(app_key="k", app_secret="s", request_timeout=timeout)


def test_default_refresh_window_is_5_minutes():
    assert DEFAULT_REFRESH_WINDOW_SECONDS == 300


async def test_external_client_not_closed_on_aclose(
    make_transport, fixed_clock_utc,
):
    transport = make_transport()
    client = httpx.AsyncClient(transport=transport)
    mgr = V71TokenManager(
        app_key="k", app_secret="s", is_paper=True,
        http_client=client, clock=fixed_clock_utc,
    )
    await mgr.aclose()
    # External client survives aclose.
    assert not client.is_closed
    await client.aclose()


async def test_owned_client_closed_on_aclose(fixed_clock_utc):
    mgr = V71TokenManager(
        app_key="k", app_secret="s", is_paper=True, clock=fixed_clock_utc,
    )
    # Trigger lazy creation
    client = await mgr._ensure_client()
    assert not client.is_closed
    await mgr.aclose()
    assert client.is_closed


async def test_remaining_seconds_handles_kst_utc_offset():
    """expires_at in KST + now in UTC must yield the same delta."""
    now_utc = datetime(2026, 4, 27, 0, 0, tzinfo=timezone.utc)
    expires_kst = (now_utc + timedelta(hours=1)).astimezone(KST)
    info = V71TokenInfo(
        token="WQJaXXXXabcdABCD",
        token_type="bearer",
        expires_at=expires_kst,
        issued_at=now_utc,
        is_paper=False,
    )
    assert 3590 <= info.remaining_seconds(now=now_utc) <= 3600
    assert info.is_expired(now=now_utc) is False


async def test_oauth_request_carries_correct_headers_and_body(
    make_transport, make_token_response, fixed_clock_utc,
):
    transport = make_transport([{"status": 200, "json": make_token_response()}])
    async with httpx.AsyncClient(transport=transport) as client:
        mgr = V71TokenManager(
            app_key="MY_APP_KEY",
            app_secret="MY_APP_SECRET",
            is_paper=True,
            http_client=client,
            clock=fixed_clock_utc,
        )
        await mgr.get_token()
    assert transport.calls == 1
    request = transport.requests[0]
    assert request.url.path == "/oauth2/token"
    assert request.headers["api-id"] == "au10001"
    body = request.read()
    assert b"client_credentials" in body
    assert b"MY_APP_KEY" in body
    assert b"MY_APP_SECRET" in body
