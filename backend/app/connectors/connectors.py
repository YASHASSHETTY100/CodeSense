"""Connector interface + GitHub/GitLab implementations with automatic branch discovery."""
from __future__ import annotations
import json
import os
import re
import shutil
import subprocess
import urllib.parse
import urllib.request
from dataclasses import dataclass


class BranchResolutionError(RuntimeError):
    """Raised when a specified branch cannot be found or remote branch discovery fails."""
    pass


@dataclass
class CloneResult:
    local_path: str
    branch: str


def _authed_url(repo_url: str, credential: str = "", provider: str = "github") -> str:
    if not credential:
        return repo_url
    m = re.match(r"(https?://)(.*)", repo_url.strip())
    if not m:
        return repo_url
    proto, rest = m.group(1), m.group(2)
    if "@" in rest.split("/")[0]:
        return repo_url
    if provider == "gitlab":
        return f"{proto}oauth2:{credential}@{rest}"
    return f"{proto}oauth:{credential}@{rest}"


def _clean_git_error(raw_stderr: str) -> str:
    """Sanitize raw git stderr for human presentation without raw stack traces or token leak."""
    clean = re.sub(r"oauth[2]?:[^\s@]+@", "***@", raw_stderr)
    lines = [line.strip() for line in clean.splitlines() if line.strip()]
    fatal_lines = [l for l in lines if "fatal:" in l or "error:" in l]
    if fatal_lines:
        return " ".join(fatal_lines)
    return " ".join(lines[-3:]) if lines else "Git operation failed."


def detect_provider_default_branch(repo_url: str, credential: str = "", provider: str = "github") -> str | None:
    """Attempt fast discovery of default branch using GitHub/GitLab public or authenticated APIs."""
    try:
        if provider == "github" or "github.com" in repo_url:
            m = re.search(r"github\.com[:/](.+?)/(.+?)(?:\.git)?$", repo_url.strip())
            if m:
                owner, repo = m.group(1), m.group(2)
                api_url = f"https://api.github.com/repos/{owner}/{repo}"
                req = urllib.request.Request(api_url)
                req.add_header("User-Agent", "CodeSense-Assistant")
                req.add_header("Accept", "application/vnd.github.v3+json")
                if credential:
                    req.add_header("Authorization", f"Bearer {credential}")
                with urllib.request.urlopen(req, timeout=5) as resp:
                    if resp.status == 200:
                        data = json.loads(resp.read().decode("utf-8"))
                        if "default_branch" in data and data["default_branch"]:
                            return str(data["default_branch"])
        elif provider == "gitlab" or "gitlab.com" in repo_url:
            m = re.search(r"gitlab\.com[:/](.+?)(?:\.git)?$", repo_url.strip())
            if m:
                path = urllib.parse.quote(m.group(1), safe="")
                api_url = f"https://gitlab.com/api/v4/projects/{path}"
                req = urllib.request.Request(api_url)
                req.add_header("User-Agent", "CodeSense-Assistant")
                if credential:
                    req.add_header("PRIVATE-TOKEN", credential)
                with urllib.request.urlopen(req, timeout=5) as resp:
                    if resp.status == 200:
                        data = json.loads(resp.read().decode("utf-8"))
                        if "default_branch" in data and data["default_branch"]:
                            return str(data["default_branch"])
    except Exception:
        pass
    return None


