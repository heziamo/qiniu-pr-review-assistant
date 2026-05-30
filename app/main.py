"""FastAPI 入口：提供 PR 审查 HTTP 接口与可视化前端。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from .github_client import GitHubClient, parse_pr_url
from .models import ReviewRequest, ReviewResult, ReviewUrlRequest, Settings
from .reviewer import PRReviewer

app = FastAPI(
    title="AI PR Review 助手",
    description="七牛云 × XEngineer 暑期实训营 题目三：GitHub PR 自动审查（DeepSeek / Claude）",
    version="0.1.0",
)

# 前端模板路径
_INDEX_HTML = Path(__file__).resolve().parent / "templates" / "index.html"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


def get_github(settings: Settings = Depends(get_settings)) -> GitHubClient:
    return GitHubClient(settings.github_token)


def get_reviewer() -> PRReviewer:
    # LLM 客户端由 get_llm_client() 按 MODEL_PROVIDER 自行选择（DeepSeek / Claude）
    return PRReviewer()


def _run_review(
    github: GitHubClient,
    reviewer: PRReviewer,
    repo: str,
    pr_number: int,
    post_comment: bool,
) -> ReviewResult:
    """拉取 diff -> 审查 ->（可选）发评论，供 /review 与 /review/url 复用。"""
    try:
        pr_diff = github.fetch_pr_diff(repo, pr_number)
    except Exception as exc:  # noqa: BLE001 —— 统一转成 HTTP 错误
        raise HTTPException(status_code=502, detail=f"拉取 PR 失败: {exc}") from exc

    if not pr_diff.files:
        raise HTTPException(status_code=422, detail="该 PR 没有可审查的文件变更")

    result = reviewer.review(pr_diff)

    if post_comment:
        try:
            result.comment_url = github.post_review_comment(
                repo, pr_number, result.to_markdown()
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"发布评论失败: {exc}") from exc

    return result


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    """返回可视化前端页面。"""
    return HTMLResponse(_INDEX_HTML.read_text(encoding="utf-8"))


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/review", response_model=ReviewResult)
def review_pr(
    req: ReviewRequest,
    github: GitHubClient = Depends(get_github),
    reviewer: PRReviewer = Depends(get_reviewer),
) -> ReviewResult:
    """按 repo + pr_number 审查 PR。"""
    return _run_review(github, reviewer, req.repo, req.pr_number, req.post_comment)


@app.post("/review/url", response_model=ReviewResult)
def review_pr_by_url(
    req: ReviewUrlRequest,
    github: GitHubClient = Depends(get_github),
    reviewer: PRReviewer = Depends(get_reviewer),
) -> ReviewResult:
    """按 PR URL 审查（供前端使用，内部解析出 repo + pr_number）。"""
    try:
        repo, pr_number = parse_pr_url(req.pr_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _run_review(github, reviewer, repo, pr_number, req.post_comment)
