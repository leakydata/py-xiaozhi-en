import sqlite3

from src.memory.backup import KEEP, backup_databases


def make(path):
    c = sqlite3.connect(path)
    c.execute("create table t(x)")
    c.execute("insert into t values (1)")
    c.commit()
    c.close()


def test_a_consistent_copy_is_made_once_a_day(tmp_path):
    make(tmp_path / "memory.db")
    first = backup_databases(tmp_path)
    assert [p.parent.name for p in first] == ["backups"]
    assert sqlite3.connect(first[0]).execute("select x from t").fetchone() == (1,)
    assert backup_databases(tmp_path) == []  # already done today


def test_only_the_last_week_is_kept(tmp_path):
    make(tmp_path / "memory.db")
    folder = tmp_path / "backups"
    folder.mkdir()
    for d in range(1, 12):
        (folder / f"memory-2020-01-{d:02d}.db").write_text("x")
    backup_databases(tmp_path)
    assert len(list(folder.glob("memory-*.db"))) == KEEP


def test_a_missing_database_is_skipped(tmp_path):
    assert backup_databases(tmp_path) == []
