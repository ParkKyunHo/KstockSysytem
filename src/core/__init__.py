"""V7.1 core package.

V7.0 Purple-ReAbs has been fully retired (preserved at git tag
``v7.0-final-stable``). All V7.1 code lives under ``src.core.v71``.

V7.1 entry points:
  - ``src.core.v71.box`` -- 박스 추적 / 진입 판정
  - ``src.core.v71.strategies`` -- BuyExecutor / ExitExecutor / ExitOrchestrator / VI 모니터
  - ``src.core.v71.exchange`` -- 키움 REST / WS / OrderManager / Reconciler
  - ``src.core.v71.notification`` -- V71NotificationService 스택
  - ``src.core.v71.position`` -- 평단가 / Reconciler
  - ``src.core.v71.candle`` -- V71CandleManager / V71BaseCandleBuilder (PATH_A 3분 + PATH_B 일봉)
  - ``src.core.v71.market`` -- V71MarketSchedule
  - ``src.core.v71.skills`` -- PRD §7 표준 스킬
"""
