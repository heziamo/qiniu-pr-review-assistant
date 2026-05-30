"""审查核心：调用 LLM 对 PR diff 进行结构化代码审查。

通过 app.llm_client.get_llm_client() 获取统一的 LLM 客户端（默认 DeepSeek，
可切换 Claude），本模块不直接依赖任何具体厂商 SDK。

Prompt 工程要点：
- 系统提示词明确角色（资深 code reviewer）并要求严格 JSON 输出。
- 输出结构：{summary, risks:[{file,line,severity,type,description,suggestion}], overall_score}。
- 风险分级 critical/high/medium/low；问题类型 bug/security/performance/style/maintainability。
- 大 PR 分块：单文件 diff 超过 MAX_FILE_LINES 行时按 hunk(@@) 拆成多块分别审查再合并。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Optional

from pydantic import ValidationError

from .llm_client import BaseLLMClient, get_llm_client
from .models import (
    ISSUE_TYPES,
    SEVERITY_LEVELS,
    _SEVERITY_ORDER,
    PullRequestDiff,
    ReviewResult,
    Risk,
)

# 单文件 diff 超过该行数时，按 hunk 拆分分块审查
MAX_FILE_LINES = 2000

# —— 稳定前缀：审查规范（JSON 版）。内容固定 => 可被各厂商 prompt cache 复用 ——
REVIEW_SYSTEM_PROMPT = f"""\
你是一位资深的代码审查工程师（senior code reviewer），擅长发现 bug、安全漏洞与可维护性问题。
你的任务：审查给定的 GitHub Pull Request diff，并输出结构化的审查结果。

