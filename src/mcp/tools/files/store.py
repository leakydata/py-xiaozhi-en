"""Workspace-scoped filesystem access.

Full read/write/delete/move, but every path is resolved and required to stay
inside one workspace directory. The caller is an LLM driven by speech, so paths
are treated as hostile input: "../../.ssh/id_rsa" and an absolute "/etc/passwd"
both resolve outside the root and are refused.

Containment uses the RESOLVED path (symlinks followed), so a symlink planted
inside the workspace cannot be used to step outside it.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional

from src.logging import get_logger

logger = get_logger()

MAX_READ_BYTES = 200_000
MAX_WRITE_BYTES = 2_000_000


class OutsideWorkspace(Exception):
    """Raised when a path escapes the workspace root."""


def root() -> Path:
    """The one directory the assistant may touch."""
    configured = None
    try:
        from src.utils.config_manager import get_config

        configured = (get_config().get_config("FILES.ROOT", "") or "").strip()
    except Exception:
        pass
    if configured:
        base = Path(configured).expanduser()
    else:
        # Somewhere the user can actually find. A hidden path under
        # ~/.local/share is fine for a database and useless for files a person
        # is meant to open.
        docs = Path.home() / "Documents"
        base = (docs if docs.is_dir() else Path.home()) / "XiaoZhi"
    base.mkdir(parents=True, exist_ok=True)
    return base.resolve()


def resolve(rel: str) -> Path:
    """Resolve a caller-supplied path inside the workspace, or refuse."""
    base = root()
    raw = (rel or "").strip()
    if not raw or raw in (".", "./"):
        return base
    candidate = Path(raw).expanduser()
    # An absolute path is only acceptable if it is already inside the workspace.
    target = candidate if candidate.is_absolute() else base / candidate
    # strict=False: the path may not exist yet (writes, mkdir).
    resolved = target.resolve(strict=False)
    if resolved != base and base not in resolved.parents:
        raise OutsideWorkspace(
            f"{raw!r} is outside the workspace ({base}). "
            "Only paths inside the workspace are allowed."
        )
    return resolved


def rel_to_root(p: Path) -> str:
    try:
        return str(p.relative_to(root())) or "."
    except ValueError:
        return str(p)


def list_dir(rel: str = ".") -> list[dict]:
    target = resolve(rel)
    if not target.exists():
        raise FileNotFoundError(f"{rel_to_root(target)} does not exist")
    if not target.is_dir():
        raise NotADirectoryError(f"{rel_to_root(target)} is not a folder")
    out = []
    for child in sorted(target.iterdir(), key=lambda c: (c.is_file(), c.name.lower())):
        try:
            stat = child.stat()
            out.append(
                {
                    "name": child.name,
                    "path": rel_to_root(child),
                    "type": "folder" if child.is_dir() else "file",
                    "bytes": stat.st_size if child.is_file() else None,
                }
            )
        except OSError:
            continue
    return out


def read_file(rel: str, max_bytes: int = MAX_READ_BYTES) -> dict:
    target = resolve(rel)
    if not target.exists():
        raise FileNotFoundError(f"{rel_to_root(target)} does not exist")
    if target.is_dir():
        raise IsADirectoryError(f"{rel_to_root(target)} is a folder, not a file")
    size = target.stat().st_size
    cap = max(1, min(int(max_bytes), MAX_READ_BYTES))
    with open(target, "rb") as fh:
        raw = fh.read(cap)
    return {
        "path": rel_to_root(target),
        "bytes": size,
        "truncated": size > len(raw),
        "text": raw.decode("utf-8", errors="replace"),
    }


def write_file(rel: str, content: str, append: bool = False) -> dict:
    target = resolve(rel)
    data = (content or "").encode("utf-8")
    if len(data) > MAX_WRITE_BYTES:
        raise ValueError(f"Content is too large ({len(data)} bytes)")
    if target.is_dir():
        raise IsADirectoryError(f"{rel_to_root(target)} is a folder")
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "ab" if append else "wb") as fh:
        fh.write(data)
    logger.info(f"[Files] {'appended to' if append else 'wrote'} {rel_to_root(target)}")
    return {
        "path": rel_to_root(target),
        "bytes": target.stat().st_size,
        "appended": append,
    }


def delete(rel: str) -> dict:
    target = resolve(rel)
    if target == root():
        raise OutsideWorkspace("Refusing to delete the workspace itself")
    if not target.exists():
        raise FileNotFoundError(f"{rel_to_root(target)} does not exist")
    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()
    logger.info(f"[Files] deleted {rel_to_root(target)}")
    return {"deleted": rel_to_root(target)}


def make_dir(rel: str) -> dict:
    target = resolve(rel)
    target.mkdir(parents=True, exist_ok=True)
    return {"created": rel_to_root(target)}


def move(src: str, dst: str) -> dict:
    a, b = resolve(src), resolve(dst)
    if not a.exists():
        raise FileNotFoundError(f"{rel_to_root(a)} does not exist")
    if a == root():
        raise OutsideWorkspace("Refusing to move the workspace itself")
    b.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(a), str(b))
    logger.info(f"[Files] moved {rel_to_root(a)} -> {rel_to_root(b)}")
    return {"from": rel_to_root(a), "to": rel_to_root(b)}


def search(query: str, limit: int = 40) -> list[dict]:
    """Filename substring search across the workspace."""
    q = (query or "").strip().lower()
    if not q:
        return []
    hits = []
    for p in root().rglob("*"):
        if q in p.name.lower():
            try:
                hits.append(
                    {
                        "path": rel_to_root(p),
                        "type": "folder" if p.is_dir() else "file",
                        "bytes": p.stat().st_size if p.is_file() else None,
                    }
                )
            except OSError:
                continue
            if len(hits) >= limit:
                break
    return hits


def grep(pattern: str, limit: int = 40) -> list[dict]:
    """Plain substring search inside text files in the workspace."""
    needle = (pattern or "").strip()
    if not needle:
        return []
    out: list[dict] = []
    for p in root().rglob("*"):
        if not p.is_file():
            continue
        try:
            if p.stat().st_size > MAX_READ_BYTES:
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if needle in line:
                out.append(
                    {"path": rel_to_root(p), "line": i, "text": line.strip()[:200]}
                )
                if len(out) >= limit:
                    return out
    return out
