"""Skill 8: Reference test scaffolding for V7.1 modules.

Spec: docs/v71/07_SKILLS_SPEC.md §8

Not imported at runtime. Used as a copy-paste template when adding tests
under ``tests/v71/test_skills/`` or ``tests/v71/test_<feature>/``.

Pattern:
  - One ``Test<Function>`` class per public function.
  - At minimum: normal_case, alternative_path, boundary_zero, boundary_max.
  - Fixtures named ``base_<thing>``, ``stage2_<thing>`` (post-state) so
    follow-up cases compose cleanly.
  - All numbers come from V71Constants (Harness 3 enforces).
  - Use pytest.mark.parametrize for boundary tables.
"""

from __future__ import annotations

# ---- TEMPLATE ONLY ----
# Copy this file when starting a new test module. Do not add real
# assertions here; CI runs tests/v71/, not src/core/v71/skills/.

TEMPLATE = '''
"""Tests for <module-under-test>.

Spec: <PRD section>
"""

from __future__ import annotations

import pytest

from src.core.v71.<package>.<module> import <SymbolUnderTest>
from src.core.v71.v71_constants import V71Constants as K


@pytest.fixture
def base_position():
    """Stage 1: just bought, before any partial exit."""
    return ...


@pytest.fixture
def stage2_position(base_position):
    """Stage 2: after +5% partial exit."""
    return ...


@pytest.fixture
def stage3_position(stage2_position):
    """Stage 3: after +10% partial exit."""
    return ...


class TestTargetFunction:
    def test_normal_case(self, base_position):
        ...

    def test_alternative_path(self, base_position):
        ...

    def test_boundary_zero(self):
        ...

    def test_boundary_max(self):
        ...

    @pytest.mark.parametrize("price,expected", [
        (..., ...),
    ])
    def test_table(self, price, expected):
        ...
'''


__all__ = ["TEMPLATE"]
