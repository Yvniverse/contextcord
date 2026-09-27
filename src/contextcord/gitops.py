from __future__ import annotations

import subprocess
from pathlib import Path


class GitError(RuntimeError):
    pass


def git(repo: Path, *args: str, check: bool = True) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and proc.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def repo_root(start: Path | None = None) -> Path:
    start = (start or Path.cwd()).resolve()
    value = git(start, "rev-parse", "--show-toplevel")
    return Path(value).resolve()


def git_dir(repo: Path) -> Path:
    value = git(repo, "rev-parse", "--path-format=absolute", "--git-dir", check=False)
    if value:
        return Path(value).resolve()
    value = git(repo, "rev-parse", "--git-dir")
    p = Path(value)
    return p.resolve() if p.is_absolute() else (repo / p).resolve()


def head(repo: Path) -> str:
    return git(repo, "rev-parse", "HEAD")


def tree(repo: Path, value: str = "HEAD") -> str:
    return git(repo, "rev-parse", f"{value}^{{tree}}")


def branch(repo: Path) -> str:
    return git(repo, "branch", "--show-current") or "DETACHED"


def status_porcelain(repo: Path) -> str:
    return git(repo, "status", "--porcelain=v1", "--untracked-files=all")


def upstream(repo: Path) -> str | None:
    value = git(repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}", check=False)
    return value or None


def upstream_head(repo: Path) -> str | None:
    value = git(repo, "rev-parse", "@{u}", check=False)
    return value or None


def list_material_files(repo: Path) -> list[str]:
    proc = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        raise GitError(proc.stderr.decode("utf-8", errors="replace"))
    return sorted(x.decode("utf-8", errors="surrogateescape").replace("\\", "/") for x in proc.stdout.split(b"\0") if x)


def changed_paths(repo: Path) -> list[str]:
    values: set[str] = set()
    commands = [
        ["diff", "--name-only", "HEAD"],
        ["diff", "--cached", "--name-only", "HEAD"],
        ["ls-files", "--others", "--exclude-standard"],
    ]
    for args in commands:
        proc = subprocess.run(["git", "-C", str(repo), *args, "-z"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.returncode:
            raise GitError(proc.stderr.decode("utf-8", "replace"))
        values.update(x.decode("utf-8", "surrogateescape") for x in proc.stdout.split(b"\0") if x)
    return sorted(values)


def resolve_commit(repo: Path, value: str) -> str:
    return git(repo, "rev-parse", f"{value}^{{commit}}")


def notes_show(repo: Path, ref: str, commit: str) -> str | None:
    raw = git(repo, "notes", f"--ref={ref}", "show", commit, check=False)
    return raw or None


def notes_write(repo: Path, ref: str, commit: str, payload: str) -> None:
    git(repo, "notes", f"--ref={ref}", "add", "-f", "-m", payload, commit)


def notes_compare_and_swap(repo: Path, ref: str, commit: str, payload: str, expected: str) -> bool:
    """Build on a private ref and atomically publish only if the base is current."""
    import uuid
    temporary = 'refs/notes/project-harness-tmp/' + uuid.uuid4().hex
    try:
        if expected:
            git(repo, 'update-ref', temporary, expected)
        notes_write(repo, temporary, commit, payload)
        new = git(repo, 'rev-parse', temporary)
        empty = '0' * (64 if git(repo, 'rev-parse', '--show-object-format') == 'sha256' else 40)
        proc = subprocess.run(['git','-C',str(repo),'update-ref',ref,new,expected or empty],
                              stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        return proc.returncode == 0
    finally:
        git(repo, 'update-ref', '-d', temporary, check=False)
