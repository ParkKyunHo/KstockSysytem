"""Unit tests for ``src/core/v71/exchange/error_mapper.py``.

Spec sources:
  - docs/v71/06_AGENTS_SPEC.md §5 Test Strategy verification
  - docs/v71/KIWOOM_API_ANALYSIS.md line 1050~1094 (Kiwoom error codes)
"""

from __future__ import annotations

import pytest

from src.core.v71.exchange.error_mapper import (
    DEFAULT_BACKOFF_BASE_SECONDS,
    DEFAULT_BACKOFF_CAP_SECONDS,
    ERROR_CODE_TO_SEVERITY,
    ERROR_CODE_TO_TYPE,
    V71KiwoomEnvMismatchError,
    V71KiwoomInvalidInputError,
    V71KiwoomIPMismatchError,
    V71KiwoomMappedError,
    V71KiwoomMarketNotFoundError,
    V71KiwoomRateLimitError,
    V71KiwoomRecursionError,
    V71KiwoomServerError,
    V71KiwoomTokenInvalidError,
    V71KiwoomUnknownError,
    V71StockNotFoundError,
    compute_backoff_seconds,
    is_fatal,
    map_business_error,
    severity_for,
    should_force_token_refresh,
    should_retry_with_backoff,
)
from src.core.v71.exchange.kiwoom_client import (
    V71KiwoomBusinessError,
    V71KiwoomError,
)


def _biz(code: int, msg: str = "msg", api_id: str = "ka10080") -> V71KiwoomBusinessError:
    return V71KiwoomBusinessError(
        f"raw {code}", return_code=code, return_msg=msg, api_id=api_id,
    )


# ---------------------------------------------------------------------------
# Group A -- mapping accuracy
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "code,expected_type",
    [
        (1517, V71KiwoomInvalidInputError),
        (1687, V71KiwoomRecursionError),
        (1700, V71KiwoomRateLimitError),
        (1901, V71KiwoomMarketNotFoundError),
        (1902, V71StockNotFoundError),
        (1999, V71KiwoomServerError),
        (8005, V71KiwoomTokenInvalidError),
        (8010, V71KiwoomIPMismatchError),
        (8030, V71KiwoomEnvMismatchError),
        (8031, V71KiwoomEnvMismatchError),
    ],
)
def test_map_business_error_to_typed_error(code, expected_type):
    mapped = map_business_error(_biz(code))
    assert isinstance(mapped, expected_type)
    assert isinstance(mapped, V71KiwoomMappedError)


def test_map_unknown_code_falls_back_to_unknown_error():
    mapped = map_business_error(_biz(99999))
    assert isinstance(mapped, V71KiwoomUnknownError)
    assert mapped.severity == "HIGH"


@pytest.mark.parametrize(
    "code,expected_severity",
    [
        (1517, "LOW"),
        (1687, "LOW"),
        (1700, "HIGH"),
        (1901, "LOW"),
        (1902, "MEDIUM"),
        (1999, "HIGH"),
        (8005, "MEDIUM"),
        (8010, "CRITICAL"),
        (8030, "CRITICAL"),
        (8031, "CRITICAL"),
        (99999, "HIGH"),  # unknown -> HIGH
    ],
)
def test_severity_for_each_code(code, expected_severity):
    assert severity_for(code) == expected_severity


@pytest.mark.parametrize(
    "code,expected_fatal",
    [
        (8010, True),
        (8030, True),
        (8031, True),
        (1700, False),
        (8005, False),
        (1517, False),
        (1902, False),
        (99999, False),
    ],
)
def test_is_fatal_only_for_critical_config_codes(code, expected_fatal):
    mapped = map_business_error(_biz(code))
    assert is_fatal(mapped) is expected_fatal


@pytest.mark.parametrize(
    "code,expected",
    [
        (1700, True),
        (1517, False),
        (8005, False),
        (8010, False),
        (8030, False),
        (1902, False),
        (99999, False),
    ],
)
def test_should_retry_with_backoff_only_for_rate_limit(code, expected):
    mapped = map_business_error(_biz(code))
    assert should_retry_with_backoff(mapped) is expected


@pytest.mark.parametrize(
    "code,expected",
    [
        (8005, True),
        (1700, False),
        (8010, False),
        (1517, False),
        (1902, False),
        (99999, False),
    ],
)
def test_should_force_token_refresh_only_for_8005(code, expected):
    mapped = map_business_error(_biz(code))
    assert should_force_token_refresh(mapped) is expected


