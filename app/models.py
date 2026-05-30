"""Pydantic 数据模型与应用配置。"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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


class ReviewResult(BaseModel):
    """LLM 审查结果。"""

    repo: str
    pr_number: int
    summary: str = Field(description="审查总览（Markdown）")
    provider: str = Field(description="使用的 LLM 厂商，如 deepseek / claude")
    model: str = Field(description="使用的模型名")
    comment_url: Optional[str] = Field(None, description="若发布了评论，则为评论链接")
