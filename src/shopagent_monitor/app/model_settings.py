"""Local model settings, isolated credentials, and atomic agent replacement."""

from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import threading
import time
from typing import Literal
from urllib.parse import urlsplit
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..llm.messages import ModelContext, UserMessage
from ..llm.model import ModelConfig, ModelFailure, create_model_backend
from .agent import MonitoringAgent
from .domain import MonitorError
from .model_errors import connection_error
from .model_requests import CONTEXT_MARGIN_TOKENS, DEFAULT_CONTEXT_TOKENS, generate_bounded
from .search_limits import SearchLimits
from .search_progress import SearchCancelled, SearchProgress


class ModelSettingsInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    enabled: bool = Field(default=True, strict=True)
    provider: Literal["openai-responses", "openai-chat"] = "openai-responses"
    model: str = Field(min_length=1, max_length=200)
    base_url: str = Field(min_length=1, max_length=500)
    api_key_required: bool = Field(default=False, strict=True)
    api_key: str | None = Field(default=None, max_length=4096, repr=False)
    clear_api_key: bool = Field(default=False, strict=True)
    timeout_sec: float = Field(default=12, ge=1, le=120, allow_inf_nan=False)
    max_output_tokens: int = Field(default=768, ge=128, le=4096, strict=True)
    temperature: float = Field(default=0, ge=0, le=2, allow_inf_nan=False)
    strict_tool_schema: bool = Field(default=False, strict=True)
    stream: bool = Field(default=True, strict=True)
    max_retries: int = Field(default=2, ge=0, le=5, strict=True)
    reasoning_effort: Literal["none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"] = "none"
    max_context_tokens: int = Field(default=DEFAULT_CONTEXT_TOKENS, ge=2048, le=2097152, strict=True)
    search_limits: SearchLimits = Field(default_factory=SearchLimits)

    @field_validator("base_url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        try:
            parsed = urlsplit(value)
            valid = (
                parsed.scheme in {"http", "https"}
                and parsed.hostname
                and parsed.port != 0
                and not parsed.username
                and not parsed.password
                and not parsed.query
                and not parsed.fragment
                and not any(c.isspace() or ord(c) < 32 for c in value)
            )
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("服务地址须为 HTTP(S) 根地址，不能包含密钥、查询参数或账号")
        return value.rstrip("/")

    @model_validator(mode="after")
    def validate_key_action(self):
        if self.provider != "openai-responses":
            self.stream = False
        if self.api_key and self.clear_api_key:
            raise ValueError("请在替换与清除 API Key 中选择一种操作")
        if self.max_context_tokens <= self.max_output_tokens + CONTEXT_MARGIN_TOKENS:
            raise ValueError("上下文长度须大于最大输出 Token 加 256 Token 安全余量")
        return self


DEFAULT = ModelSettingsInput(
    enabled=False,
    model="deepseek-v4.1-flash",
    base_url="https://api.example.com/v1",
    api_key_required=True,
)
FIELDS = (
    "provider",
    "model",
    "base_url",
    "api_key_required",
    "timeout_sec",
    "max_output_tokens",
    "temperature",
    "strict_tool_schema",
    "reasoning_effort",
    "max_context_tokens",
    "stream",
    "max_retries",
)


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            os.chmod(temporary, 0o600)
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class ModelSettings:
    def __init__(self, agent: MonitoringAgent, *, path: str | Path | None = None, start_disabled: bool = False):
        self.path = Path(path).resolve() if path else None
        self._lock = threading.RLock()
        self._model_lock = agent._model_lock
        self._agent = agent
        self._search_limits = agent.search_limits
        self._managed_credential: Path | None = None
        self._config = agent.config or ModelConfig.from_mapping(
            DEFAULT.model_dump(exclude={"api_key", "clear_api_key"}) | {"api_key_env": "SHOPAGENT_MODEL_API_KEY"}
        )
        self._enabled = agent.backend is not None
        self.revision = uuid4().hex
        self.load_error: str | None = None
        if self.path and self.path.exists():
            try:
                value = json.loads(self.path.read_text(encoding="utf-8"))
                config = ModelConfig.from_file(self.path)
                # Old Web files already used nested reasoning and may omit the new fields.
                validated = ModelSettingsInput.model_validate(
                    {k: value[k] for k in (*FIELDS, "enabled", "search_limits") if k in value}
                    | {
                        "reasoning_effort": config.reasoning_effort,
                        "max_context_tokens": value.get("max_context_tokens", DEFAULT_CONTEXT_TOKENS),
                    }
                )
                config = replace(config, **{key: getattr(validated, key) for key in FIELDS})
                self._agent = MonitoringAgent(
                    agent.catalog,
                    config if validated.enabled else None,
                    model_lock=self._model_lock,
                    search_limits=validated.search_limits,
                )
                self._config, self._enabled = config, validated.enabled
                self._search_limits = validated.search_limits
                if config.credentials_file:
                    credential = Path(config.credentials_file)
                    if credential.parent == self.path.parent and credential.name.startswith("credentials-"):
                        self._managed_credential = credential
            except Exception:
                self.load_error = "已保存的模型配置无法加载，正在使用启动配置；请检查后重新保存。"
        if not self._config.api_key_required and not self._config._credential_api_key:
            # An unauthenticated local service must not inherit an unrelated global API key.
            self._config = replace(self._config, api_key_env="SHOPAGENT_MONITOR_API_KEY")
        if start_disabled:
            self._enabled = False
            self._agent = MonitoringAgent(agent.catalog, model_lock=self._model_lock, search_limits=self._search_limits)

    @property
    def agent(self) -> MonitoringAgent:
        with self._lock:
            return self._agent

    def active(self) -> tuple[MonitoringAgent, str]:
        with self._lock:
            return self._agent, self.revision

    def _has_key(self, config: ModelConfig) -> bool:
        return bool(
            config._credential_api_key or (config.api_key_required and os.getenv(config.api_key_env, "").strip())
        )

    def public(self) -> dict:
        with self._lock:
            return {key: getattr(self._config, key) for key in FIELDS} | {
                "enabled": self._enabled,
                "has_api_key": self._has_key(self._config),
                "revision": self.revision,
                "persistent": self.path is not None,
                "load_error": self.load_error,
                "search_limits": self._search_limits.model_dump(),
            }

    def _candidate(self, body: ModelSettingsInput) -> ModelConfig:
        config = replace(
            self._config,
            **{key: getattr(body, key) for key in FIELDS},
        )
        key = body.api_key or self._config._credential_api_key
        # Retaining a credential must never send it to a newly entered origin.
        changed_endpoint = body.base_url != self._config.base_url.rstrip("/") or body.provider != self._config.provider
        if not body.api_key and not body.clear_api_key and self._has_key(self._config) and changed_endpoint:
            if body.api_key_required:
                raise MonitorError("更换模型服务或接口协议时，请重新输入 API Key。")
            key = None
            config = replace(config, api_key_env="SHOPAGENT_MONITOR_NO_KEY")
        if body.clear_api_key:
            key = None
            config = replace(config, api_key_env="SHOPAGENT_MONITOR_NO_KEY")
        return replace(config, _credential_api_key=key, credentials_file=None)

    def save(self, body: ModelSettingsInput) -> dict:
        with self._lock:
            config = self._candidate(body)
            try:
                agent = MonitoringAgent(
                    self._agent.catalog,
                    config if body.enabled else None,
                    model_lock=self._model_lock,
                    search_limits=body.search_limits,
                )
            except ModelFailure:
                raise MonitorError("配置未保存：请填写 API Key，或关闭需要认证。") from None
            credential = None
            if self.path:
                try:
                    value = {key: getattr(config, key) for key in FIELDS} | {
                        "enabled": body.enabled,
                        "api_key_env": config.api_key_env,
                        "reasoning": {"effort": config.reasoning_effort},
                        "search_limits": body.search_limits.model_dump(),
                    }
                    if config._credential_api_key:
                        credential = self.path.with_name(f"credentials-{uuid4().hex}.json")
                        _atomic_json(credential, {"api_key": config._credential_api_key})
                        value["credentials_file"] = credential.name
                    _atomic_json(self.path, value)
                except OSError:
                    if credential:
                        credential.unlink(missing_ok=True)
                    raise MonitorError("配置未保存：无法写入本机配置文件，请检查目录权限。", status=500) from None
                # Commit the pointer first; deleting only this feature's previous credentials is safe.
                old = self._managed_credential
                config = replace(config, credentials_file=str(credential) if credential else None)
                if old:
                    old_path = Path(old)
                    if (
                        old_path.parent == self.path.parent
                        and old_path.name.startswith("credentials-")
                        and old_path != credential
                    ):
                        try:
                            old_path.unlink(missing_ok=True)
                        except OSError:
                            pass
                self._managed_credential = credential
            self._agent, self._config, self._enabled = agent, config, body.enabled
            self._search_limits = body.search_limits
            self.revision, self.load_error = uuid4().hex, None
            return self.public()

    def test(self, body: ModelSettingsInput, *, on_progress=None, cancelled=None) -> dict:
        with self._lock:
            config = self._candidate(body)
        if not self._model_lock.acquire(blocking=False):
            raise MonitorError("Agent 正在处理请求，请稍后测试连接。", status=409)
        started = time.monotonic()
        progress = SearchProgress(on_progress, cancelled)
        try:
            progress.emit("planning", "正在连接模型并验证原生工具调用", step_id="connection-model")
            # Monitoring owns retries of the current turn; disable backend retries
            # so retry counts and progress reflect the actual number of requests.
            backend = create_model_backend(replace(config, max_retries=0))
            result = generate_bounded(
                backend,
                context=ModelContext(
                    system_prompt="连接测试。请调用 connection_check 并传入 ok=true。",
                    messages=(UserMessage(role="user", content="请测试原生工具调用。"),),
                    tools=(
                        {
                            "name": "connection_check",
                            "description": "确认工具调用正常，不执行业务动作。",
                            "input_schema": {
                                "type": "object",
                                "properties": {"ok": {"type": "boolean"}},
                                "required": ["ok"],
                                "additionalProperties": False,
                            },
                        },
                    ),
                ),
                max_output_tokens=128 if config.reasoning_effort == "none" else config.max_output_tokens,
                max_context_tokens=config.max_context_tokens,
                max_retries=config.max_retries,
                on_progress=progress.model_callback("connection-model"),
                cancelled=cancelled,
            )
            if (
                result.tool_call is None
                or result.tool_call.name != "connection_check"
                or set(result.tool_call.arguments) != {"ok"}
                or result.tool_call.arguments["ok"] is not True
            ):
                if result.tool_call is None:
                    detail = "预期 connection_check({ok:true})，实际未返回工具调用。"
                else:
                    detail = (
                        f"预期 connection_check({{ok:true}})，实际工具为 {result.tool_call.name}，"
                        f"参数为 {json.dumps(dict(result.tool_call.arguments), ensure_ascii=False)}。"
                    )
                failure = connection_error(ModelFailure(detail), config)
                failure["message"] = "模型已响应，但工具调用未通过校验。"
                failure["error"]["kind"] = "invalid_tool_call"
                return failure
            progress.emit("completed", "工具调用与参数校验通过", step_id="connection-model", status="completed")
            return {
                "ok": True,
                "message": "连接成功，模型原生工具调用正常。",
                "latency_ms": round((time.monotonic() - started) * 1000),
            }
        except SearchCancelled:
            raise
        except Exception as exc:
            return connection_error(exc, config)
        finally:
            self._model_lock.release()