# ---------------------------------------------------------------------------
# Group B -- attribute preservation
# ---------------------------------------------------------------------------


def test_mapped_error_preserves_input_fields():
    biz = V71KiwoomBusinessError(
        "raw", return_code=1700, return_msg="요청 개수 초과", api_id="kt10000",
    )
    mapped = map_business_error(biz)
    assert mapped.return_code == 1700
    assert mapped.return_msg == "요청 개수 초과"
    assert mapped.api_id == "kt10000"
    assert mapped.severity == "HIGH"


def test_mapped_error_inherits_v71kiwoomerror():
    mapped = map_business_error(_biz(1517))
    with pytest.raises(V71KiwoomError):
        raise mapped


def test_mapped_error_inherits_mapped_base():
    mapped = map_business_error(_biz(8010))
    assert isinstance(mapped, V71KiwoomMappedError)


def test_mapped_error_message_format():
    biz = V71KiwoomBusinessError(
        "raw", return_code=1700, return_msg="RATE LIMIT", api_id="kt10000",
    )
    mapped = map_business_error(biz)
    text = str(mapped)
    assert "1700" in text
    assert "kt10000" in text
    assert "RATE LIMIT" in text


def test_mapped_error_handles_none_api_id():
    biz = V71KiwoomBusinessError(
        "raw", return_code=1700, return_msg="x", api_id=None,
    )
    mapped = map_business_error(biz)
    assert mapped.api_id is None
    assert "unknown_api" in str(mapped)


# ---------------------------------------------------------------------------
# Group C -- backoff computation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "attempt,expected",
    [
        (1, 1.0),
        (2, 2.0),
        (3, 4.0),
        (4, 8.0),
        (5, 16.0),
        (6, 30.0),  # capped
        (7, 30.0),
        (100, 30.0),
    ],
)
def test_compute_backoff_default_base_and_cap(attempt, expected):
    assert compute_backoff_seconds(attempt) == expected


def test_compute_backoff_custom_base():
    assert compute_backoff_seconds(1, base=0.5) == 0.5
    assert compute_backoff_seconds(2, base=0.5) == 1.0
    assert compute_backoff_seconds(3, base=0.5) == 2.0


def test_compute_backoff_custom_cap():
    assert compute_backoff_seconds(10, base=1.0, cap=5.0) == 5.0


@pytest.mark.parametrize("attempt", [0, -1, -100])
def test_compute_backoff_invalid_attempt(attempt):
    with pytest.raises(ValueError, match="attempt"):
        compute_backoff_seconds(attempt)


@pytest.mark.parametrize("base", [0, -0.5, -1.0])
def test_compute_backoff_invalid_base(base):
    with pytest.raises(ValueError, match="base"):
        compute_backoff_seconds(1, base=base)


@pytest.mark.parametrize("cap", [0, -1.0, -30.0])
def test_compute_backoff_invalid_cap(cap):
    with pytest.raises(ValueError, match="cap"):
        compute_backoff_seconds(1, cap=cap)


def test_compute_backoff_cap_less_than_base():
    with pytest.raises(ValueError, match="cap"):
        compute_backoff_seconds(1, base=10.0, cap=5.0)


def test_default_constants():
    assert DEFAULT_BACKOFF_BASE_SECONDS == 1.0
    assert DEFAULT_BACKOFF_CAP_SECONDS == 30.0


# ---------------------------------------------------------------------------
# Group D -- mapping table integrity
# ---------------------------------------------------------------------------


def test_error_code_mappings_are_read_only():
    with pytest.raises(TypeError):
        ERROR_CODE_TO_TYPE[8010] = V71KiwoomInvalidInputError  # type: ignore[index]
    with pytest.raises(TypeError):
        ERROR_CODE_TO_SEVERITY[8010] = "LOW"  # type: ignore[index]


def test_every_code_in_type_table_has_severity():
    # Sanity: lookup tables must agree on the supported code set.
    type_codes = set(ERROR_CODE_TO_TYPE.keys())
    severity_codes = set(ERROR_CODE_TO_SEVERITY.keys())
    assert type_codes == severity_codes


# ---------------------------------------------------------------------------
# Group E -- property: backoff is monotonic up to cap
# ---------------------------------------------------------------------------


def test_backoff_is_monotonic_until_cap():
    base = 1.0
    cap = 30.0
    prev = compute_backoff_seconds(1, base=base, cap=cap)
    for attempt in range(2, 12):
        curr = compute_backoff_seconds(attempt, base=base, cap=cap)
        assert curr >= prev
        assert curr <= cap
        prev = curr
