"""FastAPI 入口：提供 PR 审查 HTTP 接口。"""

from __future__ import annotations

from functools import lru_cache

from fastapi import Depends, FastAPI, HTTPException

from .github_client import GitHubClient
from .models import ReviewRequest, ReviewResult, Settings
from .reviewer import PRReviewer

app = FastAPI(
    title="AI PR Review 助手",
    description="七牛云 × XEngineer 暑期实训营 题目三：基于 Claude 的 GitHub PR 自动审查",
    version="0.1.0",
)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


def get_github(settings: Settings = Depends(get_settings)) -> GitHubClient:
    return GitHubClient(settings.github_token)


def get_reviewer() -> PRReviewer:
    # LLM 客户端由 get_llm_client() 按 MODEL_PROVIDER 自行选择（DeepSeek / Claude）
    return PRReviewer()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/review", response_model=ReviewResult)
def review_pr(
    req: ReviewRequest,
    github: GitHubClient = Depends(get_github),
    reviewer: PRReviewer = Depends(get_reviewer),
) -> ReviewResult:
    """拉取指定 PR 的 diff，调用 Claude 审查，可选地把结果发布回 PR。"""
    try:
        pr_diff = github.fetch_pr_diff(req.repo, req.pr_number)
    except Exception as exc:  # noqa: BLE001 —— 统一转成 HTTP 错误
        raise HTTPException(status_code=502, detail=f"拉取 PR 失败: {exc}") from exc

    if not pr_diff.files:
        raise HTTPException(status_code=422, detail="该 PR 没有可审查的文件变更")

    result = reviewer.review(pr_diff)

    if req.post_comment:
        try:
            result.comment_url = github.post_review_comment(
                req.repo, req.pr_number, result.summary
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=502, detail=f"发布评论失败: {exc}"
            ) from exc

    return result
