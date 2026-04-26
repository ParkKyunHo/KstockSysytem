"""V7.1 Feature Flag 단위 테스트.

Spec: docs/v71/05_MIGRATION_PLAN.md §2.3, §10
"""

from __future__ import annotations

import os

import pytest

from src.utils import feature_flags as ff


@pytest.fixture(autouse=True)
def _isolate_state():
    saved = {k: v for k, v in os.environ.items() if k.startswith("V71_FF__")}
    for k in list(os.environ):
        if k.startswith("V71_FF__"):
            del os.environ[k]
    ff.reload()
    yield
    for k in list(os.environ):
        if k.startswith("V71_FF__"):
            del os.environ[k]
    os.environ.update(saved)
    ff.reload()


class TestYamlLoad:
    def test_loads_known_flag_as_bool(self):
        assert ff.is_enabled("v71.box_system") is False

    def test_safety_flag_is_true_by_default(self):
        assert ff.is_enabled("v71.v70_box_fallback") is True

    def test_unknown_path_returns_default_false(self):
        assert ff.is_enabled("does.not.exist") is False

    def test_unknown_path_respects_explicit_default(self):
        assert ff.is_enabled("does.not.exist", default=True) is True

    def test_all_flags_returns_complete_snapshot(self):
        snapshot = ff.all_flags()
        assert "v71.box_system" in snapshot
        assert "v71.v70_box_fallback" in snapshot
        assert all(isinstance(v, bool) for v in snapshot.values())


class TestEnvOverride:
    def test_env_true_overrides_yaml_false(self):
        os.environ["V71_FF__V71__BOX_SYSTEM"] = "true"
        assert ff.is_enabled("v71.box_system") is True

    def test_env_false_overrides_yaml_true(self):
        os.environ["V71_FF__V71__V70_BOX_FALLBACK"] = "false"
        assert ff.is_enabled("v71.v70_box_fallback") is False

    @pytest.mark.parametrize("token", ["1", "TRUE", "yes", "On", "y", "t"])
    def test_truthy_tokens(self, token):
        os.environ["V71_FF__V71__BOX_SYSTEM"] = token
        assert ff.is_enabled("v71.box_system") is True

    @pytest.mark.parametrize("token", ["0", "FALSE", "no", "Off", "n", "f"])
    def test_falsy_tokens(self, token):
        os.environ["V71_FF__V71__V70_BOX_FALLBACK"] = token
        assert ff.is_enabled("v71.v70_box_fallback") is False

    def test_invalid_token_falls_back_to_yaml(self):
        os.environ["V71_FF__V71__BOX_SYSTEM"] = "garbage"
        assert ff.is_enabled("v71.box_system") is False

    def test_env_overrides_default_for_unknown_path(self):
        os.environ["V71_FF__NEW__FEATURE"] = "true"
        assert ff.is_enabled("new.feature") is True


class TestRequireEnabled:
    def test_raises_when_disabled(self):
        with pytest.raises(RuntimeError, match="v71.box_system"):
            ff.require_enabled("v71.box_system")

    def test_silent_when_enabled(self):
        os.environ["V71_FF__V71__BOX_SYSTEM"] = "true"
        ff.require_enabled("v71.box_system")

    def test_error_message_includes_env_hint(self):
        with pytest.raises(RuntimeError, match=r"V71_FF__V71__BOX_SYSTEM"):
            ff.require_enabled("v71.box_system")
