"""V7.1 entry-point stub.

V7.0 Purple-ReAbs has been retired (preserved at git tag
``v7.0-final-stable``). The V7.1 box-based trading system is being
constructed under ``src/core/v71/`` per ``docs/v71/01_PRD_MAIN.md`` and
``docs/v71/05_MIGRATION_PLAN.md``.

Until Phase 2/3 of the migration, this entry point intentionally fails
fast rather than silently launching incomplete code. Operations should
continue to use the deployed V7.0 build (server-side, separate from this
working tree).
"""

from __future__ import annotations

import sys
import textwrap


def main() -> int:
    sys.stderr.write(
        textwrap.dedent(
            """
            -----------------------------------------------------------------
            K_stock_trading -- V7.1 (Box-Based Trading System) is in build.
            -----------------------------------------------------------------

            The V7.0 entry point has been removed during Phase 1 of the
            V7.0 -> V7.1 migration. The V7.1 trading engine will be wired
            here in Phase 3 once the box system, strategies, exit rules,
            and reconciler land under src/core/v71/.

            Status:
              - Phase 0:  complete (env separation, feature flags, harnesses)
              - Phase 1:  in progress (legacy code removal)
              - Phase 2:  pending (V7.1 skeletons + DB migrations)
              - Phase 3:  pending (V7.1 trading rules)

            See:
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
