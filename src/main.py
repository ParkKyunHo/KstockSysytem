"""V7.1 entry-point stub.

V7.0 has been fully retired (preserved at git tag ``v7.0-final-stable``).
The V7.1 box-based trading system now runs as a FastAPI app under
``src.web.v71.main:app``. The trading engine is wired via
``src.web.v71.trading_bridge`` (P-Wire-1 .. P-Wire-12) and started/stopped
from the FastAPI lifespan.

Run V7.1 with::

    uvicorn src.web.v71.main:app --host 0.0.0.0 --port 8080

This stub only emits an instruction message and exits non-zero so that any
``python -m src.main`` callers fail loudly instead of silently launching
nothing.
"""

from __future__ import annotations

import sys
import textwrap


def main() -> int:
    sys.stderr.write(
        textwrap.dedent(
            """
            -----------------------------------------------------------------
            K_stock_trading -- V7.1 (Box-Based Trading System)
            -----------------------------------------------------------------

            V7.0 has been fully retired (Phase A complete).
            V7.1 runs as a FastAPI application:

                uvicorn src.web.v71.main:app --host 0.0.0.0 --port 8080

            Documentation:
              - docs/v71/01_PRD_MAIN.md
              - docs/v71/05_MIGRATION_PLAN.md
              - docs/v71/WORK_LOG.md

            For the previous V7.0 entry point, check out git tag
            v7.0-final-stable.
            -----------------------------------------------------------------
            """
        ).strip()
        + "\n"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
