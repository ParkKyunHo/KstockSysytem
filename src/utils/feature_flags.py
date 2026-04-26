"""V7.1 Feature Flag 로더.

Source of truth: ``config/feature_flags.yaml``
Spec: ``docs/v71/05_MIGRATION_PLAN.md`` §10
헌법: V7.1 신규 코드는 진입점에서 :func:`is_enabled` 로 가드되어야 한다 (하네스 5).

런타임 오버라이드:
    환경변수 ``V71_FF__<DOTTED_PATH>=true|false`` (점은 ``__`` 로 인코딩).
    예) ``V71_FF__V71__BOX_SYSTEM=true``  →  ``v71.box_system`` 활성화.

스레드 안전성:
    YAML 1회 로드 + 환경변수 매 호출 평가. 캐시 무효화는 :func:`reload` 로 명시 호출.
"""

from __future__ import annotations

import os
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_FLAG_FILE = Path(__file__).resolve().parents[2] / "config" / "feature_flags.yaml"
_ENV_PREFIX = "V71_FF__"
_TRUE_TOKENS = frozenset({"1", "true", "yes", "on", "y", "t"})
_FALSE_TOKENS = frozenset({"0", "false", "no", "off", "n", "f"})

_lock = threading.Lock()


@lru_cache(maxsize=1)
def _load_flags() -> dict[str, Any]:
    if not _FLAG_FILE.is_file():
        return {}
    with _FLAG_FILE.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data or {}


def _resolve_yaml(path: str) -> bool | None:
    node: Any = _load_flags()
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    if isinstance(node, bool):
        return node
    return None


def _resolve_env(path: str) -> bool | None:
    env_key = _ENV_PREFIX + path.upper().replace(".", "__")
    raw = os.environ.get(env_key)
    if raw is None:
        return None
    token = raw.strip().lower()
    if token in _TRUE_TOKENS:
        return True
    if token in _FALSE_TOKENS:
        return False
    return None


def is_enabled(path: str, default: bool = False) -> bool:
    """``v71.box_system`` 같은 점 표기 경로의 활성 여부.

    우선순위: 환경변수 > YAML > ``default``.
    """
    env = _resolve_env(path)
    if env is not None:
        return env
    yaml_value = _resolve_yaml(path)
    if yaml_value is not None:
        return yaml_value
    return default


def require_enabled(path: str) -> None:
    """플래그가 꺼져 있으면 :class:`RuntimeError` 발생 (V7.1 진입점 가드용)."""
    if not is_enabled(path):
        raise RuntimeError(
            f"Feature flag '{path}' is disabled. "
            f"Enable in config/feature_flags.yaml or set "
            f"{_ENV_PREFIX}{path.upper().replace('.', '__')}=true."
        )


def all_flags() -> dict[str, Any]:
    """현재 효과적 플래그 스냅샷 (YAML + ENV 오버라이드 적용)."""
    snapshot: dict[str, Any] = {}

    def _walk(prefix: str, node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                _walk(f"{prefix}.{key}" if prefix else key, value)
        elif isinstance(node, bool):
            snapshot[prefix] = is_enabled(prefix)

    _walk("", _load_flags())
    return snapshot


def reload() -> None:
    """YAML 캐시 무효화 (테스트/CLI 용)."""
    with _lock:
        _load_flags.cache_clear()
