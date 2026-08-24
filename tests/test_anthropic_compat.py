"""Tests for the AG2 sampling-parameter shim (`app/anthropic_compat.py`).

This shim is the project's most fragile piece: it monkey-patches an AG2
internal (`AnthropicClient.load_config`). If AG2 renames or restructures that
method, the patch silently stops applying and every Claude call starts failing
with a 400 about `temperature`. These tests turn that silent breakage into a
red build.
"""

from __future__ import annotations

import pytest
from autogen.oai import anthropic as ag2_anthropic

from app.anthropic_compat import _REJECTS_SAMPLING, patch_ag2_anthropic_sampling


@pytest.fixture
def unpatched_client(monkeypatch):
    """A fresh AnthropicClient subclass with a recording load_config.

    Patching the real class would leak across tests, so each test gets its own
    subclass installed in place of the real one.
    """
    seen: list[dict] = []

    class RecordingClient:
        def load_config(self, params):
            seen.append(params)
            # Mirror AG2's behaviour: temperature is always present.
            return {"model": params.get("model", ""), "temperature": 1.0, "max_tokens": 8192}

    monkeypatch.setattr(ag2_anthropic, "AnthropicClient", RecordingClient)
    return RecordingClient


class TestPatchBehaviour:
    @pytest.mark.parametrize(
        "model",
        ["claude-opus-4-8", "claude-opus-4-7", "claude-fable-5", "claude-mythos-1"],
    )
    def test_sampling_params_are_stripped_for_rejecting_models(self, unpatched_client, model):
        patch_ag2_anthropic_sampling()
        config = unpatched_client().load_config({"model": model})
        assert "temperature" not in config
        assert "top_p" not in config
        assert "top_k" not in config

    @pytest.mark.parametrize("model", ["claude-sonnet-4-6", "claude-opus-4-6", "claude-haiku-4-5"])
    def test_sampling_params_are_kept_for_models_that_accept_them(self, unpatched_client, model):
        patch_ag2_anthropic_sampling()
        config = unpatched_client().load_config({"model": model})
        assert config["temperature"] == 1.0

    def test_the_rest_of_the_config_is_untouched(self, unpatched_client):
        patch_ag2_anthropic_sampling()
        config = unpatched_client().load_config({"model": "claude-opus-4-8"})
        assert config["max_tokens"] == 8192
        assert config["model"] == "claude-opus-4-8"

    def test_a_missing_model_is_survivable(self, unpatched_client):
        patch_ag2_anthropic_sampling()
        assert unpatched_client().load_config({})["temperature"] == 1.0

    def test_patching_twice_does_not_stack(self, unpatched_client):
        """Non-idempotent patching would wrap load_config repeatedly on reimport."""
        patch_ag2_anthropic_sampling()
        first = unpatched_client.load_config
        patch_ag2_anthropic_sampling()
        assert unpatched_client.load_config is first


class TestModelPattern:
    @pytest.mark.parametrize(
        "model", ["claude-opus-4-7", "claude-opus-4-8", "CLAUDE-FABLE-5", "mythos"]
    )
    def test_matches_rejecting_models(self, model):
        assert _REJECTS_SAMPLING.search(model)

    @pytest.mark.parametrize("model", ["claude-sonnet-4-6", "claude-opus-4-6", "gpt-4"])
    def test_does_not_match_others(self, model):
        assert _REJECTS_SAMPLING.search(model) is None


class TestAgainstRealAg2:
    def test_ag2_still_exposes_the_method_this_shim_patches(self):
        """The load-bearing assumption. If this fails, the shim is a no-op and
        every Claude call will 400 on `temperature`."""
        assert hasattr(ag2_anthropic, "AnthropicClient")
        assert callable(getattr(ag2_anthropic.AnthropicClient, "load_config", None))
