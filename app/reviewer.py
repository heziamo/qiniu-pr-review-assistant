"""审查核心：调用 LLM 对 PR diff 进行代码审查。

通过 app.llm_client.get_llm_client() 获取统一的 LLM 客户端（默认 DeepSeek，
可切换 Claude），本模块不直接依赖任何具体厂商 SDK。

Prompt caching：审查规范（REVIEW_SYSTEM_PROMPT）作为稳定的 system 前缀传入，
各客户端内部据此启用各自的缓存（Claude 显式打 cache_control 断点；DeepSeek
为服务端自动上下文缓存），跨多次 PR 审查复用，降低成本。
注意：切勿在 system 前缀里插入时间戳 / 随机 ID 等每请求变化的内容。
"""

from __future__ import annotations

from typing import Optional

from .llm_client import BaseLLMClient, get_llm_client
from .models import PullRequestDiff, ReviewResult

# —— 稳定前缀：审查规范。内容固定 => 可被各厂商的 prompt cache 复用 ——
REVIEW_SYSTEM_PROMPT = """\
你是一位资深的代码审查工程师，正在审查一个 GitHub Pull Request 的 diff。
请用中文输出一份结构化的审查报告（Markdown 格式），覆盖以下维度：

## 审查维度
1. **正确性**：逻辑错误、边界条件、空指针 / 越界、并发与竞态、错误处理是否完备。
2. **安全性**：注入、越权、敏感信息泄露、不安全的依赖或反序列化。
3. **可维护性**：命名、重复代码、过度复杂、缺少注释或文档。
4. **性能**：不必要的循环 / 查询、N+1、内存浪费。
5. **测试**：关键路径是否缺少测试覆盖。

## 输出格式
- 先给一段 **总体评价**（2~3 句）。
- 然后按 **文件** 分组列出问题，每条包含：
  - 严重程度：🔴 严重 / 🟡 中等 / 🟢 建议
  - 问题描述与所在位置（文件名 + 大致行号）
  - 具体的修改建议（必要时给出代码片段）
- 若某文件没有问题，简要说明即可，不要强行挑刺。
- 结尾给出 **是否建议合并** 的结论：✅ 可合并 / ⚠️ 需修改后合并 / ❌ 不建议合并。

请只报告你有把握的问题，并标注置信度；保持专业、具体、可执行。
"""


def _render_diff(pr: PullRequestDiff) -> str:
    """把 PR 元信息与文件 diff 拼成给模型的文本（这是每次变化的「易变」部分）。"""
    parts: list[str] = [
        f"# Pull Request #{pr.pr_number}: {pr.title}",
        f"仓库: {pr.repo}　作者: {pr.author}　{pr.base_ref} <- {pr.head_ref}",
        "",
        "## PR 描述",
        pr.description or "（无描述）",
        "",
        "## 变更文件 diff",
    ]
    for f in pr.files:
        parts.append(f"\n### {f.filename} ({f.status}, +{f.additions}/-{f.deletions})")
        if f.patch:
            parts.append(f"```diff\n{f.patch}\n```")
        else:
            parts.append("（无 diff 文本：可能是二进制文件或过大被省略）")
    return "\n".join(parts)


class PRReviewer:
    """使用 LLM 审查 PR diff。"""

    def __init__(self, client: Optional[BaseLLMClient] = None) -> None:
        # 默认按 .env 的 MODEL_PROVIDER 选择客户端；也可注入自定义实现（便于测试）
        self._client = client or get_llm_client()

    def review(self, pr: PullRequestDiff, max_tokens: int = 8000) -> ReviewResult:
        """对一个 PR diff 执行审查，返回结构化结果。"""
        diff_text = _render_diff(pr)

        messages = [
            {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
            {"role": "user", "content": diff_text},
        ]
        summary = self._client.chat(messages, max_tokens=max_tokens)

        return ReviewResult(
            repo=pr.repo,
            pr_number=pr.pr_number,
            summary=summary,
            provider=self._client.provider,
            model=self._client.model,
        )
