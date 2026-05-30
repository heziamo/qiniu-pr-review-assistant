"""手动验证 GitHubClient.fetch_pr_diff_from_url。

用法:
    # 需先在 .env 或环境变量中配置 GITHUB_TOKEN
    python scripts/test_fetch.py
    python scripts/test_fetch.py https://github.com/owner/repo/pull/123
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# 让脚本在项目根目录外也能 import app
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.github_client import GitHubClient  # noqa: E402

# 默认用一个公开 PR 做冒烟测试（PyGithub 仓库的某个已合并 PR）
DEFAULT_PR_URL = "https://github.com/PyGithub/PyGithub/pull/2900"


def main() -> None:
    load_dotenv()
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        sys.exit("缺少 GITHUB_TOKEN，请在 .env 或环境变量中配置后重试")

    url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PR_URL
    print(f"拉取 PR: {url}\n")

    client = GitHubClient(token)
    pr = client.fetch_pr_diff_from_url(url)

    print("=" * 60)
    print(f"标题   : {pr.title}")
    print(f"仓库   : {pr.repo}  #{pr.pr_number}")
    print(f"作者   : {pr.author}")
    print(f"分支   : {pr.base_ref} <- {pr.head_ref}")
    print(f"变更数 : {len(pr.files)} 个文件")
    print("-" * 60)
    desc = pr.description or "（无描述）"
    print("描述   :")
    print(desc[:500] + ("..." if len(desc) > 500 else ""))
    print("=" * 60)

    for f in pr.files:
        print(f"\n### {f.filename}  [{f.status}]  +{f.additions}/-{f.deletions}")
        if f.patch:
            # 只打印前 30 行，避免刷屏
            lines = f.patch.splitlines()
            preview = "\n".join(lines[:30])
            print(preview)
            if len(lines) > 30:
                print(f"... （省略 {len(lines) - 30} 行）")
        else:
            print("（无 diff 文本：二进制文件或过大被省略）")


if __name__ == "__main__":
    main()
