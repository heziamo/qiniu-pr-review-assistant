"""Pydantic 数据模型与应用配置。"""

from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel, Field, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 风险分级（由高到低）与问题类型，供 prompt 与校验共用
SEVERITY_LEVELS = ("critical", "high", "medium", "low")
ISSUE_TYPES = ("bug", "security", "performance", "style", "maintainability")

_SEVERITY_ORDER = {s: i for i, s in enumerate(SEVERITY_LEVELS)}
_SEVERITY_EMOJI = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}


class Settings(BaseSettings):
    """从环境变量 / .env 加载配置。

    LLM 相关的密钥（DEEPSEEK_API_KEY / ANTHROPIC_API_KEY / MODEL_PROVIDER）
    由 app.llm_client.get_llm_client() 直接读取环境变量，不在此重复声明，
    这样 LLM 配置与 GitHub 配置解耦。
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    github_token: str = Field(..., alias="GITHUB_TOKEN")


class ReviewRequest(BaseModel):
    """审查请求：指定要审查的 GitHub PR。"""

    repo: str = Field(..., description="仓库全名，如 owner/repo", examples=["octocat/Hello-World"])
    pr_number: int = Field(..., ge=1, description="PR 编号", examples=[42])
    post_comment: bool = Field(
        False, description="是否将审查结果作为评论发布回 PR"
    )


class ReviewUrlRequest(BaseModel):
    """Web 前端用：直接提交 PR URL（内部解析出 repo + pr_number）。"""

    pr_url: str = Field(
        ...,
        description="完整 PR URL",
        examples=["https://github.com/owner/repo/pull/123"],
    )
    post_comment: bool = Field(False, description="是否将审查结果作为评论发布回 PR")


class FileDiff(BaseModel):
    """单个文件的 diff。"""

    filename: str
    status: str = Field(description="added / modified / removed / renamed")
    additions: int = 0
    deletions: int = 0
    patch: Optional[str] = Field(None, description="unified diff 文本，二进制文件为空")


class PullRequestDiff(BaseModel):
    """一个 PR 的元信息与全部文件 diff。"""

    repo: str
    pr_number: int
    title: str
    description: str = ""
    author: str = ""
    base_ref: str = ""
    head_ref: str = ""
    files: list[FileDiff] = Field(default_factory=list)


class Risk(BaseModel):
    """单条审查发现的风险点。"""

    file: str = Field("", description="问题所在文件路径")
    line: Optional[int] = Field(None, description="起始行号；无法定位为 null")
    severity: str = Field("low", description=" / ".join(SEVERITY_LEVELS))
    type: str = Field("maintainability", description=" / ".join(ISSUE_TYPES))
    description: str = Field("", description="问题描述")
    suggestion: str = Field("", description="可执行的修改建议")

    @field_validator("line", mode="before")
    @classmethod
    def _coerce_line(cls, v: object) -> Optional[int]:
        if v is None or v == "":
            return None
        if isinstance(v, bool):  # 避免 True/False 被当成 1/0
            return None
        if isinstance(v, int):
            return v
        # 字符串如 "52" / "52-56" / "L52" -> 取第一个整数
        m = re.search(r"\d+", str(v))
        return int(m.group()) if m else None

    @field_validator("severity", mode="before")
    @classmethod
    def _norm_severity(cls, v: object) -> str:
        s = str(v).strip().lower()
        return s if s in SEVERITY_LEVELS else "low"

    @field_validator("type", mode="before")
    @classmethod
    def _norm_type(cls, v: object) -> str:
        t = str(v).strip().lower()
        return t if t in ISSUE_TYPES else "maintainability"


class ReviewResult(BaseModel):
    """LLM 审查结果（结构化）。"""

    repo: str
    pr_number: int
    summary: str = Field("", description="总体评价")
    risks: list[Risk] = Field(default_factory=list, description="风险点列表，按严重程度排序")
    overall_score: int = Field(0, description="代码质量总分 0-100，越高越好")
    provider: str = Field("", description="使用的 LLM 厂商，如 deepseek / claude")
    model: str = Field("", description="使用的模型名")
    input_tokens: int = Field(0, description="本次审查累计输入 token")
    output_tokens: int = Field(0, description="本次审查累计输出 token")
    comment_url: Optional[str] = Field(None, description="若发布了评论，则为评论链接")

    @field_validator("overall_score", mode="before")
    @classmethod
    def _clamp_score(cls, v: object) -> int:
        try:
            n = int(round(float(v)))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 0
        return max(0, min(100, n))

    @computed_field  # type: ignore[prop-decorator]
    @property
    def markdown(self) -> str:
        """Markdown 报告，随响应一并返回，供前端「复制报告」使用。"""
        return self.to_markdown()

    def to_markdown(self) -> str:
        """渲染成适合发到 PR 评论的 Markdown 报告。"""
        lines = [
            "## 🤖 AI 代码审查报告",
            "",
            f"**总体评分**: {self.overall_score}/100　**模型**: {self.provider}/{self.model}",
            "",
            self.summary or "（无总体评价）",
            "",
        ]
        if not self.risks:
            lines.append("✅ 未发现明显问题。")
            return "\n".join(lines)

        lines.append(f"### 风险点（{len(self.risks)}）")
        for r in self.risks:
            emoji = _SEVERITY_EMOJI.get(r.severity, "⚪️")
            loc = f"`{r.file}`" + (f":{r.line}" if r.line is not None else "")
            lines.append(f"- {emoji} **{r.severity}** [{r.type}] {loc}")
            lines.append(f"  - {r.description}")
            if r.suggestion:
                lines.append(f"  - 建议：{r.suggestion}")
        return "\n".join(lines)
