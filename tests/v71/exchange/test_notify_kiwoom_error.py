"""Unit tests for ``src/core/v71/exchange/notify_kiwoom_error.py`` +
``src/core/v71/skills/notification_skill.format_kiwoom_error_message``.

Spec sources:
  - 06_AGENTS_SPEC.md §5 Test Strategy verification (28-case plan)
  - 12_SECURITY.md §6 (token / Authorization redaction + payload sanitization)
  - 02_TRADING_RULES.md §9 (severity tiers, message format)
  - error_mapper severity policy (1700 / 8005 / 8010 / 8030 / 8031 / 1999)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from src.core.v71.exchange.error_mapper import (
    V71KiwoomEnvMismatchError,
    V71KiwoomIPMismatchError,
    V71KiwoomMappedError,
    V71KiwoomRateLimitError,
    V71KiwoomServerError,
    V71KiwoomTokenInvalidError,
    V71KiwoomUnknownError,
)
from src.core.v71.exchange.notify_kiwoom_error import (
    build_kiwoom_error_request,
    notify_kiwoom_error,
)
from src.core.v71.skills.notification_skill import (
    EventType,
    NotificationRequest,
    Severity,
    format_kiwoom_error_message,
)

FIXED_TS = datetime(2026, 4, 28, 9, 30, 45, tzinfo=timezone.utc)


def _fixed_clock() -> datetime:
    return FIXED_TS


def _make_error(
    cls: type[V71KiwoomMappedError],
    *,
    return_code: int,
    severity: str,
    return_msg: str = "test",
    api_id: str | None = "kt10000",
) -> V71KiwoomMappedError:
    return cls(
        f"test {return_code}",
        return_code=return_code,
        return_msg=return_msg,
        api_id=api_id,
        severity=severity,
    )


# ---------------------------------------------------------------------------
# Group A: subclass → EventType + Severity (5 cases parametrize)
# ---------------------------------------------------------------------------


class TestKiwoomErrorMapping:
    @pytest.mark.parametrize(
        "error_class,return_code,expected_event,expected_severity",
        [
            (V71KiwoomRateLimitError, 1700,
             EventType.KIWOOM_RATE_LIMIT_EXCEEDED, Severity.HIGH),
            (V71KiwoomTokenInvalidError, 8005,
             EventType.KIWOOM_TOKEN_INVALID, Severity.MEDIUM),
            (V71KiwoomIPMismatchError, 8010,
             EventType.KIWOOM_IP_MISMATCH, Severity.CRITICAL),
            (V71KiwoomEnvMismatchError, 8030,
             EventType.KIWOOM_ENV_MISMATCH, Severity.CRITICAL),
            (V71KiwoomEnvMismatchError, 8031,
             EventType.KIWOOM_ENV_MISMATCH, Severity.CRITICAL),
            (V71KiwoomServerError, 1999,
             EventType.KIWOOM_SERVER_ERROR, Severity.HIGH),
        ],
    )
    def test_event_type_and_severity_match(
        self, error_class, return_code, expected_event, expected_severity
    ):
        err = _make_error(
            error_class,
            return_code=return_code,
            severity=expected_severity.value,
        )
        req = build_kiwoom_error_request(err, clock=_fixed_clock)
        assert req.severity == expected_severity
        assert req.event_type == expected_event

    def test_unknown_subclass_falls_back_to_system_error(self):
        err = _make_error(
            V71KiwoomUnknownError, return_code=9999, severity="HIGH",
        )
        req = build_kiwoom_error_request(err, clock=_fixed_clock)
        assert req.event_type == EventType.SYSTEM_ERROR


# ---------------------------------------------------------------------------
# Group B: format_kiwoom_error_message (8 cases)
# ---------------------------------------------------------------------------


class TestFormatKiwoomErrorMessage:
    def test_basic_lines_render(self):
        title, body = format_kiwoom_error_message(
            severity=Severity.HIGH,
            event_type=EventType.KIWOOM_RATE_LIMIT_EXCEEDED,
            return_code=1700,
            api_id="kt10000",
            return_msg="요청 한도 초과",
            timestamp=FIXED_TS,
        )
        assert title == "[HIGH] 키움 API 요청 한도 초과"
        assert "코드: 1700" in body
        assert "API: kt10000" in body
        assert "09:30:45" in body
        assert "메시지: 요청 한도 초과" in body
        assert "자동 복구 불가" not in body
        assert "재시도" not in body

    def test_is_fatal_renders_intervention_line(self):
        _, body = format_kiwoom_error_message(
            severity=Severity.CRITICAL,
            event_type=EventType.KIWOOM_IP_MISMATCH,
            return_code=8010,
            api_id="kt10000",
            return_msg="IP 불일치",
            timestamp=FIXED_TS,
            is_fatal=True,
        )
        assert "자동 복구 불가" in body
        assert "운영자 개입 필요" in body

    def test_force_refresh_renders_refresh_line(self):
        _, body = format_kiwoom_error_message(
            severity=Severity.MEDIUM,
            event_type=EventType.KIWOOM_TOKEN_INVALID,
            return_code=8005,
            api_id="kt10000",
            return_msg="토큰 무효",
            timestamp=FIXED_TS,
            should_force_token_refresh=True,
        )
        assert "토큰 자동 재발급" in body

    def test_retry_with_backoff_renders_backoff_line(self):
        _, body = format_kiwoom_error_message(
            severity=Severity.HIGH,
            event_type=EventType.KIWOOM_RATE_LIMIT_EXCEEDED,
            return_code=1700,
            api_id="kt10000",
            return_msg="rl",
            timestamp=FIXED_TS,
            should_retry_with_backoff=True,
        )
        assert "백오프 후 재시도" in body

    def test_action_hints_are_mutually_exclusive(self):
        # is_fatal takes priority over the other two.
        _, body = format_kiwoom_error_message(
            severity=Severity.CRITICAL,
            event_type=EventType.KIWOOM_IP_MISMATCH,
            return_code=8010,
            api_id="kt10000",
            return_msg="msg",
            timestamp=FIXED_TS,
            is_fatal=True,
            should_force_token_refresh=True,
            should_retry_with_backoff=True,
        )
        assert "자동 복구 불가" in body
        assert "토큰 자동 재발급" not in body
        assert "백오프 후 재시도" not in body

    def test_return_msg_none_skips_message_line(self):
        _, body = format_kiwoom_error_message(
            severity=Severity.HIGH,
            event_type=EventType.KIWOOM_SERVER_ERROR,
            return_code=1999,
            api_id="kt10000",
            return_msg=None,
            timestamp=FIXED_TS,
        )
        assert "메시지:" not in body

    def test_return_msg_truncated_at_200(self):
        long_msg = "X" * 500
        _, body = format_kiwoom_error_message(
            severity=Severity.HIGH,
            event_type=EventType.KIWOOM_SERVER_ERROR,
            return_code=1999,
            api_id="kt10000",
            return_msg=long_msg,
            timestamp=FIXED_TS,
        )
        msg_line = next(
            line for line in body.split("\n") if line.startswith("메시지:")
        )
        assert msg_line.endswith("...")
        # "메시지: " (5 chars) + 200 + "..." (3) = 208 chars
        assert len(msg_line) == 208

    def test_return_msg_redacts_bearer_token(self):
        # Security H1 regression -- bearer token must be redacted.
        secret = "Bearer eyJSUPER_SECRET_TOKEN_12345abcdef"
        _, body = format_kiwoom_error_message(
            severity=Severity.HIGH,
            event_type=EventType.KIWOOM_SERVER_ERROR,
            return_code=1999,
            api_id="kt10000",
            return_msg=f"echoed {secret} from gateway",
            timestamp=FIXED_TS,
        )
        assert "SUPER_SECRET_TOKEN_12345" not in body
        assert "eyJSUPER" not in body
        assert "[REDACTED]" in body


# ---------------------------------------------------------------------------
# Group C: build_kiwoom_error_request policy + payload (8 cases)
# ---------------------------------------------------------------------------


class TestBuildKiwoomErrorRequest:
    def test_rate_limit_marks_backoff(self):
        err = _make_error(
            V71KiwoomRateLimitError, return_code=1700, severity="HIGH",
        )
        req = build_kiwoom_error_request(err, clock=_fixed_clock)
        assert req.payload["should_retry_with_backoff"] is True
        assert req.payload["is_fatal"] is False
        assert req.payload["should_force_token_refresh"] is False

    def test_ip_mismatch_marks_fatal(self):
        err = _make_error(
            V71KiwoomIPMismatchError, return_code=8010, severity="CRITICAL",
        )
        req = build_kiwoom_error_request(err, clock=_fixed_clock)
        assert req.payload["is_fatal"] is True

    def test_env_mismatch_marks_fatal(self):
        err = _make_error(
            V71KiwoomEnvMismatchError, return_code=8031, severity="CRITICAL",
        )
        req = build_kiwoom_error_request(err, clock=_fixed_clock)
        assert req.payload["is_fatal"] is True

    def test_token_invalid_marks_force_refresh(self):
        err = _make_error(
            V71KiwoomTokenInvalidError, return_code=8005, severity="MEDIUM",
        )
        req = build_kiwoom_error_request(err, clock=_fixed_clock)
        assert req.payload["should_force_token_refresh"] is True
        assert req.payload["is_fatal"] is False

    def test_api_id_override_replaces_in_payload_and_message(self):
        err = _make_error(
            V71KiwoomRateLimitError,
            return_code=1700,
            severity="HIGH",
            api_id="kt10000",
        )
        req = build_kiwoom_error_request(
            err, api_id_override="kt00018", clock=_fixed_clock,
        )
        assert req.payload["api_id"] == "kt00018"
        assert "API: kt00018" in req.message

    def test_extra_payload_merges_caller_fields(self):
        err = _make_error(
            V71KiwoomRateLimitError, return_code=1700, severity="HIGH",
        )
        req = build_kiwoom_error_request(
            err, extra_payload={"attempt": 3}, clock=_fixed_clock,
        )
        assert req.payload["attempt"] == 3
        # Canonical fields untouched.
        assert req.payload["return_code"] == 1700

    def test_clock_default_renders_a_time(self):
        err = _make_error(
            V71KiwoomRateLimitError, return_code=1700, severity="HIGH",
        )
        req = build_kiwoom_error_request(err)
        # Time component must render in the message body.
        import re
        assert re.search(r"\d{2}:\d{2}:\d{2}", req.message)

    def test_returns_notification_request_dataclass(self):
        err = _make_error(
            V71KiwoomRateLimitError, return_code=1700, severity="HIGH",
        )
        req = build_kiwoom_error_request(err, clock=_fixed_clock)
        assert isinstance(req, NotificationRequest)


# ---------------------------------------------------------------------------
# Group D: payload sanitization (Security M1) (4 cases)
# ---------------------------------------------------------------------------


class TestPayloadSanitization:
    @pytest.mark.parametrize(
        "forbidden_key",
        ["token", "access_token", "Authorization", "app_secret", "secret"],
    )
    def test_forbidden_key_in_extra_payload_redacted(self, forbidden_key, caplog):
        err = _make_error(
            V71KiwoomRateLimitError, return_code=1700, severity="HIGH",
        )
        with caplog.at_level(logging.WARNING):
            req = build_kiwoom_error_request(
                err,
                extra_payload={forbidden_key: "SUPER_SECRET_VALUE"},
                clock=_fixed_clock,
            )
        assert req.payload[forbidden_key] == "***REDACTED***"
        assert "SUPER_SECRET_VALUE" not in req.message

    @pytest.mark.parametrize(
        "reserved_key",
        ["is_fatal", "should_force_token_refresh", "should_retry_with_backoff",
         "return_code", "api_id"],
    )
    def test_reserved_key_in_extra_payload_dropped(self, reserved_key, caplog):
        # Security M1: caller cannot falsify the canonical alert metadata
        # by passing the reserved keys via extra_payload.
        err = _make_error(
            V71KiwoomIPMismatchError, return_code=8010, severity="CRITICAL",
        )
        # Try to flip is_fatal=False on an 8010 incident.
        with caplog.at_level(logging.WARNING):
            req = build_kiwoom_error_request(
                err,
                extra_payload={reserved_key: "ATTACKER_SUPPLIED"},
                clock=_fixed_clock,
            )
        # Helper-owned canonical value wins.
        if reserved_key == "is_fatal":
            assert req.payload["is_fatal"] is True
        elif reserved_key == "return_code":
            assert req.payload["return_code"] == 8010

    def test_safe_extra_payload_keys_pass_through(self):
        err = _make_error(
            V71KiwoomRateLimitError, return_code=1700, severity="HIGH",
        )
        req = build_kiwoom_error_request(
            err,
            extra_payload={"attempt": 3, "elapsed_ms": 1500},
            clock=_fixed_clock,
        )
        assert req.payload["attempt"] == 3
        assert req.payload["elapsed_ms"] == 1500

    def test_payload_is_json_serialisable(self):
        # notifications.payload is JSONB in PostgreSQL; ensure our shape
        # round-trips through json.dumps without TypeError.
        import json
        err = _make_error(
            V71KiwoomIPMismatchError, return_code=8010, severity="CRITICAL",
        )
        req = build_kiwoom_error_request(
            err, extra_payload={"attempt": 3}, clock=_fixed_clock,
        )
        json.dumps(req.payload)


# ---------------------------------------------------------------------------
# Group E: severity cast fail-secure (Security M2) (2 cases)
# ---------------------------------------------------------------------------


class TestSeverityCastFailSecure:
    def test_invalid_severity_falls_back_to_high(self, capsys):
        # Force an invalid severity onto the error instance (future drift
        # / a malformed mapper would do this in production). The project
        # logger writes to stdout via structlog, so capsys (not caplog).
        err = _make_error(
            V71KiwoomRateLimitError, return_code=1700, severity="HIGH",
        )
        object.__setattr__(err, "severity", "BOGUS")

        req = build_kiwoom_error_request(err, clock=_fixed_clock)

        assert req.severity == Severity.HIGH  # safe fallback
        captured = capsys.readouterr()
        assert "v71_kiwoom_severity_cast_failed" in captured.out

    def test_helper_never_raises_on_severity_cast(self):
        err = _make_error(
            V71KiwoomRateLimitError, return_code=1700, severity="HIGH",
        )
        object.__setattr__(err, "severity", "junk")
        # Must not raise.
        build_kiwoom_error_request(err, clock=_fixed_clock)


# ---------------------------------------------------------------------------
# Group F: notify_kiwoom_error queue integration (4 cases)
# ---------------------------------------------------------------------------


def _outcome_record_id(notification_id: str) -> AsyncMock:
    record = AsyncMock()
    record.id = notification_id
    outcome = AsyncMock()
    outcome.accepted = True
    outcome.record = record
    outcome.suppression_reason = None
    return outcome


def _suppressed_outcome(reason: str) -> AsyncMock:
    outcome = AsyncMock()
    outcome.accepted = False
    outcome.record = None
    outcome.suppression_reason = reason
    return outcome


@pytest.fixture
def queue_mock():
    queue = AsyncMock()
    queue.enqueue = AsyncMock(return_value=_outcome_record_id("notif-test-1"))
    return queue


class TestNotifyKiwoomError:
    async def test_enqueues_and_returns_queued(self, queue_mock):
        err = _make_error(
            V71KiwoomRateLimitError, return_code=1700, severity="HIGH",
        )
        result = await notify_kiwoom_error(
            err, queue=queue_mock, clock=_fixed_clock,
        )
        assert result.status == "QUEUED"
        assert result.notification_id == "notif-test-1"
        queue_mock.enqueue.assert_awaited_once()
        kwargs = queue_mock.enqueue.await_args.kwargs
        assert kwargs["severity"] == Severity.HIGH
        assert kwargs["event_type"] == "KIWOOM_RATE_LIMIT_EXCEEDED"
        assert kwargs["payload"]["return_code"] == 1700

    async def test_critical_path_routes(self, queue_mock):
        err = _make_error(
            V71KiwoomIPMismatchError, return_code=8010, severity="CRITICAL",
        )
        result = await notify_kiwoom_error(
            err, queue=queue_mock, clock=_fixed_clock,
        )
        assert result.status == "QUEUED"
        kwargs = queue_mock.enqueue.await_args.kwargs
        assert kwargs["severity"] == Severity.CRITICAL

    async def test_queue_suppression_propagates(self, queue_mock):
        queue_mock.enqueue.return_value = _suppressed_outcome("RATE_LIMIT")
        err = _make_error(
            V71KiwoomRateLimitError, return_code=1700, severity="HIGH",
        )
        result = await notify_kiwoom_error(
            err, queue=queue_mock, clock=_fixed_clock,
        )
        assert result.status == "SUPPRESSED"
        assert result.suppression_reason == "RATE_LIMIT"
        assert result.notification_id is None

    async def test_queue_exception_propagates(self, queue_mock):
        queue_mock.enqueue.side_effect = RuntimeError("DB down")
        err = _make_error(
            V71KiwoomRateLimitError, return_code=1700, severity="HIGH",
        )
        with pytest.raises(RuntimeError, match="DB down"):
            await notify_kiwoom_error(
                err, queue=queue_mock, clock=_fixed_clock,
            )


# ---------------------------------------------------------------------------
# Group G: schema consistency (2 cases)
# ---------------------------------------------------------------------------


class TestPayloadSchemaConsistency:
    def test_canonical_keys_always_present(self):
        for cls, code, sev in [
            (V71KiwoomRateLimitError, 1700, "HIGH"),
            (V71KiwoomIPMismatchError, 8010, "CRITICAL"),
            (V71KiwoomTokenInvalidError, 8005, "MEDIUM"),
            (V71KiwoomServerError, 1999, "HIGH"),
        ]:
            err = _make_error(cls, return_code=code, severity=sev)
            req = build_kiwoom_error_request(err, clock=_fixed_clock)
            required = {
                "return_code", "api_id", "is_fatal",
                "should_force_token_refresh", "should_retry_with_backoff",
            }
            assert required <= set(req.payload.keys())

    def test_event_type_in_canonical_set(self):
        for cls, code, sev, expected in [
            (V71KiwoomRateLimitError, 1700, "HIGH",
             EventType.KIWOOM_RATE_LIMIT_EXCEEDED),
            (V71KiwoomIPMismatchError, 8010, "CRITICAL",
             EventType.KIWOOM_IP_MISMATCH),
        ]:
            err = _make_error(cls, return_code=code, severity=sev)
            req = build_kiwoom_error_request(err, clock=_fixed_clock)
            assert req.event_type == expected