def detect_git_remote_default_branch(repo_url: str, credential: str = "", provider: str = "github") -> str:
    """Detect default branch using safe git ls-remote commands:
    Priority 1: Provider API (GitHub/GitLab)
    Priority 2: git ls-remote --symref <url> HEAD
    Priority 3: Match HEAD sha with remote branch sha in git ls-remote --heads
    Priority 4: Intelligent fallback to available discovered branches (main/master/etc.)
    """
    # 1. Provider API
    api_branch = detect_provider_default_branch(repo_url, credential, provider)
    if api_branch:
        return api_branch

    authed = _authed_url(repo_url, credential, provider)

    # 2. git ls-remote --symref <authed> HEAD
    try:
        r = subprocess.run(
            ["git", "ls-remote", "--symref", authed, "HEAD"],
            capture_output=True, text=True, timeout=30
        )
        if r.returncode == 0 and r.stdout:
            m = re.search(r"ref:\s+refs/heads/(\S+)\s+HEAD", r.stdout)
            if m:
                return m.group(1).strip()
    except Exception:
        pass

    # 3. Match HEAD sha with heads
    try:
        r_head = subprocess.run(
            ["git", "ls-remote", authed, "HEAD"],
            capture_output=True, text=True, timeout=30
        )
        r_branches = subprocess.run(
            ["git", "ls-remote", "--heads", authed],
            capture_output=True, text=True, timeout=30
        )
        head_sha = ""
        if r_head.returncode == 0 and r_head.stdout.strip():
            head_sha = r_head.stdout.split()[0].strip()

        branches_map = {}
        if r_branches.returncode == 0 and r_branches.stdout:
            for line in r_branches.stdout.splitlines():
                parts = line.strip().split()
                if len(parts) >= 2 and "refs/heads/" in parts[1]:
                    b_sha = parts[0]
                    b_name = parts[1].split("refs/heads/")[-1]
                    branches_map[b_name] = b_sha

        if head_sha:
            for b_name, b_sha in branches_map.items():
                if b_sha == head_sha:
                    return b_name

        # 4. Fallback among available branches
        for candidate in ["main", "master", "trunk", "development", "develop"]:
            if candidate in branches_map:
                return candidate

        if branches_map:
            return next(iter(branches_map.keys()))
    except Exception as e:
        raise BranchResolutionError(f"Failed to inspect remote repository metadata: {e}")

    raise BranchResolutionError(
        "Could not detect the repository's default branch. "
        "Please ensure the repository URL and credentials are valid."
    )


def check_remote_branch_exists(repo_url: str, branch: str, credential: str = "", provider: str = "github") -> bool:
    """Verify whether a specific branch exists on the remote repository."""
    if not branch:
        return False
    authed = _authed_url(repo_url, credential, provider)
    try:
        r = subprocess.run(
            ["git", "ls-remote", "--heads", authed, f"refs/heads/{branch}"],
            capture_output=True, text=True, timeout=30
        )
        if r.returncode == 0 and r.stdout:
            for line in r.stdout.splitlines():
                if f"refs/heads/{branch}" in line:
                    return True
        r2 = subprocess.run(
            ["git", "ls-remote", "--heads", authed, branch],
            capture_output=True, text=True, timeout=30
        )
        if r2.returncode == 0 and r2.stdout:
            for line in r2.stdout.splitlines():
                if f"refs/heads/{branch}" in line:
                    return True
    except Exception:
        return False
    return False


def resolve_repository_branch(
    repo_url: str,
    configured_branch: str = "",
    credential: str = "",
    provider: str = "github"
) -> tuple[str, str]:
    """Resolves (effective_branch, detected_branch) following priority A, B, C, D:
    A. If user explicitly supplied branch -> verify it exists, fail cleanly if not.
    B/C/D. If branch not supplied -> auto-detect default branch via provider/symref/HEADs.
    """
    cfg = (configured_branch or "").strip()
    if cfg:
        exists = check_remote_branch_exists(repo_url, cfg, credential, provider)
        if not exists:
            raise BranchResolutionError(
                f"Repository connection failed because branch '{cfg}' does not exist. "
                f"The repository's default branch could not be used. Please select a valid "
                f"branch or allow CodeSense to detect the default branch automatically."
            )
        try:
            detected = detect_git_remote_default_branch(repo_url, credential, provider)
        except Exception:
            detected = cfg
        return cfg, detected

    detected = detect_git_remote_default_branch(repo_url, credential, provider)
    return detected, detected


import stat


