"""Compatibility shim for AG2's Anthropic client.

AG2 (as of 0.14.0) always sends `temperature` (defaulting to 1.0) and cannot be
configured to omit it. Claude Opus 4.7/4.8 and the Fable/Mythos models **reject**
`temperature`/`top_p`/`top_k` with HTTP 400. This shim strips those sampling
parameters for the affected models, so the configured default (`claude-opus-4-8`)
works without downgrading the model.

It patches `AnthropicClient.load_config`, the single point every create path
funnels through. The patch is idempotent and a no-op for models that still
accept sampling params (e.g. Sonnet 4.6, Opus 4.6).
"""

from __future__ import annotations

import re

from autogen.oai import anthropic as _az

# Models that reject temperature/top_p/top_k (sampling params removed in the API).
_REJECTS_SAMPLING = re.compile(r"opus-4-(?:7|8)|fable|mythos", re.IGNORECASE)

_PATCH_FLAG = "_research_assistant_sampling_patch"
_UNSUPPORTED_KEYS = ("temperature", "top_p", "top_k")


def patch_ag2_anthropic_sampling() -> None:
    """Idempotently patch AG2 so sampling params are dropped for 4.7+/Fable models."""
    client_cls = _az.AnthropicClient
    if getattr(client_cls, _PATCH_FLAG, False):
        return

    original_load_config = client_cls.load_config

    def load_config(self, params):  # type: ignore[no-untyped-def]
        config = original_load_config(self, params)
        model = config.get("model") or ""
        if _REJECTS_SAMPLING.search(model):
            for key in _UNSUPPORTED_KEYS:
                config.pop(key, None)
        return config

    client_cls.load_config = load_config
    setattr(client_cls, _PATCH_FLAG, True)
