"""端到端验证：拉取 PR diff + 调用 LLM 审查。

用法:
    # 需在 .env 或环境变量配置 GITHUB_TOKEN 以及对应厂商的 API Key
    #   MODEL_PROVIDER=deepseek -> DEEPSEEK_API_KEY
    #   MODEL_PROVIDER=claude   -> ANTHROPIC_API_KEY
    python scripts/review.py
    python scripts/review.py https://github.com/owner/repo/pull/123
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# 让脚本在项目根目录外也能 import app
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.github_client import GitHubClient  # noqa: E402
from app.reviewer import PRReviewer  # noqa: E402

DEFAULT_PR_URL = "https://github.com/PyGithub/PyGithub/pull/2787"


def main() -> None:
    load_dotenv()

    github_token = os.getenv("GITHUB_TOKEN")
    if not github_token:
        sys.exit("缺少 GITHUB_TOKEN，请在 .env 或环境变量中配置后重试")

    provider = os.getenv("MODEL_PROVIDER", "deepseek").strip().lower()
    key_var = "ANTHROPIC_API_KEY" if provider in ("claude", "anthropic") else "DEEPSEEK_API_KEY"
    if not os.getenv(key_var):
        sys.exit(f"缺少 {key_var}（当前 MODEL_PROVIDER={provider}），请配置后重试")

    url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PR_URL
    print(f"拉取并审查 PR: {url}\n")

    pr = GitHubClient(github_token).fetch_pr_diff_from_url(url)
    print(f"已拉取: {pr.title}（{len(pr.files)} 个文件），调用 LLM 审查中...\n")

    result = PRReviewer().review(pr)

    print("=" * 60)
    print(f"厂商/模型 : {result.provider} / {result.model}")
    print(f"总体评分 : {result.overall_score}/100")
    print(f"风险点数 : {len(result.risks)}")
    print("=" * 60)

    # 1) 结构化 JSON 输出（验证 schema）
    print("\n----- 结构化结果 (JSON) -----")
    print(json.dumps(result.model_dump(), ensure_ascii=False, indent=2))

    # 2) Markdown 报告（即发到 PR 评论里的样子）
    print("\n----- Markdown 报告 -----")
    print(result.to_markdown())


if __name__ == "__main__":
    main()
