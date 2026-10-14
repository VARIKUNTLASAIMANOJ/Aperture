"""
Shared LLM factory — NVIDIA NIM Nemotron via LangChain OpenAI-compatible client.

NVIDIA NIM exposes an OpenAI-compatible API endpoint, so we use ChatOpenAI
pointed at the NIM base URL with the Nemotron model string.

Docs: https://docs.api.nvidia.com/nim/reference/nvidia-nemotron-4-340b-instruct
"""

from __future__ import annotations

import os

from langchain_openai import ChatOpenAI

DEFAULT_NIM_BASE_URL = "https://integrate.api.nvidia.com/v1"

# Model history on this account, because NIM retires models without notice and
# the failure mode is a hard 4xx at request time, not a warning:
#   llama-3.1-nemotron-ultra-253b-v1   404 — not exposed on standard keys
#   llama-3.3-nemotron-super-49b-v1.5  410 — end of life 2026-08-26
#
# Current default verified callable on 2026-10-08, with tool calling (which the
# voice agent needs) confirmed working. `nvidia/nemotron-3.5-lightning-30b-a3b`
# is the fallback if this one is retired. Override with NVIDIA_MODEL;
# GET {base_url}/models lists what a given key can actually call.
DEFAULT_NEMOTRON_MODEL = "nvidia/nemotron-3-super-120b-a12b"


def nim_config() -> tuple[str, str, str]:
    """
    Return (api_key, base_url, model) for the NVIDIA NIM endpoint.

    Split out of get_llm so the voice agent can point LiveKit's OpenAI-compatible
    LLM plugin at the SAME endpoint and model without importing LangChain into
    the realtime path, and without a second copy of the env-var names. NIM is
    OpenAI-compatible, which is the only reason reusing the project's existing
    LLM for voice is possible at all.
    """
    api_key = os.environ.get("NVIDIA_API_KEY", "")
    if not api_key:
        raise EnvironmentError(
            "NVIDIA_API_KEY env var is not set. "
            "Get your key at https://build.nvidia.com/"
        )
    return (
        api_key,
        os.environ.get("NVIDIA_NIM_BASE_URL", DEFAULT_NIM_BASE_URL),
        os.environ.get("NVIDIA_MODEL", DEFAULT_NEMOTRON_MODEL),
    )


def get_llm(temperature: float = 0.2) -> ChatOpenAI:
    """
    Return a ChatOpenAI client wired to NVIDIA NIM Nemotron-Ultra-253B.
    Drop-in replacement anywhere we previously used ChatOpenAI("gpt-4o").

    The environment is read HERE, not at module import. api/main.py imports
    core.graph — and therefore this module — before it calls load_dotenv(), so
    a module-level os.environ.get() captured an empty key and every contract
    generation failed with "NVIDIA_API_KEY env var is not set" even though the
    key was present in .env. Reading lazily makes the lookup independent of
    import order.
    """
    api_key  = os.environ.get("NVIDIA_API_KEY", "")
    base_url = os.environ.get("NVIDIA_NIM_BASE_URL", DEFAULT_NIM_BASE_URL)
    model    = os.environ.get("NVIDIA_MODEL", DEFAULT_NEMOTRON_MODEL)

    if not api_key:
        raise EnvironmentError(
            "NVIDIA_API_KEY env var is not set. "
            "Get your key at https://build.nvidia.com/"
        )
    return ChatOpenAI(
        model           = model,
        temperature     = temperature,
        openai_api_key  = api_key,   # type: ignore[arg-type]
        openai_api_base = base_url,  # type: ignore[arg-type]
        max_tokens      = 4096,
    )