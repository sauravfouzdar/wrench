import base64

from github import Github, GithubException
from github.InputGitTreeElement import InputGitTreeElement

from wrench.exceptions import GitHubError

_EXCLUDE_PATTERNS = (
    "node_modules",
    "dist/",
    ".min.",
    "__pycache__",
    ".lock",
    "coverage",
    "migrations",
    ".pyc",
)


class GitHubService:
    def __init__(self, owner: str, repo: str, token: str):
        self.owner = owner
        self.repo_name = repo
        self.g = Github(token)
        try:
            self.repo = self.g.get_repo(f"{owner}/{repo}")
        except GithubException as e:
            raise GitHubError(f"Could not access repo {owner}/{repo}: {e}") from e

    def create_branch(self, branch_name: str, base: str = "main") -> dict:
        try:
            # fall back to the repo's default branch if the requested base doesn't exist
            try:
                sha = self.repo.get_branch(base).commit.sha
            except GithubException:
                base = self.repo.default_branch
                sha = self.repo.get_branch(base).commit.sha
            self.repo.create_git_ref(ref=f"refs/heads/{branch_name}", sha=sha)
            return {
                "branch": branch_name,
                "sha": sha,
                "url": f"https://github.com/{self.owner}/{self.repo_name}/tree/{branch_name}",
            }
        except GithubException as e:
            raise GitHubError(f"Failed to create branch {branch_name!r}: {e}") from e

    def get_file_content(self, path: str, ref: str = "main") -> dict:
        try:
            file = self.repo.get_contents(path, ref=ref)
            return {
                "path": file.path,
                "content": file.decoded_content.decode("utf-8"),
                "sha": file.sha,
            }
        except GithubException as e:
            raise GitHubError(f"Failed to read {path!r}: {e}") from e

    def get_file_tree(self, path: str = "", ref: str = "main") -> list[dict]:
        try:
            tree = self.repo.get_git_tree(ref, recursive=True).tree
            results = []
            for item in tree:
                if item.type != "blob":
                    continue
                if any(pat in item.path for pat in _EXCLUDE_PATTERNS):
                    continue
                results.append({"path": item.path, "type": item.type, "size": item.size})
            return results
        except GithubException as e:
            raise GitHubError(f"Failed to get file tree: {e}") from e

    def commit_files(self, branch: str, files: list[dict], message: str) -> dict:
        try:
            ref = self.repo.get_git_ref(f"heads/{branch}")
            head_sha = ref.object.sha
            parent_commit = self.repo.get_git_commit(head_sha)
            base_tree_sha = parent_commit.tree.sha

            tree_elements = []
            for f in files:
                blob = self.repo.create_git_blob(f["content"], "utf-8")
                tree_elements.append(
                    InputGitTreeElement(
                        path=f["path"],
                        mode="100644",
                        type="blob",
                        sha=blob.sha,
                    )
                )

            base_tree = self.repo.get_git_tree(base_tree_sha)
            new_tree = self.repo.create_git_tree(tree_elements, base_tree)
            new_commit = self.repo.create_git_commit(message, new_tree, [parent_commit])
            ref.edit(new_commit.sha)

            return {
                "commit_sha": new_commit.sha,
                "commit_url": new_commit.html_url,
            }
        except GithubException as e:
            raise GitHubError(f"Failed to commit files to {branch!r}: {e}") from e

    def open_pr(self, branch: str, base: str, title: str, body: str) -> dict:
        try:
            pr = self.repo.create_pull(title=title, body=body, head=branch, base=base)
            return {"number": pr.number, "url": pr.html_url, "title": pr.title}
        except GithubException as e:
            raise GitHubError(f"Failed to open PR from {branch!r} → {base!r}: {e}") from e

    def get_pr(self, pr_number: int) -> dict:
        try:
            pr = self.repo.get_pull(pr_number)
            return {
                "number": pr.number,
                "title": pr.title,
                "body": pr.body,
                "state": pr.state,
                "url": pr.html_url,
                "head": pr.head.ref,
                "base": pr.base.ref,
                "author": pr.user.login,
            }
        except GithubException as e:
            raise GitHubError(f"Failed to get PR #{pr_number}: {e}") from e

    def get_pr_files(self, pr_number: int) -> list[dict]:
        try:
            pr = self.repo.get_pull(pr_number)
            return [
                {
                    "path": f.filename,
                    "status": f.status,
                    "additions": f.additions,
                    "deletions": f.deletions,
                    "patch": f.patch or "",
                }
                for f in pr.get_files()
            ]
        except GithubException as e:
            raise GitHubError(f"Failed to get files for PR #{pr_number}: {e}") from e

    def get_pr_comments(self, pr_number: int) -> list[dict]:
        try:
            pr = self.repo.get_pull(pr_number)
            return [
                {
                    "author": c.user.login,
                    "body": c.body,
                    "path": getattr(c, "path", None),
                    "line": getattr(c, "original_line", None),
                }
                for c in pr.get_review_comments()
            ]
        except GithubException as e:
            raise GitHubError(f"Failed to get comments for PR #{pr_number}: {e}") from e

    def create_review(
        self, pr_number: int, body: str, event: str, comments: list[dict]
    ) -> dict:
        try:
            pr = self.repo.get_pull(pr_number)
            review_comments = [
                {
                    "path": c["path"],
                    "line": c.get("line", 1),
                    "body": c["comment"],
                }
                for c in comments
                if c.get("path")
            ]
            review = pr.create_review(body=body, event=event, comments=review_comments)
            return {"id": review.id, "state": review.state}
        except GithubException as e:
            raise GitHubError(f"Failed to create review for PR #{pr_number}: {e}") from e

    def get_file_commits(self, path: str, ref: str = "main", max_commits: int = 5) -> list[dict]:
        try:
            commits = self.repo.get_commits(sha=ref, path=path)
            result = []
            for commit in commits[:max_commits]:
                result.append({
                    "sha": commit.sha[:8],
                    "message": commit.commit.message.split("\n")[0],
                    "author": commit.commit.author.name,
                    "date": commit.commit.author.date.strftime("%Y-%m-%d"),
                })
            return result
        except GithubException as e:
            raise GitHubError(f"Failed to get commits for {path!r}: {e}") from e

    def get_issue(self, issue_number: int) -> dict:
        try:
            issue = self.repo.get_issue(issue_number)
            return {
                "number": issue.number,
                "title": issue.title,
                "body": issue.body or "",
                "state": issue.state,
                "labels": [lb.name for lb in issue.labels],
            }
        except GithubException as e:
            raise GitHubError(f"Failed to get issue #{issue_number}: {e}") from e

    def list_open_prs(self) -> list[dict]:
        try:
            return [
                {
                    "number": pr.number,
                    "title": pr.title,
                    "url": pr.html_url,
                    "author": pr.user.login,
                    "head": pr.head.ref,
                }
                for pr in self.repo.get_pulls(state="open")
            ]
        except GithubException as e:
            raise GitHubError(f"Failed to list open PRs: {e}") from e