def _safe_rmtree(path: str) -> None:
    if not os.path.exists(path):
        return
    def on_rm_error(func, p, exc_info):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except Exception:
            pass
    shutil.rmtree(path, onerror=on_rm_error)


def _git_clone(url: str, dest: str, branch: str = "") -> str:
    git_dir = os.path.join(dest, ".git")
    if os.path.isdir(git_dir):
        chk = subprocess.run(["git", "-C", dest, "status"], capture_output=True, text=True)
        if chk.returncode == 0:
            if branch:
                subprocess.run(["git", "-C", dest, "checkout", branch], capture_output=True, timeout=60)
            subprocess.run(["git", "-C", dest, "pull", "--ff-only"], check=False,
                           capture_output=True, timeout=120)
            # verify we actually have files checked out
            non_git = [f for f in os.listdir(dest) if f != ".git"]
            if non_git:
                return dest
        # If status failed or repository is empty, remove and clone fresh
        _safe_rmtree(dest)

    if os.path.isdir(dest):
        _safe_rmtree(dest)
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    cmd = ["git", "clone", "--depth", "1"]
    if branch:
        cmd += ["--branch", branch]
    cmd += [url, dest]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        cmd2 = ["git", "clone"] + (["--branch", branch] if branch else []) + [url, dest]
        r2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=600)
        if r2.returncode != 0:
            err_msg = _clean_git_error(r2.stderr or r.stderr)
            raise RuntimeError(f"git clone failed: {err_msg}")
    return dest


class RepoConnector:
    provider: str = "base"

    def parse_repo_url(self, url: str) -> dict:
        raise NotImplementedError

    def clone_or_pull(self, repo_url: str, dest_dir: str, branch: str = "",
                      credential: str = "") -> CloneResult:
        raise NotImplementedError

    def list_branches(self, repo_url: str, credential: str = "") -> list[str]:
        authed = _authed_url(repo_url, credential, self.provider)
        try:
            r = subprocess.run(["git", "ls-remote", "--heads", authed],
                               capture_output=True, text=True, timeout=60)
            out = [l.split("refs/heads/")[-1].strip() for l in r.stdout.splitlines() if "refs/heads/" in l]
            return out or []
        except Exception:
            return []


class GitHubConnector(RepoConnector):
    provider = "github"

    def parse_repo_url(self, url: str) -> dict:
        m = re.search(r"github\.com[:/](.+?)/(.+?)(?:\.git)?$", url.strip())
        if not m:
            raise ValueError("Not a GitHub repo URL")
        return {"owner": m.group(1), "repo": m.group(2)}

    def clone_or_pull(self, repo_url: str, dest_dir: str, branch: str = "", credential: str = "") -> CloneResult:
        authed = _authed_url(repo_url, credential, self.provider)
        effective_branch = branch
        if not effective_branch:
            effective_branch, _ = resolve_repository_branch(repo_url, branch, credential, self.provider)
        _git_clone(authed, dest_dir, effective_branch)
        return CloneResult(dest_dir, effective_branch)


class GitLabConnector(RepoConnector):
    provider = "gitlab"

    def parse_repo_url(self, url: str) -> dict:
        m = re.search(r"gitlab\.com[:/](.+?)(\.git)?$", url.strip())
        if not m:
            raise ValueError("Not a GitLab repo URL")
        return {"path": m.group(1)}

    def clone_or_pull(self, repo_url: str, dest_dir: str, branch: str = "", credential: str = "") -> CloneResult:
        authed = _authed_url(repo_url, credential, self.provider)
        effective_branch = branch
        if not effective_branch:
            effective_branch, _ = resolve_repository_branch(repo_url, branch, credential, self.provider)
        _git_clone(authed, dest_dir, effective_branch)
        return CloneResult(dest_dir, effective_branch)


def get_connector(provider: str) -> RepoConnector:
    if provider == "gitlab":
        return GitLabConnector()
    return GitHubConnector()