【输出要求】严格只输出一个 JSON 对象，不要输出任何额外文字、解释或 Markdown 代码块（不要 ```）。
JSON 结构如下：
{{
  "summary": "对本次变更的总体评价（中文，2~4 句）",
  "risks": [
    {{
      "file": "问题所在文件路径",
      "line": 起始行号（整数；定位到具体行，无法定位则为 null）,
      "severity": "{' | '.join(SEVERITY_LEVELS)}",
      "type": "{' | '.join(ISSUE_TYPES)}",
      "description": "问题描述（中文，说明是什么问题、为何是问题）",
      "suggestion": "可执行的修改建议（中文，必要时给出代码片段）"
    }}
  ],
  "overall_score": 代码质量总分（整数 0~100，越高越好）
}}

【severity 分级标准】
- critical：会导致崩溃 / 数据损坏 / 安全漏洞，必须修复才能合并
- high：明显的 bug 或风险，强烈建议修复
- medium：潜在问题或不规范，建议修复
- low：风格 / 可读性等小建议

【type 含义】
- bug：逻辑错误、边界条件、空值 / 越界、错误处理缺失
- security：注入、越权、敏感信息泄露、不安全依赖
- performance：低效循环 / 查询、N+1、内存浪费
- style：命名、格式、注释等风格问题
- maintainability：重复代码、过度复杂、可维护性差

【规则】
- 只报告你有把握的问题；没有问题时 "risks" 返回空数组 []。
- "risks" 按 severity 从高到低排序。
- 不要臆造行号；diff 中无法确定具体行时 "line" 用 null。
- summary 与各字段一律用中文。
"""


@dataclass
class _ParsedReview:
    """单次 LLM 调用解析出的结构（合并前的中间结果）。"""

    summary: str = ""
    risks: list = field(default_factory=list)
    overall_score: int = 0


def _patch_line_count(patch: Optional[str]) -> int:
    return patch.count("\n") + 1 if patch else 0


def _split_patch_into_hunks(patch: str) -> list[str]:
    """按 `@@ ... @@` hunk 头把 unified diff 拆成多个 hunk（保留各自的 hunk 头）。"""
    hunks: list[str] = []
    current: list[str] = []
    for line in patch.splitlines(keepends=True):
        if line.startswith("@@") and current:
            hunks.append("".join(current))
            current = [line]
        else:
            current.append(line)
    if current:
        hunks.append("".join(current))
    return hunks


def _group_hunks(hunks: list[str], max_lines: int) -> list[str]:
    """把 hunk 贪心合并成若干组，每组行数尽量不超过 max_lines（单个超大 hunk 自成一组）。"""
    groups: list[str] = []
    current: list[str] = []
    current_lines = 0
    for h in hunks:
        n = h.count("\n") + 1
        if current and current_lines + n > max_lines:
            groups.append("".join(current))
            current, current_lines = [h], n
        else:
            current.append(h)
            current_lines += n
    if current:
        groups.append("".join(current))
    return groups


def _pr_header(pr: PullRequestDiff) -> str:
    return (
        f"# Pull Request #{pr.pr_number}: {pr.title}\n"
        f"仓库: {pr.repo}　作者: {pr.author}　{pr.base_ref} <- {pr.head_ref}\n\n"
        f"## PR 描述\n{pr.description or '（无描述）'}\n"
    )


def _render_file(filename: str, status: str, adds: int, dels: int, patch: Optional[str]) -> str:
    head = f"### {filename} ({status}, +{adds}/-{dels})\n"
    if patch:
        return head + f"```diff\n{patch}\n```\n"
    return head + "（无 diff 文本：二进制文件或过大被省略）\n"


def _build_chunks(pr: PullRequestDiff) -> list[tuple[str, str]]:
    """构造审查分块：(label, 提示文本)。

    - 普通文件合并进「主要变更」一块。
    - 单文件 diff 超过 MAX_FILE_LINES 行的，按 hunk 分组拆成多块，每块单独审查。
    """
    header = _pr_header(pr)
    small_files = []
    big_chunks: list[tuple[str, str]] = []

    for f in pr.files:
        if f.patch and _patch_line_count(f.patch) > MAX_FILE_LINES:
            groups = _group_hunks(_split_patch_into_hunks(f.patch), MAX_FILE_LINES)
            for i, g in enumerate(groups, 1):
                label = f"{f.filename} (片段 {i}/{len(groups)})"
                text = (
                    header
                    + "\n## 变更文件 diff（大文件已按 hunk 分块）\n"
                    + _render_file(f.filename, f.status, f.additions, f.deletions, g)
                )
                big_chunks.append((label, text))
        else:
            small_files.append(f)

    chunks: list[tuple[str, str]] = []
    if small_files:
        body = "\n".join(
            _render_file(f.filename, f.status, f.additions, f.deletions, f.patch)
            for f in small_files
        )
        chunks.append(("主要变更", header + "\n## 变更文件 diff\n" + body))
    chunks.extend(big_chunks)
    return chunks or [("空变更", header)]


def _parse_review(raw: str) -> _ParsedReview:
    """从 LLM 返回文本中稳健地解析出 JSON 审查结果。"""
    text = raw.strip()
    # 去掉可能的 ```json ... ``` 代码块围栏
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    # 截取最外层 JSON 对象
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        text = text[start : end + 1]

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # 解析失败时降级：把原文塞进 summary，不抛错中断
        return _ParsedReview(summary=raw.strip()[:2000], risks=[], overall_score=0)

    risks: list[Risk] = []
    for item in data.get("risks") or []:
        try:
            risks.append(Risk.model_validate(item))
        except ValidationError:
            continue

    try:
        score = int(round(float(data.get("overall_score", 0))))
    except (TypeError, ValueError):
        score = 0

    return _ParsedReview(
        summary=str(data.get("summary", "")).strip(),
        risks=risks,
        overall_score=max(0, min(100, score)),
    )


class PRReviewer:
    """使用 LLM 审查 PR diff，输出结构化结果。"""

    def __init__(self, client: Optional[BaseLLMClient] = None) -> None:
        # 默认按 .env 的 MODEL_PROVIDER 选择客户端；也可注入自定义实现（便于测试）
        self._client = client or get_llm_client()

    def review(self, pr: PullRequestDiff, max_tokens: int = 4000) -> ReviewResult:
        """对一个 PR diff 执行审查。大文件会自动分块审查并合并结果。"""
        chunks = _build_chunks(pr)
        parsed = [self._review_chunk(text, max_tokens) for _, text in chunks]
        multi = len(parsed) > 1

        all_risks: list[Risk] = []
        summaries: list[str] = []
        scores: list[int] = []
        for (label, _), p in zip(chunks, parsed):
            all_risks.extend(p.risks)
            summaries.append(f"【{label}】{p.summary}" if multi else p.summary)
            scores.append(p.overall_score)

        # 按 severity 由高到低排序
        all_risks.sort(key=lambda r: _SEVERITY_ORDER.get(r.severity, 99))

        return ReviewResult(
            repo=pr.repo,
            pr_number=pr.pr_number,
            summary="\n".join(s for s in summaries if s),
            risks=all_risks,
            overall_score=min(scores) if scores else 0,  # 最差分块主导总分
            provider=self._client.provider,
            model=self._client.model,
        )

    def _review_chunk(self, diff_text: str, max_tokens: int) -> _ParsedReview:
        messages = [
            {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
            {"role": "user", "content": diff_text},
        ]
        raw = self._client.chat(messages, json_mode=True, max_tokens=max_tokens)
        return _parse_review(raw)
