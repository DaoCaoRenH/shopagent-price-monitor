"""Model configuration and isolated credential loading."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
from typing import Any, Mapping
from .types import ModelFailure


@dataclass(frozen=True)
class ModelConfig:
    provider: str
    model: str
    base_url: str = "https://api.openai.com/v1"
    api_key_env: str = "OPENAI_API_KEY"
    credentials_file: str | None = None
    api_key_required: bool = True
    temperature: float = 0.0
    seed: int | None = None
    max_output_tokens: int = 256
    timeout_sec: float = 60.0
    max_retries: int = 2
    reasoning_effort: str = "none"
    send_reasoning_effort_none: bool = False
    max_context_tokens: int = 24576
    # Official OpenAI Responses supports strict function schemas.  Some
    # compatible providers only accept standard JSON Schema, especially for
    # dynamic dictionaries whose additionalProperties is itself a schema.
    strict_tool_schema: bool = True
    # Most calls require one tool; some reasoning providers need auto instead.
    tool_choice: str = "required"
    # OpenAI Responses can return SSE events.  Keep the switch explicit so a
    # compatible gateway can fall back to the stable JSON envelope if needed.
    stream: bool = False
    # Loaded only from an ignored credentials JSON file.  Keep it out of the
    # dataclass repr/equality so reports and diagnostics cannot expose it.
    _credential_api_key: str | None = field(default=None, repr=False, compare=False)

    @classmethod
    def from_file(cls, path: str | Path) -> "ModelConfig":
        config_path = Path(path).expanduser().resolve()
        try:
            value = json.loads(config_path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise ModelFailure(f"unable to read model config file: {config_path}") from exc
        except json.JSONDecodeError as exc:
            raise ModelFailure(f"invalid model config JSON: {config_path}") from exc
        return cls.from_mapping(value, base_dir=config_path.parent)

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, Any],
        *,
        base_dir: str | Path | None = None,
    ) -> "ModelConfig":
        if not isinstance(value, Mapping):
            raise ModelFailure("model config must be an object")
        value = dict(value)
        if "max_context_chars" in value:
            raise ModelFailure("context window settings must use max_context_tokens")
        credentials_file = _resolve_credentials_file(value.get("credentials_file"), base_dir=base_dir)
        credential_api_key: str | None = None
        if credentials_file is not None:
            credentials = _load_credentials_file(credentials_file)
            if "base_url" in credentials:
                base_url = credentials["base_url"]
                if not isinstance(base_url, str) or not base_url.strip():
                    raise ModelFailure(f"credentials file has an invalid base_url: {credentials_file}")
                value["base_url"] = base_url.strip()
            credential_api_key = _read_credential_api_key(credentials, credentials_file)
        provider = str(value.get("provider", "openai-responses")).strip().casefold()
        if provider in {"openai", "openai-responses", "openai_response"}:
            canonical_provider = "openai-responses"
            default_base_url = "https://api.openai.com/v1"
            default_api_key_env = "OPENAI_API_KEY"
        elif provider in {
            "openai-chat",
            "openai-chat-completions",
            "openai_chat",
            "llama.cpp",
            "llama-cpp",
        }:
            canonical_provider = "openai-chat"
            default_base_url = "http://127.0.0.1:8080/v1"
            default_api_key_env = "OPENAI_API_KEY"
        else:
            raise ModelFailure(f"unsupported provider: {provider}")
        model = str(value.get("model", "")).strip()
        if not model:
            raise ModelFailure("model must be non-empty")
        env_value = value.get("api_key_env", default_api_key_env)
        if isinstance(env_value, list):
            env_value = env_value[0] if env_value else "OPENAI_API_KEY"
        api_key_env = str(env_value).strip() or default_api_key_env
        reasoning = value.get("reasoning", {})
        if isinstance(reasoning, str):
            reasoning = {"effort": reasoning}
        if not isinstance(reasoning, Mapping):
            raise ModelFailure("reasoning config must be an object or string")
        effort = reasoning.get("effort", value.get("reasoning_effort", "none"))
        effort = str(effort).strip().casefold()
        if effort not in {"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"}:
            raise ModelFailure(f"unsupported reasoning effort: {effort}")
        send_reasoning_effort_none = value.get("send_reasoning_effort_none", False)
        if not isinstance(send_reasoning_effort_none, bool):
            raise ModelFailure("send_reasoning_effort_none must be a boolean")
        strict_tool_schema = value.get("strict_tool_schema", True)
        if not isinstance(strict_tool_schema, bool):
            raise ModelFailure("strict_tool_schema must be a boolean")
        tool_choice = str(value.get("tool_choice", "required")).strip().casefold()
        if tool_choice not in {"auto", "required"}:
            raise ModelFailure("tool_choice must be 'auto' or 'required'")
        stream = value.get("stream", False)
        if not isinstance(stream, bool):
            raise ModelFailure("stream must be a boolean")
        api_key_required = value.get("api_key_required", True)
        if not isinstance(api_key_required, bool):
            raise ModelFailure("api_key_required must be a boolean")
        return cls(
            provider=canonical_provider,
            model=model,
            base_url=str(value.get("base_url", default_base_url)).rstrip("/"),
            api_key_env=api_key_env,
            credentials_file=(str(credentials_file) if credentials_file is not None else None),
            api_key_required=api_key_required,
            temperature=float(value.get("temperature", 0.0)),
            seed=(None if value.get("seed") is None else int(value.get("seed"))),
            max_output_tokens=max(1, int(value.get("max_output_tokens", 256))),
            timeout_sec=max(1.0, float(value.get("timeout_sec", 60.0))),
            max_retries=max(0, min(5, int(value.get("max_retries", 2)))),
            reasoning_effort=effort,
            send_reasoning_effort_none=send_reasoning_effort_none,
            max_context_tokens=max(1, int(value.get("max_context_tokens", 24576))),
            strict_tool_schema=strict_tool_schema,
            tool_choice=tool_choice,
            stream=stream,
            _credential_api_key=credential_api_key,
        )


def _resolve_credentials_file(
    value: Any,
    *,
    base_dir: str | Path | None,
) -> Path | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ModelFailure("credentials_file must be a non-empty path string")
    path = Path(os.path.expandvars(os.path.expanduser(value.strip())))
    if not path.is_absolute() and base_dir is not None:
        path = Path(base_dir) / path
    return path.resolve()


def _load_credentials_file(path: Path) -> Mapping[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ModelFailure(f"unable to read credentials file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ModelFailure(f"invalid credentials JSON: {path}") from exc
    if not isinstance(raw, Mapping):
        raise ModelFailure(f"credentials file must contain a JSON object: {path}")
    return raw


def _read_credential_api_key(credentials: Mapping[str, Any], path: Path) -> str:
    value = credentials.get("api_key")
    if not isinstance(value, str) or not value.strip():
        raise ModelFailure(f"credentials file has no non-empty api_key: {path}")
    return value.strip()


def _resolve_api_key(config: ModelConfig, explicit_api_key: str | None) -> str | None:
    if explicit_api_key is not None:
        return explicit_api_key.strip() or None
    if not config.api_key_required:
        return None
    if config._credential_api_key:
        return config._credential_api_key
    value = os.getenv(config.api_key_env)
    if value:
        return value.strip()
    raise ModelFailure(f"missing API key environment variable: {config.api_key_env}")
