"""Pydantic 数据模型与应用配置。"""

from __future__ import annotations

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """从环境变量 / .env 加载配置。"""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: str = Field(..., alias="ANTHROPIC_API_KEY")
    github_token: str = Field(..., alias="GITHUB_TOKEN")
    anthropic_model: str = Field("claude-opus-4-8", alias="ANTHROPIC_MODEL")


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
    patch: str | None = Field(None, description="unified diff 文本，二进制文件为空")


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
    """Claude 审查结果。"""

    repo: str
    pr_number: int
    summary: str = Field(description="审查总览（Markdown）")
    model: str
    cache_read_tokens: int = Field(
        0, description="本次请求命中缓存的输入 token 数，用于验证 prompt caching 生效"
    )
    cache_creation_tokens: int = Field(0, description="本次请求写入缓存的输入 token 数")
    input_tokens: int = 0
    output_tokens: int = 0
    comment_url: str | None = Field(None, description="若发布了评论，则为评论链接")
