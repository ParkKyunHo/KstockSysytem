"""V7.1 on-demand reports (Claude Opus 4.7).

Spec: docs/v71/11_REPORTING.md
Modules (Phase 6):
  - ``report_generator``  Top-level orchestrator
  - ``claude_api_client`` Anthropic SDK wrapper (cost tracking)
  - ``data_collector``    Kiwoom + DART + Naver news aggregation
  - ``exporters``         PDF / Excel
"""
