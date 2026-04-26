"""V7.1 web dashboard (FastAPI + JWT + 2FA).

Spec: docs/v71/09_API_SPEC.md, docs/v71/10_UI_GUIDE.md, docs/v71/12_SECURITY.md
Subpackages (Phase 5):
  - ``api``       REST endpoints
  - ``auth``      JWT, 2FA TOTP, session management
  - ``dashboard`` Static asset serving / SSR if needed
"""
