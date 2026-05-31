"""统一的 LLM 客户端抽象层。

设计目标：让上层（reviewer）不关心底层用的是 DeepSeek 还是 Claude。
所有实现都接受 OpenAI 风格的 messages（[{"role": ..., "content": ...}]），
并返回纯文本字符串。通过 get_llm_client() 工厂按 .env 的 MODEL_PROVIDER 切换。

新增其他厂商（如 GPT）只需再实现一个 BaseLLMClient 子类并在工厂里注册。
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod

from dotenv import load_dotenv
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

# OpenAI 风格的消息类型别名
Message = dict[str, str]


def _is_retryable_error(exc: BaseException) -> bool:
    """仅对 429（限流）/ 5xx（服务端错误）/ 连接超时类错误重试。

    openai 与 anthropic 的 APIStatusError 子类都带 .status_code；
    连接/超时类（APIConnectionError / APITimeoutError）无 status_code，按类名识别。
    """
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status == 429 or status >= 500
    return type(exc).__name__ in {"APIConnectionError", "APITimeoutError"}


def _log_retry(retry_state) -> None:
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    logger.warning("LLM 调用重试 [%d/3]: %s", retry_state.attempt_number, exc)


# 指数退避：最多 3 次，间隔 ~1s/2s/4s（上限 10s），仅对可重试错误生效
_llm_retry = retry(
    retry=retry_if_exception(_is_retryable_error),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    before_sleep=_log_retry,
    reraise=True,
)


class BaseLLMClient(ABC):
    """所有 LLM 客户端的基类。

    子类需实现 chat()，输入 OpenAI 风格 messages，返回模型输出文本。
    属性 provider / model 用于在结果中标注本次使用的厂商与模型。
    last_usage 记录最近一次调用的 token 用量（供上层统计）。
    """

    provider: str = "base"

    def __init__(self, model: str) -> None:
        self.model = model
        self.last_usage: dict[str, int] = {"input_tokens": 0, "output_tokens": 0}

    @abstractmethod
    def chat(self, messages: list[Message], **kwargs) -> str:
        """发送一轮对话，返回模型输出的纯文本。"""
        raise NotImplementedError


class DeepSeekClient(BaseLLMClient):
    """DeepSeek 客户端，复用 openai SDK（DeepSeek 兼容 OpenAI 协议）。"""

    provider = "deepseek"

    def __init__(
        self,
        api_key: str,
        model: str = "deepseek-chat",
        base_url: str = "https://api.deepseek.com",
    ) -> None:
        super().__init__(model)
        # 延迟导入：未安装 openai 时只在真正使用 DeepSeek 才报错
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key, base_url=base_url)

    @_llm_retry
    def chat(self, messages: list[Message], **kwargs) -> str:
        # json_mode=True -> 让 DeepSeek 强制返回合法 JSON 对象
        if kwargs.pop("json_mode", False):
            kwargs.setdefault("response_format", {"type": "json_object"})
        resp = self._client.chat.completions.create(
            model=self.model,
            messages=messages,  # type: ignore[arg-type]
            **kwargs,
        )
        usage = getattr(resp, "usage", None)
        if usage:
            self.last_usage = {
                "input_tokens": getattr(usage, "prompt_tokens", 0) or 0,
                "output_tokens": getattr(usage, "completion_tokens", 0) or 0,
            }
        return resp.choices[0].message.content or ""


class ClaudeClient(BaseLLMClient):
    """Claude 客户端，使用 anthropic SDK（可选依赖）。

    会把 OpenAI 风格 messages 里的 system 角色抽出来作为 Claude 的 system 参数，
    并对 system 前缀打 prompt caching 断点（稳定前缀，跨请求复用）。
    """

    provider = "claude"

    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-5",
        max_tokens: int = 8000,
    ) -> None:
        super().__init__(model)
        # 延迟导入：anthropic 是可选依赖，仅在使用 Claude 时才需要
        import anthropic

        self._client = anthropic.Anthropic(api_key=api_key)
        self._max_tokens = max_tokens

    @_llm_retry
    def chat(self, messages: list[Message], **kwargs) -> str:
        # Claude 没有简单的 json_object 开关，依赖 prompt 约束输出 JSON，这里忽略该标志
        kwargs.pop("json_mode", None)
        # 拆出 system 与对话消息（Claude 的 system 是独立参数）
        system_parts = [m["content"] for m in messages if m["role"] == "system"]
        convo = [m for m in messages if m["role"] != "system"]

        params: dict = {
            "model": self.model,
            "max_tokens": kwargs.pop("max_tokens", self._max_tokens),
            "messages": convo,
        }
        if system_parts:
            # 稳定的 system 前缀打缓存断点
            params["system"] = [
                {
                    "type": "text",
                    "text": "\n\n".join(system_parts),
                    "cache_control": {"type": "ephemeral"},
                }
            ]
        params.update(kwargs)

        resp = self._client.messages.create(**params)
        usage = getattr(resp, "usage", None)
        if usage:
            self.last_usage = {
                "input_tokens": getattr(usage, "input_tokens", 0) or 0,
                "output_tokens": getattr(usage, "output_tokens", 0) or 0,
            }
        return "".join(b.text for b in resp.content if b.type == "text")


def get_llm_client() -> BaseLLMClient:
    """工厂：按 .env 的 MODEL_PROVIDER 返回对应的 LLM 客户端。

    MODEL_PROVIDER 默认 "deepseek"；可选 "claude" / "anthropic"。
    缺少对应 API Key 时抛出明确的 ValueError。
    """
    load_dotenv()
    provider = os.getenv("MODEL_PROVIDER", "deepseek").strip().lower()

    if provider == "deepseek":
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError("MODEL_PROVIDER=deepseek 但未配置 DEEPSEEK_API_KEY")
        return DeepSeekClient(
            api_key=api_key,
            model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        )

    if provider in ("claude", "anthropic"):
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError(
                f"MODEL_PROVIDER={provider} 但未配置 ANTHROPIC_API_KEY"
            )
        return ClaudeClient(
            api_key=api_key,
            model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5"),
        )

    raise ValueError(
        f"未知的 MODEL_PROVIDER: {provider!r}，支持 'deepseek' 或 'claude'"
    )
