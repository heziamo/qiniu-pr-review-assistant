"""GitHub 交互层：拉取 PR diff、发布审查评论。"""

from __future__ import annotations

from github import Github
from github.Auth import Token

from .models import FileDiff, PullRequestDiff


class GitHubClient:
    """封装 PyGithub，提供拉取 diff 与回写评论的能力。"""

    def __init__(self, token: str) -> None:
        self._gh = Github(auth=Token(token))

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
