# CLAUDE.md — `src/core/v71/` (V7.1 거래 시스템 코어)

> 이 디렉터리에서 작업 시 **root CLAUDE.md + 이 파일**이 함께 컨텍스트.
> 거래 룰 = 자금 위험 직결 → root §0.1 (assume X) + 헌법 1 (사용자 판단 불가침) **강하게** 적용.

---

## 1. 거래 룰 헌법 (이 디렉터리 한정)

1. **9 skills 우선** — raw 직접 호출 금지 (harness H3 차단)
2. **frozen DTO** — `BoxRecord` / `PositionState` mutation은 `apply_*()` 메서드만 (직접 변경 금지)
3. **idempotent** — 같은 시그널 재진입 시 부작용 0
4. **atomic 트랜잭션** — orphan position/box 윈도우 0 (예: `V71PositionManager.create_with_box`)
5. **SSoT** — in-memory dict mirror of ORM 금지 (G1 차단)

> 이 5개를 어기면 자금 안전 직접 위협. PR/commit 전 자가 점검.

---

## 2. 9 Skills 빠른 참조 (PRD §7)

| 작업 | Skill (호출 entry) | raw 차단 |
|------|------|---------|
| Kiwoom REST | `v71-kiwoom-api` (`call_kiwoom_api()`) | httpx / requests / aiohttp |
| 박스 진입 판정 | `v71-box-entry` (`evaluate_box_entry()`) | 직접 PATH_A/B 로직 |
| 손절선 / TS / 익절 | `v71-exit-calc` (`calculate_effective_stop()`) | 직접 계산 |
| 매수/매도 후 평단가 | `v71-avg-price` (`update_position_after_buy/sell()`) | weighted_avg_price 직접 변경 |
| VI 발동/해제 | `v71-vi` (`handle_vi_state()`, `check_post_vi_gap()`) | 직접 VI flag 조작 |
| 알림 발송 | `v71-notification` (`send_notification()`) | telegram.send_message 직접 |
| kt00018 ↔ DB 정합 | `v71-reconciliation` (`reconcile_position()`) | 직접 비교/sync |
| 테스트 작성 | `v71-test-template` | (가이드만) |
| 신규 모듈 추가 | `v71-add-module` | 12단계 자동 |

→ raw call 시도 시 **harness H3 (Trading Rule Enforcer)** 가 pre-commit에서 차단.
→ 9개 외 새 도메인 = root **Part 4.3 신규 스킬 절차**로 사용자 승인 받아 생성.

---

## 3. Sub-agent 호출 trigger (이 디렉터리 작업 시)

```
거래 룰 작성/수정          → trading-logic-verifier (PRD §6.2 필수)
                            (박스 진입, 손절/익절/TS, 평단가, VI, 한도)
새 함수/클래스             → test-strategy (PRD §6.5 필수)
신규 모듈 추가             → v71-architect (PRD §6.1 필수)
                            또는 `/v71-add-module <path> "<purpose>"` 스킬
DB column/table/marker 변경 → migration-strategy (PRD §6.3 필수)
외부 API/시크릿 처리       → security-reviewer (PRD §6.4 필수)
```

---

## 4. 모듈 구조 (상세: `docs/v71/04_ARCHITECTURE.md`)

```
box/          BoxManager / Repository / EntryDetector (PATH_A 3분봉, PATH_B 일봉) / Strategies
exchange/     KiwoomClient / WebSocket / OrderManager / Reconciler / RateLimiter / TokenManager
exit/         Calculator / TrailingStop / Executor / Orchestrator
position/     V71PositionManager (DB-backed atomic, 5 invariant)
notification/ Service / DailySummary (15:30) / MonthlyReview (1일 09:00) / TelegramCommands / Queue
pricing/      V71PricePublisher (PRICE_TICK → DB UPDATE + WS publish, NFR1 1Hz flush)
skills/       9 표준 스킬 (위 §2)
market/       V71MarketSchedule / KR_HOLIDAYS_2026 (KST tz-aware)
```

---

## 5. 자금 안전 패턴 (필수 인지)

- `BoxRecord` / `PositionState` = `frozen=True` dataclass → 직접 mutation 차단
- 박스 진입 = **단일 atomic 트랜잭션** (position INSERT + box UPDATE + trade_event INSERT)
- 보상 실패 = 5분 cooldown (`BoxEvent.INVALIDATED`) — 무한 재시도 차단
- VI 발동 중 publish skip (P-Wire-Price-Tick CONSTRAINT P4)
- timestamp guard (kt00018 5s vs WS 0B 1Hz race 방지) — `WHERE current_price_at IS NULL OR < :new_at`
- per-stock `asyncio.Lock` (BoxManager + ExitOrchestrator + PricePublisher 각각 분리 lock)

---

## 6. 5 Invariant Flag (P-Wire-Box-2 land 전까지 false 강제)

`box_entry_detector` / `pullback_strategy` / `breakout_strategy` / `path_b_daily` / `buy_executor_v71`

→ `config/feature_flags.yaml` + `scripts/deploy/check_invariants.ps1` 강제. 운영자 결정 없이 ON 금지.

---

## 7. NFR1 (1초 hot-path budget)

- PRICE_TICK handler: 메모리 캐시만 < 1ms (DB UPDATE는 1Hz background flush task)
- 박스 진입 판정: < 100ms (`V71Constants.NFR1_HOT_PATH_BUDGET_SECONDS=0.1`)
- 알림 발송: 비동기 큐 (Circuit Breaker + 5분 빈도 제한)
- 무거운 작업 (kt00018 reconcile, fetch_history) = `asyncio.Task` background

> hot-path 1초 초과 risk 있는 작업 추가 시 v71-architect 호출 필수.
