"""Persisted CLI configuration (~/.config/adaptorch/config.json).

Railway-style credential store: `auth login` writes the tenant API key and the
resolved API URL here so every later command works without exporting
ADAPTORCH_API_KEY. `config set provider.*` wires a BYOK provider/model the same
way ADAPTORCH_PROVIDER* env vars do.

Precedence is always: environment variable > persisted config > built-in
default. Env wins so CI and one-shot overrides never fight stored state.

Secrets are stored as plain fields but the file is written mode 0600 and never
echoed back to stdout — `config get` and `auth status` mask them.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

CONFIG_DIR_ENV = "ADAPTORCH_CONFIG_DIR"
DEFAULT_API_URL = "https://adaptorch.com"

# user-facing key -> stored leaf under the "provider" object
_PROVIDER_KEY_MAP = {
    "provider.name": "provider",
    "provider.model": "model",
    "provider.api_key": "api_key",
}
_CONFIGURABLE_KEYS = frozenset({"api_url", *_PROVIDER_KEY_MAP})

# Keys whose values must never travel on argv or appear in stdout.
_SECRET_KEYS = frozenset({"provider.api_key"})


def config_dir() -> Path:
    override = os.environ.get(CONFIG_DIR_ENV)
    if override and override.strip():
        return Path(override.strip()).expanduser()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg and xdg.strip():
        return Path(xdg.strip()).expanduser() / "adaptorch"
    return Path.home() / ".config" / "adaptorch"


def config_path() -> Path:
    return config_dir() / "config.json"


def load_config() -> dict[str, Any]:
    path = config_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def save_config(config: dict[str, Any]) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def configurable_keys() -> tuple[str, ...]:
    return tuple(sorted(_CONFIGURABLE_KEYS))


def is_secret_key(key: str) -> bool:
    return key in _SECRET_KEYS


def get_config_value(key: str) -> str | None:
    config = load_config()
    if key == "api_url":
        value = config.get("api_url")
    elif key in _PROVIDER_KEY_MAP:
        provider = config.get("provider")
        leaf = _PROVIDER_KEY_MAP[key]
        value = provider.get(leaf) if isinstance(provider, dict) else None
    else:
        return None
    return value.strip() if isinstance(value, str) and value.strip() else None


def set_config_value(key: str, value: str) -> None:
    if key not in _CONFIGURABLE_KEYS:
        raise KeyError(key)
    config = load_config()
    if key == "api_url":
        config["api_url"] = value
    else:
        provider = config.setdefault("provider", {})
        if not isinstance(provider, dict):
            provider = {}
            config["provider"] = provider
        provider[_PROVIDER_KEY_MAP[key]] = value
    save_config(config)


def unset_config_value(key: str) -> bool:
    config = load_config()
    removed = False
    if key == "api_url":
        removed = "api_url" in config
        config.pop("api_url", None)
    elif key == "api_key":
        removed = "api_key" in config
        config.pop("api_key", None)
    elif key == "provider":
        removed = "provider" in config
        config.pop("provider", None)
    elif key in _PROVIDER_KEY_MAP:
        provider = config.get("provider")
        leaf = _PROVIDER_KEY_MAP[key]
        if isinstance(provider, dict) and leaf in provider:
            provider.pop(leaf, None)
            removed = True
        if isinstance(provider, dict) and not provider:
            config.pop("provider", None)
    else:
        return False
    if removed:
        save_config(config)
    return removed


def store_credentials(*, api_key: str, api_url: str) -> None:
    config = load_config()
    config["api_key"] = api_key
    config["api_url"] = api_url
    save_config(config)


def clear_credentials() -> bool:
    config = load_config()
    if "api_key" not in config:
        return False
    config.pop("api_key", None)
    save_config(config)
    return True


def resolve_api_key() -> tuple[str | None, str]:
    env_value = os.environ.get("ADAPTORCH_API_KEY")
    if env_value and env_value.strip():
        return env_value.strip(), "env"
    stored = load_config().get("api_key")
    if isinstance(stored, str) and stored.strip():
        return stored.strip(), "config"
    return None, "none"


def resolve_api_url(flag_value: str | None) -> tuple[str, str]:
    # Explicit --api-url wins over everything (same precedence the argparse
    # default gave it before); then env, then stored config, then default.
    if flag_value and flag_value.strip():
        return flag_value.strip(), "flag"
    env_value = os.environ.get("ADAPTORCH_API_URL")
    if env_value and env_value.strip():
        return env_value.strip(), "env"
    stored = get_config_value("api_url")
    if stored:
        return stored, "config"
    return DEFAULT_API_URL, "default"


def resolve_provider_credential() -> tuple[tuple[str, str, str] | None, str]:
    env_provider = os.environ.get("ADAPTORCH_PROVIDER", "").strip()
    env_model = os.environ.get("ADAPTORCH_PROVIDER_MODEL", "").strip()
    env_key = os.environ.get("ADAPTORCH_PROVIDER_API_KEY", "").strip()
    if env_provider or env_model or env_key:
        return (env_provider, env_model, env_key), "env"
    provider_cfg = load_config().get("provider")
    if isinstance(provider_cfg, dict):
        provider = str(provider_cfg.get("provider") or "").strip()
        model = str(provider_cfg.get("model") or "").strip()
        key = str(provider_cfg.get("api_key") or "").strip()
        if provider or model or key:
            return (provider, model, key), "config"
    return None, "none"


def mask_secret(value: str | None) -> str | None:
    if not value:
        return None
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}…{value[-4:]}"


def config_view() -> dict[str, Any]:
    config = load_config()
    provider_raw = config.get("provider")
    provider: dict[str, Any] = provider_raw if isinstance(provider_raw, dict) else {}
    stored_key = config.get("api_key")
    provider_key = provider.get("api_key")
    return {
        "api_url": config.get("api_url"),
        "api_key": mask_secret(stored_key if isinstance(stored_key, str) else None),
        "credential_source": resolve_api_key()[1],
        "provider": {
            "name": provider.get("provider"),
            "model": provider.get("model"),
            "api_key": mask_secret(provider_key if isinstance(provider_key, str) else None),
            "source": resolve_provider_credential()[1],
        },
        "config_path": str(config_path()),
    }
