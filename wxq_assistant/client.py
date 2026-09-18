"""Explicit, bounded Chat Completions transport. No credentials in logs or files."""
from __future__ import annotations

import ipaddress
import json
import math
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from .state import strict_json

class ModelError(RuntimeError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ModelError("拒绝模型服务的HTTP重定向，避免凭据发送到其他地址")


@dataclass(frozen=True)
class Settings:
    base_url: str
    model: str
    api_key: str = ""
    timeout: float = 12.0
    token_field: str = "max_completion_tokens"
    output_tokens: int = 1400
    json_mode: bool = True

    def __post_init__(self):
        u = urllib.parse.urlsplit(self.base_url)
        local = u.hostname == "localhost"
        try:
            local = local or ipaddress.ip_address(u.hostname or "").is_loopback
        except ValueError:
            pass
        if not u.hostname or u.username or u.password or u.query or u.fragment:
            raise ValueError("模型base URL格式无效；不得包含凭据、查询参数或片段")
        if u.scheme != "https" and not (u.scheme == "http" and local):
            raise ValueError("非本机模型地址必须使用HTTPS")
        if not local and not self.api_key:
            raise ValueError("外部模型服务须通过WXQ_API_KEY配置凭据")
        if not self.model or any(x in self.model for x in "\r\n"):
            raise ValueError("必须配置有效的WXQ_MODEL")
        if not math.isfinite(self.timeout) or not 0.1 <= self.timeout <= 120:
            raise ValueError("模型超时必须为0.1..120秒")
        if self.token_field not in {"max_completion_tokens", "max_tokens"}:
            raise ValueError("WXQ_TOKEN_LIMIT_FIELD只允许max_completion_tokens或max_tokens")
        if type(self.output_tokens) is not int or not 128 <= self.output_tokens <= 8000:
            raise ValueError("输出token上限须为128..8000")

    @classmethod
    def from_env(cls, *, vision: bool = False) -> "Settings":
        model = os.environ.get("WXQ_VISION_MODEL", "") if vision else os.environ.get("WXQ_MODEL", "")
        return cls(base_url=os.environ.get("WXQ_BASE_URL", ""), model=model,
                   api_key=os.environ.get("WXQ_API_KEY", ""), timeout=float(os.environ.get("WXQ_TIMEOUT", "12")),
                   token_field=os.environ.get("WXQ_TOKEN_LIMIT_FIELD", "max_completion_tokens"),
                   output_tokens=int(os.environ.get("WXQ_OUTPUT_TOKENS", "1400")),
                   json_mode=os.environ.get("WXQ_JSON_MODE", "1") == "1")

    @property
    def host(self) -> str:
        return urllib.parse.urlsplit(self.base_url).netloc


class ModelClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    def complete_json(self, system: str, user: Any) -> dict[str, Any]:
        s = self.settings
        payload = {"model": s.model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}], s.token_field: s.output_tokens}
        if s.json_mode:
            payload["response_format"] = {"type": "json_object"}
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        headers = {"Content-Type": "application/json", "User-Agent": "wangxiangzs/0.1"}
        if s.api_key:
            headers["Authorization"] = "Bearer " + s.api_key
        req = urllib.request.Request(s.base_url.rstrip("/") + "/chat/completions", data=body, headers=headers, method="POST")
        try:
            with urllib.request.build_opener(NoRedirect()).open(req, timeout=s.timeout) as response:
                raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise ModelError("模型响应过大")
            data = strict_json(raw.decode("utf-8"))
            choice = data["choices"][0]
            if choice.get("finish_reason") == "length":
                raise ModelError("模型输出被截断，丢弃不完整建议")
            message = choice["message"]
            if message.get("refusal"):
                raise ModelError("模型未提供可用建议")
            content = message["content"]
            if not isinstance(content, str):
                raise ModelError("模型未返回JSON文本")
            parsed = strict_json(content)
            if not isinstance(parsed, dict):
                raise ModelError("模型JSON顶层必须为对象")
            return parsed
        except urllib.error.HTTPError as exc:
            # Do not print provider response bodies: they may reflect request data/credentials.
            raise ModelError(f"模型服务HTTP {exc.code}；检查地址、模型名、额度和权限。未自动重试。") from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ModelError("模型网络请求失败或超时；保留本地提醒，不显示旧建议。") from None
        except (KeyError, IndexError, TypeError, ValueError, UnicodeError) as exc:
            raise ModelError(f"模型输出格式无效：{type(exc).__name__}") from None
