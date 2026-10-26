import os
import re

from wrench.github_client.service import GitHubService

_SOURCE_EXTENSIONS = {".py", ".js", ".ts", ".go", ".rb", ".java", ".rs", ".cs", ".cpp"}
_TRUNCATION_NOTE = "\n# [truncated]"


class CodeReader:
    def __init__(self, service: GitHubService):
        self.service = service

    def build_context(
        self,
        repo: str,
        path_hint: str,
        ref: str = "main",
        max_files: int = 20,
        max_chars_per_file: int = 8000,
    ) -> str:
        tree = self.service.get_file_tree(ref=ref)

        def score(item: dict) -> int:
            path = item["path"]
            s = 0
            filename = os.path.basename(path)
            dirname = os.path.dirname(path)
            if path_hint and path_hint in filename:
                s += 3
            if path_hint and path_hint in dirname:
                s += 2
            _, ext = os.path.splitext(filename)
            if ext in _SOURCE_EXTENSIONS:
                s += 1
            return s

        ranked = sorted(tree, key=score, reverse=True)[:max_files]

        sections = []
        for item in ranked:
            try:
                file_data = self.service.get_file_content(item["path"], ref=ref)
                content = file_data["content"]
                if len(content) > max_chars_per_file:
                    content = content[:max_chars_per_file] + _TRUNCATION_NOTE
                sections.append(f"=== File: {item['path']} ===\n{content}")
            except Exception:
                pass

        return "\n\n".join(sections)

    def build_pr_context(self, pr_number: int) -> str:
        pr = self.service.get_pr(pr_number)
        files = self.service.get_pr_files(pr_number)
        comments = self.service.get_pr_comments(pr_number)

        parts = [
            f"PR #{pr['number']}: {pr['title']}",
            f"Author: {pr['author']}   {pr['head']} → {pr['base']}",
            f"State: {pr['state']}",
        ]

        # PR description
        parts.append("\n--- PR Description ---")
        parts.append(pr["body"] or "(no description)")

        # Linked issues — parse #N refs from the PR body
        parts += self._linked_issues_section(pr["body"] or "")

        # Changed files: full content for small files, patch-only for large ones
        parts.append("\n--- Changed Files ---")
        for f in files:
            parts.append(
                f"\n=== {f['path']} ({f['status']}, +{f['additions']} -{f['deletions']}) ==="
            )
            full_content = self._try_full_file(f["path"], pr["head"])
            if full_content is not None:
                parts.append("(full file shown — patch follows for reference)")
                parts.append(f["patch"] or "")
                parts.append("--- full file ---")
                parts.append(full_content)
            elif f["patch"]:
                parts.append(f["patch"])

            # Recent commit history for this file on the base branch
            history = self._file_commit_history(f["path"], pr["base"])
            if history:
                parts.append(f"  Recent commits touching {f['path']} (base branch):")
                for h in history:
                    parts.append(f"    {h['date']}  {h['sha']}  {h['author']}: {h['message']}")

        # Existing inline review comments
        if comments:
            parts.append("\n--- Existing Review Comments ---")
            for c in comments:
                location = f"{c['path']}:{c['line']}" if c.get("path") else "general"
                parts.append(f"[{c['author']} on {location}]: {c['body']}")

        return "\n".join(parts)

    # ------------------------------------------------------------------ helpers

    def _try_full_file(self, path: str, ref: str, max_lines: int = 500) -> str | None:
        """Return full file content if it is ≤ max_lines, else None."""
        try:
            data = self.service.get_file_content(path, ref=ref)
            content = data["content"]
            if content.count("\n") <= max_lines:
                return content
        except Exception:
            pass
        return None

    def _file_commit_history(self, path: str, ref: str) -> list[dict]:
        try:
            return self.service.get_file_commits(path, ref=ref, max_commits=5)
        except Exception:
            return []

    def _linked_issues_section(self, body: str) -> list[str]:
        """Extract #N issue references from the PR body and fetch their titles/bodies."""
        nums = {
            int(n)
            for n in re.findall(r"(?:closes?|fixes?|resolves?)\s+#(\d+)", body, re.IGNORECASE)
        }
        # also grab bare #N references that aren't part of a closing keyword
        nums |= {
            int(n)
            for n in re.findall(r"(?<![/\w])#(\d+)(?!\d)", body)
            if int(n) < 100_000  # skip huge numbers that are likely SHAs
        }
        if not nums:
            return []

        parts = ["\n--- Linked Issues ---"]
        for num in sorted(nums):
            try:
                issue = self.service.get_issue(num)
                labels = f"  [{', '.join(issue['labels'])}]" if issue["labels"] else ""
                parts.append(f"Issue #{issue['number']}: {issue['title']}{labels} ({issue['state']})")
                if issue["body"]:
                    # cap at 1000 chars so one issue doesn't swamp the context
                    body_snippet = issue["body"][:1000]
                    if len(issue["body"]) > 1000:
                        body_snippet += "\n[issue body truncated]"
                    parts.append(body_snippet)
            except Exception:
                pass
        return parts
