"""Concrete, credential-redacted diagnostics for the local connection test."""

from __future__ import annotations

import json
import os
import re
import socket
import ssl
from urllib.parse import quote, quote_plus, urlsplit, urlunsplit
from urllib.error import HTTPError, URLError

from ..llm.model import ModelConfig, ModelResponseError


def redact_detail(text: str, config: ModelConfig) -> str:
    key = config._credential_api_key or (os.getenv(config.api_key_env, "").strip() if config.api_key_required else "")
    if key:
        variants = {
            key,
            quote(key, safe=""),
            quote_plus(key),
            json.dumps(key)[1:-1],
            key.replace("sk-", "<redacted-key-prefix>"),
        }
        for value in sorted(variants, key=len, reverse=True):
            text = text.replace(value, "[密钥已隐藏]")
            # Provider adapters truncate messages: also mask a reflected key cut at that boundary.
            if len(value) >= 8:
                text = re.sub(re.escape(value[:8]) + r"[\w./+%<>=-]*", "[密钥已隐藏]", text)
    text = re.sub(r"(?i)\bBearer\s+[^\s\"'<>;,]+", "Bearer [密钥已隐藏]", text)
    text = re.sub(r"(?:sk-|<redacted-key-prefix>)[\w-]+", "[密钥已隐藏]", text)
    text = re.sub(
        r"""(?ix)(\b(?:api[_-]?key|x-goog-api-key|authorization|access[_-]?token|token|password|secret)
        ["']?\s*[:=]\s*)(?:"[^"]*"|'[^']*'|[^\s,;}\]]+)""",
        lambda match: match[1] + "[密钥已隐藏]",
        text,
    )

    def safe_url(match: re.Match) -> str:
        try:
            parsed = urlsplit(match[0])
            return urlunsplit((parsed.scheme, parsed.netloc.rsplit("@", 1)[-1], parsed.path, "", ""))
        except ValueError:
            return "[无效地址]"

    text = re.sub(r"""https?://[^\s"'<>]+""", safe_url, text)
    text = "".join(c for c in text if c in "\n\t" or ord(c) >= 32)
    return text[:1500] + ("…（内容已截断）" if len(text) > 1500 else "")


def connection_error(exc: Exception, config: ModelConfig) -> dict:
    chain: list[BaseException] = []
    current: BaseException | None = exc
    while current is not None and len(chain) < 8 and all(current is not item for item in chain):
        chain.append(current)
        reason = current.reason if isinstance(current, URLError) else None
        current = current.__cause__ or (reason if isinstance(reason, BaseException) else None)
    # Backends chain the underlying failure. Keep its useful reason rather than retry-wrapper text.
    detail = redact_detail(str(chain[-1]) or type(chain[-1]).__name__, config)
    combined = " ".join(str(item) for item in chain).casefold()
    status = next((item.code for item in chain if isinstance(item, HTTPError)), None)
    if status is None:
        match = re.search(r"\bHTTP\s+(\d{3})\b", combined, flags=re.IGNORECASE)
        status = int(match[1]) if match else None

    kind, summary = "unexpected_error", "请求发生异常。"
    if status:
        kind = "http_error"
        summary = {
            400: "模型服务拒绝请求，请查看返回的参数错误。",
            401: "模型服务拒绝认证，请检查 API Key。",
            403: "模型服务拒绝访问，请检查密钥权限。",
            404: "接口或模型不存在，请检查根地址、模型名称和协议。",
            405: "接口不接受此请求方式，请检查协议和地址。",
            408: "模型服务处理请求超时。",
            413: "请求超过服务允许的大小或上下文限制。",
            429: "请求受限或额度不足，请查看服务返回的原因。",
        }.get(status, "模型服务内部错误。" if status >= 500 else "模型服务返回错误。")
        summary = f"HTTP {status}，{summary}"
    elif "missing api key" in combined:
        kind, summary = "missing_api_key", "未提供 API Key，请填写密钥或关闭需要认证。"
    elif any(isinstance(item, (ssl.SSLError, ssl.CertificateError)) for item in chain):
        kind, summary = "tls_error", "TLS 连接或证书校验失败。"
    elif any(isinstance(item, TimeoutError) for item in chain) or "timed out" in combined:
        kind, summary = "timeout", f"请求等待超时，配置的无响应等待上限为 {config.timeout_sec:g} 秒。"
    elif any(isinstance(item, ConnectionRefusedError) for item in chain) or any(
        value in combined for value in ("connection refused", "actively refused", "积极拒绝", "10061")
    ):
        kind, summary = "connection_refused", "连接被拒绝，请确认模型服务已启动且端口正确。"
    elif any(isinstance(item, socket.gaierror) for item in chain):
        kind, summary = "dns_error", "无法解析模型服务域名。"
    elif any(isinstance(item, (URLError, ConnectionError)) for item in chain):
        kind, summary = "network_error", "无法连接模型服务，请查看网络错误。"
    elif isinstance(exc, ModelResponseError):
        kind, summary = "invalid_response", "服务响应格式不符合所选协议或未返回有效工具调用。"

    suffix = {
        "openai-responses": "/responses",
        "openai-chat": "/chat/completions",
    }[config.provider]
    return {
        "ok": False,
        "message": "连接测试失败：" + summary,
        "error": {
            "kind": kind,
            "exception_type": type(chain[-1]).__name__,
            "http_status": status,
            "detail": detail,
            "endpoint": redact_detail(config.base_url.rstrip("/") + suffix, config),
        },
    }
