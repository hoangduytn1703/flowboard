"""Local secret storage for the multi-LLM provider layer.

Schema of ``~/.flowboard/secrets.json``:

```json
{
  "apiKeys": {"openai": "sk-..."},
  "featureConfig": {
    "auto_prompt": {"provider": "gemini", "model": "gemini-3.8-flash-low", "effort": "low"},
    "vision":      {"provider": "gemini", "model": "gemini-3.8-flash-high", "effort": "high"},
    "planner":     {"provider": "claude", "model": "sonnet", "effort": "medium"}
  },
  "activeProviders": {
    "auto_prompt": "gemini",
    "vision": "gemini",
    "planner": "claude"
  }
}
```

**Why two blocks for the same thing.** ``activeProviders`` is the original
"which provider serves this feature" map. ``featureConfig`` is its
superset: same routing plus the per-feature model and reasoning effort.
Both are maintained, deliberately:

- **Read** prefers ``featureConfig`` and falls back to ``activeProviders``
  (provider only; model and effort come back ``None``). An install that
  upgraded from a pre-``featureConfig`` version keeps routing exactly
  where it was routing before, with the CLIs' own model defaults applying
  until the user picks something.
- **Write** updates *both*. If the user later downgrades Flowboard, the
  older build still finds ``activeProviders`` and keeps working instead of
  presenting a bricked, seemingly-unconfigured install.

The duplication costs a few bytes in a single-user JSON file and buys a
lossless upgrade/downgrade path in both directions. Drop ``activeProviders``
only once downgrades are no longer a concern.

Stored as plain JSON with file mode ``0o600`` (owner read/write only).
Single-user local app — OS-level file permissions are sufficient. We
deliberately don't encrypt; encryption adds a key-management surface
area without real benefit when the only attacker that matters has
already won (root on this user's box).

Writes are atomic (`tmp + replace`) so a crash mid-write can't corrupt
the file — readers either see the old contents or the new contents,
never a half-written file.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


_DEFAULT_PATH = Path.home() / ".flowboard" / "secrets.json"


def _path() -> Path:
    """Indirection so tests can monkeypatch the location.

    Tests typically set ``FLOWBOARD_SECRETS_PATH`` to a tmp file. Production
    callers leave the env var unset and the default ``~/.flowboard/secrets.json``
    applies.
    """
    override = os.environ.get("FLOWBOARD_SECRETS_PATH")
    return Path(override) if override else _DEFAULT_PATH


# ── Per-account storage ────────────────────────────────────────────────
#
# With login on, the document lives in the central store (``account_setting``
# key ``secrets:<username>`` — on Neon when FLOWBOARD_CENTRAL_DB_URL is set),
# so the keys follow the account to every machine. The first read on an
# account without one adopts this machine's ``secrets.json``. Without login
# (FLOWBOARD_AUTH=off, tests) the file is used as before.

_CACHE_TTL_S = 60.0
_cache: dict[str, tuple[float, dict]] = {}


def _account_scope() -> Optional[str]:
    """The username whose central document to use, or None for the file."""
    if os.environ.get("FLOWBOARD_SECRETS_PATH"):
        return None  # tests pin a file
    try:
        from flowboard import accounts
    except Exception:  # pragma: no cover - import cycle guard
        return None
    if not accounts.auth_enabled():
        return None
    user = accounts.active_user()
    return user["username"] if user else None


def _central_key(username: str) -> str:
    return f"secrets:{username}"


def _read_file() -> dict:
    p = _path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("secrets: file unreadable, treating as empty (%s)", exc)
        return {}


def forget_cache() -> None:
    _cache.clear()


def read() -> dict:
    """Load the full secrets document. Empty dict if nothing is stored —
    callers must handle missing keys themselves."""
    import time

    username = _account_scope()
    if username is None:
        return _read_file()
    hit = _cache.get(username)
    if hit and time.monotonic() - hit[0] < _CACHE_TTL_S:
        return json.loads(json.dumps(hit[1]))
    from flowboard import accounts

    doc = accounts.get_setting(_central_key(username))
    if not isinstance(doc, dict):
        doc = _read_file()
        if doc:
            accounts.set_setting(_central_key(username), doc)
            logger.info("secrets: adopted this machine's secrets.json for account %s", username)
        else:
            doc = {}
    _cache[username] = (time.monotonic(), doc)
    return json.loads(json.dumps(doc))


def write(payload: dict) -> None:
    """Persist the document: the account's central row when logged in,
    else an atomic file write with mode 0o600 (parent dir created)."""
    import time

    username = _account_scope()
    if username is not None:
        from flowboard import accounts

        accounts.set_setting(_central_key(username), payload)
        _cache[username] = (time.monotonic(), json.loads(json.dumps(payload)))
        return
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    # chmod BEFORE replace so the final file is never group/world-readable
    # even momentarily on filesystems that preserve permissions on rename.
    os.chmod(tmp, 0o600)
    tmp.replace(p)


# ── API key helpers ────────────────────────────────────────────────────

def get_api_key(provider: str) -> Optional[str]:
    """None if the key is unset OR if the file doesn't exist."""
    doc = read()
    keys = doc.get("apiKeys") or {}
    val = keys.get(provider)
    return val if isinstance(val, str) and val else None


