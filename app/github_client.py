"""GitHub 交互层：拉取 PR diff、发布审查评论。"""

from __future__ import annotations

import re

from github import Github
from github.Auth import Token

from .models import FileDiff, PullRequestDiff

# 匹配形如 https://github.com/owner/repo/pull/123 的 PR 链接，
# 容忍结尾的 /files、/commits、#discussion_xxx、? 查询串等。
_PR_URL_RE = re.compile(
    r"github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/pull/(?P<number>\d+)"
)


def parse_pr_url(url: str) -> tuple[str, int]:
    """从 PR URL 解析出 (repo_full_name, pr_number)。

    >>> parse_pr_url("https://github.com/octocat/Hello-World/pull/42")
    ('octocat/Hello-World', 42)
    """
    match = _PR_URL_RE.search(url.strip())
    if not match:
        raise ValueError(
            f"无法解析 PR URL: {url!r}，应形如 "
            "https://github.com/owner/repo/pull/123"
        )
    return f"{match['owner']}/{match['repo']}", int(match["number"])


class GitHubClient:
    """封装 PyGithub，提供拉取 diff 与回写评论的能力。"""

    def __init__(self, token: str) -> None:
        self._gh = Github(auth=Token(token))

    def fetch_pr_diff_from_url(self, url: str) -> PullRequestDiff:
        """从 PR URL 拉取该 PR 的元信息与全部文件 diff。"""
        repo, pr_number = parse_pr_url(url)
        return self.fetch_pr_diff(repo, pr_number)

    def fetch_pr_diff(self, repo: str, pr_number: int) -> PullRequestDiff:
        """拉取指定 PR 的元信息与全部文件 diff。"""
        repository = self._gh.get_repo(repo)
        pr = repository.get_pull(pr_number)

        files = [
            FileDiff(
                filename=f.filename,
                status=f.status,
                additions=f.additions,
                deletions=f.deletions,
                patch=getattr(f, "patch", None),
            )
            for f in pr.get_files()
        ]

        return PullRequestDiff(
            repo=repo,
            pr_number=pr_number,
            title=pr.title,
            description=pr.body or "",
            author=pr.user.login if pr.user else "",
            base_ref=pr.base.ref,
            head_ref=pr.head.ref,
            files=files,
        )

    def post_review_comment(self, repo: str, pr_number: int, body: str) -> str:
        """将审查结果作为 issue 评论发布到 PR，返回评论链接。"""
        repository = self._gh.get_repo(repo)
        pr = repository.get_pull(pr_number)
        comment = pr.create_issue_comment(body)
        return comment.html_url
