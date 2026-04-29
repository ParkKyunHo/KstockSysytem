"""Mutable in-process system state (safe-mode / start time).

PRD §9.3 / §9.4 toggle this. P5.4.6 will subscribe the trading engine
event bus to the same state.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class SystemState:
    started_at: float = field(default_factory=time.time)
    safe_mode: bool = False
    safe_mode_reason: str | None = None
    safe_mode_entered_at: datetime | None = None
    safe_mode_resumed_at: datetime | None = None
    last_websocket_disconnect_at: datetime | None = None
    websocket_reconnect_count_today: int = 0
    websocket_connected: bool = True
    kiwoom_available: bool = True
    telegram_active: bool = True
    # P-Wire-4a degraded mode flag: VI monitor is wired in P-Wire-4c. Until
    # then, V71BuyExecutor receives an ``is_vi_active`` stub that returns
    # ``False`` for every code. ``True`` here means PATH_A entries are NOT
    # blocked by VI state; surfaced to the dashboard so operators can see
    # the gap.
    degraded_vi: bool = False

    # 박스 wizard 비중 결정용 실제 키움 잔고 (kt00018 5분 TTL cache).
    # buy_executor wire 시점에 trading_bridge 가 register. 비활성 또는
    # 키움 fetch 실패 시 None -- frontend 는 fallback (settings.total_capital
    # 또는 unknown 메시지) 처리.
    get_total_capital: Callable[[], int] | None = None

    def uptime_seconds(self) -> int:
        return int(time.time() - self.started_at)


system_state = SystemState()


_FEATURE_FLAGS_DEFAULT = {
    "v71.box_system": True,
    "v71.exit_system": True,
    "v71.vi_monitor": True,
    "v71.notifications": True,
    "v71.reports": True,
    "v71.websocket": True,
}


class FeatureFlagStore:
    def __init__(self) -> None:
        self._flags: dict[str, bool] = dict(_FEATURE_FLAGS_DEFAULT)
        # Allow env-driven overrides for boot-time toggling without DB.
        for key, default in _FEATURE_FLAGS_DEFAULT.items():
            env_key = "V71_FLAG_" + key.upper().replace(".", "_")
            raw = os.environ.get(env_key)
            if raw is None:
                continue
            self._flags[key] = raw.lower() in {"1", "true", "yes", "on"}

    def all(self) -> dict[str, bool]:
        return dict(self._flags)

    def set(self, key: str, value: bool) -> None:
        self._flags[key] = value


feature_flags = FeatureFlagStore()