def set_api_key(provider: str, key: Optional[str]) -> None:
    """Set or clear (key=None) a provider's API key.

    Clearing removes the entry entirely so ``get_api_key`` returns None
    cleanly without falsy-empty-string ambiguity.
    """
    doc = read()
    keys = dict(doc.get("apiKeys") or {})
    if key is None or not key:
        keys.pop(provider, None)
    else:
        keys[provider] = key
    doc["apiKeys"] = keys
    write(doc)


# ── Feature-config helpers ─────────────────────────────────────────────

# Features that must have a provider before setup counts as done. Order
# matters only for display; iteration order is deterministic on 3.7+.
_FEATURES: tuple[str, ...] = ("auto_prompt", "vision", "planner")
# Configurable but optional: unset means "use the Planner's pin" (see
# services/chat_agent.py), so adding it never re-opens the forced setup
# gate on an install that was already configured.
OPTIONAL_FEATURES: tuple[str, ...] = ("chat_agent",)


def _clean_str(val: object) -> Optional[str]:
    """Non-empty strings pass through; everything else becomes None.

    Guards every read path against a hand-edited secrets.json holding
    ``42`` or ``null`` where a provider / model / effort belongs.
    """
    return val if isinstance(val, str) and val else None


def read_feature_config() -> dict[str, dict]:
    """Return ``{feature: {"provider", "model", "effort"}}`` for every
    feature the user has configured.

    ``featureConfig`` wins when present. Otherwise the legacy
    ``activeProviders`` map supplies the provider and ``model``/``effort``
    come back ``None`` — see the module docstring for why both blocks
    exist. A feature with no provider anywhere is simply absent from the
    result; callers treat absence as "not configured" rather than
    substituting a default, so an unconfigured feature fails loudly in the
    dispatch path instead of silently routing somewhere the user didn't
    pick.
    """
    doc = read()
    feature_cfg = doc.get("featureConfig")
    if not isinstance(feature_cfg, dict):
        feature_cfg = {}
    legacy = doc.get("activeProviders")
    if not isinstance(legacy, dict):
        legacy = {}

    # File order, featureConfig first — deterministic without imposing an
    # order the file itself doesn't have.
    features = list(feature_cfg) + [f for f in legacy if f not in feature_cfg]

    out: dict[str, dict] = {}
    for feature in features:
        entry = feature_cfg.get(feature)
        if isinstance(entry, dict):
            provider = _clean_str(entry.get("provider"))
            if provider is not None:
                out[feature] = {
                    "provider": provider,
                    "model": _clean_str(entry.get("model")),
                    "effort": _clean_str(entry.get("effort")),
                }
                continue
        # Back-compat: a pre-featureConfig install, or a featureConfig
        # entry hand-edited into something unusable. The legacy block
        # carries the provider and nothing else, so model/effort stay
        # None rather than borrowing values from a mismatched entry.
        provider = _clean_str(legacy.get(feature))
        if provider is not None:
            out[feature] = {"provider": provider, "model": None, "effort": None}
    return out


