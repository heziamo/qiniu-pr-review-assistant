"""FastAPI 入口：提供 PR 审查 HTTP 接口与可视化前端。"""

from __future__ import annotations

import logging
import os
import threading
import time
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from .github_client import GitHubClient, parse_pr_url
from .models import ReviewRequest, ReviewResult, ReviewUrlRequest, Settings
from .reviewer import PRReviewer

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("pr_review")

app = FastAPI(
    title="AI PR Review 助手",
    description="七牛云 × XEngineer 暑期实训营 题目三：GitHub PR 自动审查（DeepSeek / Claude）",
    version="0.1.0",
)

# 前端模板路径
_INDEX_HTML = Path(__file__).resolve().parent / "templates" / "index.html"

# 大 PR 保护阈值（行数是主要保护，文件数为辅）
MAX_FILES = 80
MAX_CHANGED_LINES = 20000

# 内存监控指标（简单版，进程重启即清零）
_metrics_lock = threading.Lock()
_metrics: dict = {"total_reviews": 0, "total_elapsed": 0.0, "provider_counts": {}}


def _record_metrics(provider: str, elapsed: float) -> None:
    with _metrics_lock:
        _metrics["total_reviews"] += 1
        _metrics["total_elapsed"] += elapsed
        counts = _metrics["provider_counts"]
        counts[provider] = counts.get(provider, 0) + 1


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

    # 大 PR 保护：文件过多或变更行数过大时拒绝，避免超时与高成本
    total_lines = sum(f.additions + f.deletions for f in pr_diff.files)
    if len(pr_diff.files) > MAX_FILES or total_lines > MAX_CHANGED_LINES:
        raise HTTPException(
            status_code=422,
            detail=(
                f"PR 过大（{len(pr_diff.files)} 个文件 / {total_lines} 行变更，"
                f"上限 {MAX_FILES} 文件 / {MAX_CHANGED_LINES} 行），请拆分后审查"
            ),
        )

    start = time.perf_counter()
    try:
        result = reviewer.review(pr_diff)
    except Exception as exc:  # noqa: BLE001 —— 模型调用失败统一转成 502
        logger.exception("模型调用失败 repo=%s pr=%s", repo, pr_number)
        raise HTTPException(status_code=502, detail=f"模型调用失败: {exc}") from exc
    elapsed = time.perf_counter() - start

    _record_metrics(result.provider, elapsed)
    logger.info(
        "审查完成 repo=%s pr=#%s 耗时=%.1fs 模型=%s/%s tokens=%d+%d 风险=%d 评分=%d",
        repo, pr_number, elapsed, result.provider, result.model,
        result.input_tokens, result.output_tokens, len(result.risks),
        result.overall_score,
    )

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


@app.get("/config")
def config() -> dict[str, str]:
    """供前端展示当前使用的 LLM 厂商（不含任何密钥）。"""
    return {"provider": os.getenv("MODEL_PROVIDER", "deepseek")}


@app.get("/metrics")
def metrics() -> dict:
    """简单的内存监控指标：累计审查次数、平均耗时、各厂商调用次数。"""
    with _metrics_lock:
        n = _metrics["total_reviews"]
        avg = _metrics["total_elapsed"] / n if n else 0.0
        return {
            "total_reviews": n,
            "avg_elapsed_seconds": round(avg, 2),
            "provider_counts": dict(_metrics["provider_counts"]),
        }


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
