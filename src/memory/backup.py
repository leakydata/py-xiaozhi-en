"""A daily copy of the memory databases, so a bad write or a lost disk is not the end.

remember/recall is the assistant's long-term memory and the conversation log is
the record of everything said; both live in single SQLite files. SQLite's online
backup API takes a consistent copy while the app is writing. One copy a day,
the last seven kept.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from src.logging import get_logger

logger = get_logger()

KEEP = 7


def backup_databases(
    data_dir: Path, names=("memory.db", "conversations.db")
) -> list[Path]:
    """Copy each database once per day into <data_dir>/backups/. Returns new files."""
    made: list[Path] = []
    folder = Path(data_dir) / "backups"
    stamp = datetime.now().strftime("%Y-%m-%d")
    for name in names:
        src = Path(data_dir) / name
        if not src.exists() or src.stat().st_size == 0:
            continue
        stem = src.stem
        dest = folder / f"{stem}-{stamp}.db"
        if dest.exists():
            continue
        try:
            folder.mkdir(parents=True, exist_ok=True)
            with (
                sqlite3.connect(str(src)) as source,
                sqlite3.connect(str(dest)) as target,
            ):
                source.backup(target)
            made.append(dest)
        except Exception as e:
            logger.warning(f"backup of {name} failed: {e}")
            dest.unlink(missing_ok=True)
            continue
        for old in sorted(folder.glob(f"{stem}-*.db"))[:-KEEP]:
            old.unlink(missing_ok=True)
    if made:
        logger.info(f"memory backup: {', '.join(p.name for p in made)}")
    return made
