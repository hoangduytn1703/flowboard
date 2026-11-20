"""Provider registry + ``run_llm`` dispatch.

The single entry point used by ``prompt_synth``, ``vision``, ``planner``.
Looks up the configured provider — plus that feature's pinned model and
reasoning effort — runs the capability gates (vision attachment vs.
text-only provider), then delegates to the provider's ``run()``.

Three CLI-backed providers are registered (Claude, Gemini (which drives
the ``agy`` CLI — see ``gemini.py`` for why the id outlived the binary),
OpenAI Codex) plus ``muse`` — the assistant itself (Pax), fulfilled through
the provider-job queue instead of a subprocess. xAI Grok was previously wired up but never shipped a usable
end-user CLI, so it was dropped from both UI and registry.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Literal, Optional

from .base import LLMError, LLMProvider
from .claude import ClaudeProvider
from .gemini import GeminiProvider
from .muse import MuseProvider
from .openai import OpenAIProvider
from . import secrets

logger = logging.getLogger(__name__)


Feature = Literal["auto_prompt", "vision", "planner", "chat_agent"]


# Module-level singletons. Each provider class has cheap probe state
# (e.g. cached `--version` result, cached model catalog) so re-instantiating
# per call would defeat the cache. Same lifetime as the agent process.
_PROVIDERS: dict[str, LLMProvider] = {
    "claude": ClaudeProvider(),
    "gemini": GeminiProvider(),
    "openai": OpenAIProvider(),
    "muse": MuseProvider(),
}


#: Which AI answers every ``run_llm`` in this context, whatever the feature config says: "claude" (the Claude CLI) |
#: "gemini" (the Gemini API key pool, services/llm/gemini_api) | None (the config). Set with :func:`use_ai` — the
#: auto posting schedule (services/autopilot) lets the seller pick per schedule. A ContextVar, so it follows the
#: awaits and tasks of that one job only.
AI_OVERRIDE: ContextVar[Optional[str]] = ContextVar("flowboard_ai_override", default=None)
AI_CHOICES = ("claude", "gemini")
#: Gemini model for writing through the key pool: 3.5-flash writes well in ~20 s (3.8-flash took over 40 s).
GEMINI_TEXT_MODEL = "gemini-3.5-flash"


@contextmanager
def use_ai(choice: Optional[str]):
    """Inside the block every ``run_llm`` goes to ``choice`` ("claude" | "gemini"; anything else = the config)."""
    token = AI_OVERRIDE.set(choice if choice in AI_CHOICES else None)
    try:
        yield
    finally:
        AI_OVERRIDE.reset(token)


async def _run_gemini_keys(user_prompt: str, *, system_prompt: Optional[str], attachments: Optional[list[str]],
                           timeout: float) -> str:
    from . import gemini_api

    if not gemini_api.configured():
        raise LLMError("Chưa có Gemini API key — thêm ở Cài đặt → Gemini key.")
    logger.info("llm: provider=gemini-key model=%s attachments=%d", GEMINI_TEXT_MODEL, len(attachments or []))
    try:
        return await gemini_api.generate_text(user_prompt, system=system_prompt, attachments=attachments,
                                              model=GEMINI_TEXT_MODEL, timeout=timeout)
    except gemini_api.GeminiAPIError as exc:
        raise LLMError(f"Gemini: {exc}") from exc


#: said when nothing can answer — the seller's words, with where to fix it (the English tail is matched by chat_agent)
NO_AI = ("Chưa có AI nào dùng được trên tài khoản này: thêm Gemini API key (miễn phí) ở Cài đặt → 🔑 Gemini key, "
         "hoặc chọn AI ở Cài đặt → 🤖 AI viết.")


def _gemini_keys_ready() -> bool:
    from . import gemini_api

    try:
        return bool(gemini_api.configured())
    except Exception:  # noqa: BLE001 — a broken secrets store is "no keys"
        return False


async def picked_ai(feature: Feature, *, vision: bool = False) -> Optional[str]:
    """The AI the account picked for ``feature`` when it runs on this machine
    (and reads images when ``vision``) — None when nothing is picked or it
    cannot run here. The Gemini keys stand-in does not count."""
    entry = secrets.read_feature_config().get(feature)
    provider = _PROVIDERS.get(entry["provider"]) if entry else None
    if provider is None or (vision and not provider.supports_vision):
        return None
    try:
        return entry["provider"] if await provider.is_available() else None
    except Exception:  # noqa: BLE001 — a probe that breaks is "not here"
        return None


def get_provider(name: str) -> Optional[LLMProvider]:
    """Lookup by name. None if the name is unknown."""
    return _PROVIDERS.get(name)


def list_providers() -> list[LLMProvider]:
    """All registered providers, in deterministic order."""
    return list(_PROVIDERS.values())


async def run_llm(
    feature: Feature,
    user_prompt: str,
    *,
    system_prompt: Optional[str] = None,
    attachments: Optional[list[str]] = None,
    timeout: float = 90.0,
    effort: Optional[str] = None,
    gemini_backup: bool = True,
) -> str:
    """Feature-routed LLM dispatch.

    ``effort`` replaces the feature's pinned reasoning effort for this one
    call (a job that needs speed over depth). ``gemini_backup=False`` skips
    the account's Gemini keys as a stand-in for a missing / failing AI (a
    caller that already raced Gemini itself).

    Resolution chain:
      1. Look up the configured provider / model / effort for ``feature``
         in ``~/.flowboard/secrets.json``. No defaults — if the user
         hasn't picked a provider yet, raise loud so the UI's forced-setup
         gate intercepts before the call lands. Model and effort MAY be
         unset even when the provider is pinned; unset means "don't pass
         the flag", so the CLI's own configured default applies.
      2. Vision capability gate — if ``attachments`` is non-empty and the
         provider declares ``supports_vision = False``, raise immediately
         (no model call). Defense in depth alongside the per-provider
         attachment-rejection inside ``run()``.
      3. Availability gate — if the provider's CLI is missing or its API
         key isn't configured, raise immediately so the caller doesn't
         eat a longer subprocess / HTTP timeout.
      4. Effort re-check — see below.
      5. Dispatch.
    """
    config = secrets.read_feature_config()
    pick = AI_OVERRIDE.get()
    if pick == "gemini":
        return await _run_gemini_keys(user_prompt, system_prompt=system_prompt, attachments=attachments, timeout=timeout)
    if pick == "claude":
        # the Claude CLI the seller already uses: their pinned model / effort when Claude is the configured provider
        entry = config.get(feature)
        same = bool(entry) and entry.get("provider") == "claude"
        config = {**config, feature: {"provider": "claude", "model": entry.get("model") if same else None,
                                      "effort": entry.get("effort") if same else None}}
    entry = config.get(feature)
    # A new account has picked no AI yet, and a picked CLI can be missing on this machine (the installed app on a
    # friend's PC has no Claude CLI): the account's Gemini keys answer instead of an error — "install and it works".
    # Not when a caller asked for one AI by name (use_ai): that choice is kept.
    backup = gemini_backup and pick is None and _gemini_keys_ready()

    async def by_keys(why: str) -> str:
        logger.info("llm: feature=%s answered by the Gemini keys (%s)", feature, why)
        return await _run_gemini_keys(user_prompt, system_prompt=system_prompt, attachments=attachments, timeout=timeout)

    if entry is None:
        if backup:
            return await by_keys("no provider picked")
        raise LLMError(f"{NO_AI} (No AI provider configured for {feature})")
    provider_name = entry["provider"]
    model = entry.get("model")
    effort = effort or entry.get("effort")
    provider = _PROVIDERS.get(provider_name)
    if provider is None:
        raise LLMError(
            f"Unknown provider {provider_name!r} configured for {feature}; "
            f"reconfigure in Settings → AI Providers."
        )

    if attachments and not provider.supports_vision:
        raise LLMError(
            f"{provider_name} doesn't support vision; "
            f"reconfigure Vision provider in Settings → AI Providers."
        )

    if not await provider.is_available():
        if backup:
            return await by_keys(f"{provider_name} is not on this machine")
        raise LLMError(
            f"AI đã chọn ({provider_name}) không chạy được trên máy này — {NO_AI} "
            f"{provider_name} is not configured "
            f"(CLI missing or API key not set); "
            f"reconfigure in Settings → AI Providers."
        )

    # Defense in depth. `effort` came out of secrets.json, which the HTTP
    # layer validates on the way in — but that file is on disk and
    # hand-editable, a provider's ladder can shrink under a config written
    # against the old one, and this value ends up inside a CLI flag
    # (`-c model_reasoning_effort="…"` for Codex). Dropping an
    # unrecognised value costs the user their effort pin for this call and
    # leaves the CLI's own default in place; passing it through would put
    # an unchecked string on the command line. The model is deliberately
    # NOT re-checked here: unknown-but-valid model ids are the documented
    # escape hatch (see routes/llm.py's `_validate_model`).
    if effort is not None:
        allowed = list(getattr(provider, "efforts", []) or [])
        if allowed and effort not in allowed:
            logger.warning(
                "llm: dropping unknown effort %r for provider=%s feature=%s "
                "(accepts %s); falling back to the CLI's own setting",
                effort, provider_name, feature, ", ".join(allowed),
            )
            effort = None

    logger.info(
        "llm: provider=%s feature=%s model=%s effort=%s attachments=%d",
        provider_name, feature, model or "-", effort or "-",
        len(attachments) if attachments else 0,
    )
    try:
        return await provider.run(
            user_prompt,
            system_prompt=system_prompt,
            attachments=attachments,
            timeout=timeout,
            model=model,
            effort=effort,
        )
    except LLMError as exc:
        # the picked AI failed (out of quota, the CLI logged out…): the Gemini keys get one try before the error
        if not backup:
            raise
        logger.warning("llm: provider=%s failed for %s (%s) — trying the Gemini keys", provider_name, feature, str(exc)[:200])
        try:
            return await by_keys(f"{provider_name} failed")
        except LLMError:
            raise exc from None
