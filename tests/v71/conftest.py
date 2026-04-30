"""V7.1 test root conftest.

Pre-warms the ``src.core.v71.exchange`` import chain. The package
``__init__.py`` eagerly pulls in ``V71KiwoomExchangeAdapter``, which
imports from ``skills.kiwoom_api_skill``, which (re-)imports the
exchange package. Whether the cycle resolves depends on which test
module loads first; running the whole suite in pytest order works,
but invoking a single test file (``pytest tests/v71/test_x.py``)
sometimes hits the half-initialized state and dies with::

    ImportError: cannot import name 'ExchangeAdapter'

Tracked in MEMORY (pytest-only circular import). The proper fix is
to split the Protocol out of ``kiwoom_api_skill`` and lazy-import the
adapter from ``exchange.__init__``; until then this fixture imports
the modules in the order that warms the cache cleanly.

Also exposes :class:`FakeBoxManager` -- the test stub that replaces
the legacy ``V71BoxManager()`` (in-memory dict) call sites used by
nine pre-P-Wire-Box-1 test modules. The DB-backed manager now requires
a ``session_factory``; ``FakeBoxManager`` keeps the same async API
shape but stores boxes in-memory so existing test intent (drive the
manager directly, then assert on output) carries over without
spinning up an aiosqlite engine in every fixture.
"""

from __future__ import annotations


def _prewarm_v71_exchange_imports() -> None:
    # Import ``error_mapper`` first so kiwoom_api_skill's ``from
    # src.core.v71.exchange.error_mapper import (...)`` resolves before
    # exchange.__init__ tries to pull V71KiwoomExchangeAdapter back in.
    import src.core.v71.exchange.error_mapper  # noqa: F401
    import src.core.v71.exchange.exchange_adapter  # noqa: F401
    import src.core.v71.skills.kiwoom_api_skill  # noqa: F401


_prewarm_v71_exchange_imports()


# ---------------------------------------------------------------------------
# FakeBoxManager: re-exported from tests/v71/_fakes so test modules can
# do from tests.v71._fakes import FakeBoxManager. Keeping the class out
# of this conftest avoids the tests package import path issue.
# ---------------------------------------------------------------------------

from tests.v71._fakes import FakeBoxManager  # noqa: E402, F401
