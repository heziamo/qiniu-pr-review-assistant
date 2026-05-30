"""审查核心：调用 Claude 对 PR diff 进行代码审查。

Prompt caching 策略（见 Anthropic prompt-caching 最佳实践）：
- 缓存是「前缀匹配」：前缀任意一个字节变化都会让其后的缓存失效。
- 渲染顺序为 system -> messages，因此把【稳定不变】的审查规范放在 system 并打上
  cache_control 断点；把【每次都变】的 PR diff 放在 user message（断点之后）。
- 这样跨多次 PR 审查请求，庞大的审查规范前缀可被复用，节省约 90% 的输入成本。
- 通过 response.usage.cache_read_input_tokens 验证缓存是否命中。
"""

from __future__ import annotations

import anthropic

from .models import PullRequestDiff, ReviewResult

# —— 稳定前缀：审查规范。内容固定 => 可被 prompt cache 复用 ——
# 注意：切勿在此插入时间戳 / 随机 ID / 每请求变化的内容，否则缓存前缀失效。
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
    """使用 Claude 审查 PR diff。"""

    def __init__(self, api_key: str, model: str = "claude-opus-4-8") -> None:
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def review(self, pr: PullRequestDiff, max_tokens: int = 8000) -> ReviewResult:
        """对一个 PR diff 执行审查，返回结构化结果。

        使用流式请求 + 自适应思考；system 前缀打 cache_control 断点以启用 prompt caching。
        """
        diff_text = _render_diff(pr)

        with self._client.messages.stream(
            model=self._model,
            max_tokens=max_tokens,
            thinking={"type": "adaptive"},
            # 稳定的审查规范放 system 并缓存；易变的 diff 放 user message。
            system=[
                {
                    "type": "text",
                    "text": REVIEW_SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": diff_text}],
        ) as stream:
            message = stream.get_final_message()

        summary = "".join(
            block.text for block in message.content if block.type == "text"
        )
        usage = message.usage

        return ReviewResult(
            repo=pr.repo,
            pr_number=pr.pr_number,
            summary=summary,
            model=self._model,
            cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
            cache_creation_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
        )