def read_active_providers() -> dict[str, str]:
    """Return ``{feature: provider_name}`` for features the user has
    explicitly picked. No defaults — missing keys are absent.

    A thin projection of :func:`read_feature_config` kept for callers that
    only care about routing. Callers must handle the missing case (a
    feature with no provider pinned can't dispatch). The HTTP layer
    surfaces this via the ``configured`` flag on ``GET /api/llm/config``;
    the dispatch layer raises ``LLMError`` so the user sees a clear "open
    settings" message instead of silently falling back to a provider they
    didn't pick.
    """
    return {f: cfg["provider"] for f, cfg in read_feature_config().items()}


def is_active_providers_configured() -> bool:
    """True when every feature has a provider pinned.

    This used to additionally require all three features to point at the
    *same* provider (a single-provider UI invariant). That invariant is
    gone: the user now configures each feature independently — provider,
    model and reasoning effort — so a mixed config is the expected shape,
    not a legacy accident to nag about. The flag now means exactly what
    the forced-setup gate needs it to mean: "is there anywhere to route
    every feature?"
    """
    saved = read_feature_config()
    return all(f in saved for f in _FEATURES)


def set_feature_config(
    feature: str,
    provider: str,
    model: Optional[str] = None,
    effort: Optional[str] = None,
) -> None:
    """Pin one feature to a provider + optional model + optional effort.

    Caller validates all three (see ``routes/llm.py``). Writes both the
    ``featureConfig`` entry and the legacy ``activeProviders`` entry so a
    downgrade to an older Flowboard build still finds its routing — see
    the module docstring.

    ``model``/``effort`` of ``None`` are stored as JSON null rather than
    omitted, so "the user explicitly cleared this" and "this key predates
    the field" stay indistinguishable at the only place that matters:
    both mean "don't pass the flag".
    """
    doc = read()
    feature_cfg = dict(doc.get("featureConfig") or {})
    feature_cfg[feature] = {
        "provider": provider,
        "model": model,
        "effort": effort,
    }
    doc["featureConfig"] = feature_cfg

    legacy = dict(doc.get("activeProviders") or {})
    legacy[feature] = provider
    doc["activeProviders"] = legacy

    write(doc)


def set_feature_provider(feature: str, provider: str) -> None:
    """Pin one feature to one provider, leaving model/effort unset.

    Convenience wrapper over :func:`set_feature_config` for callers that
    only route (and for the many existing tests that predate model/effort
    selection).
    """
    set_feature_config(feature, provider)


# ── Gemini API key pool ────────────────────────────────────────────────
# Several keys, rotated when one runs out of quota (see gemini_api.py).
# Stored as a list under ``geminiApiKeys``; ``apiKeys.gemini`` is not used
# so the single-key helpers above keep their one-string contract.

def parse_keys(text: str) -> list[str]:
    """Keys pasted as one blob: split on whitespace / commas / semicolons,
    drop blanks and duplicates, keep order."""
    import re

    out: list[str] = []
    for tok in re.split(r"[\s,;]+", text or ""):
        tok = tok.strip().strip('"\'')
        if tok and tok not in out:
            out.append(tok)
    return out


def get_gemini_keys() -> list[str]:
    doc = read()
    keys = doc.get("geminiApiKeys")
    if not isinstance(keys, list):
        return []
    return [k for k in keys if isinstance(k, str) and k.strip()]


def set_gemini_keys(keys: list[str]) -> None:
    doc = read()
    cleaned: list[str] = []
    for k in keys:
        k = (k or "").strip()
        if k and k not in cleaned:
            cleaned.append(k)
    if cleaned:
        doc["geminiApiKeys"] = cleaned
    else:
        doc.pop("geminiApiKeys", None)
    write(doc)
