"""Local memory store: SQLite + sqlite-vec.

One file under the user data dir holds notes, reminders and facts with their
embeddings, so recall is semantic ("what did I say about the truck?") rather
than keyword matching. Everything stays on the machine.

sqlite-vec keeps vectors in a vec0 virtual table joined to `notes` by id. The
extension must be loaded per connection, which is why _connect() exists.
"""

from __future__ import annotations

import json
import sqlite3
import struct
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from src.logging import get_logger
from src.memory.embedder import DIM, get_embedder
from src.utils.resource_finder import get_user_data_dir

logger = get_logger()

KINDS = ("note", "reminder", "fact", "event")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS notes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT NOT NULL DEFAULT 'note',
    text        TEXT NOT NULL,
    speaker     TEXT,
    created_at  TEXT NOT NULL,
    due_at      TEXT,
    done        INTEGER NOT NULL DEFAULT 0,
    tags        TEXT,
    source      TEXT,
    meta        TEXT
);
CREATE INDEX IF NOT EXISTS idx_notes_due  ON notes(due_at);
CREATE INDEX IF NOT EXISTS idx_notes_kind ON notes(kind);
CREATE INDEX IF NOT EXISTS idx_notes_done ON notes(done);

CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
    text, content='notes', content_rowid='id', tokenize='porter unicode61'
);
CREATE TRIGGER IF NOT EXISTS notes_ai AFTER INSERT ON notes BEGIN
    INSERT INTO notes_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS notes_ad AFTER DELETE ON notes BEGIN
    INSERT INTO notes_fts(notes_fts, rowid, text) VALUES('delete', old.id, old.text);
END;
CREATE TRIGGER IF NOT EXISTS notes_au AFTER UPDATE OF text ON notes BEGIN
    INSERT INTO notes_fts(notes_fts, rowid, text) VALUES('delete', old.id, old.text);
    INSERT INTO notes_fts(rowid, text) VALUES (new.id, new.text);
END;
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _pack(vec) -> bytes:
    return struct.pack(f"{len(vec)}f", *[float(x) for x in vec])


class MemoryStore:
    """Notes + reminders + semantic recall, backed by SQLite."""

    _instance: Optional["MemoryStore"] = None
    _singleton_lock = threading.Lock()

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.path = Path(db_path) if db_path else get_user_data_dir() / "memory.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._vec_ok = False
        self._init_db()

    @classmethod
    def instance(cls) -> "MemoryStore":
        with cls._singleton_lock:
            if cls._instance is None:
                cls._instance = MemoryStore()
            return cls._instance

    # ---------- connection ----------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path))
        conn.row_factory = sqlite3.Row
        try:
            conn.enable_load_extension(True)
            import sqlite_vec

            sqlite_vec.load(conn)
            conn.enable_load_extension(False)
            self._vec_ok = True
        except Exception as e:
            # Plain SQLite still works; recall falls back to LIKE matching.
            if self._vec_ok:
                logger.warning(f"sqlite-vec unavailable on this connection: {e}")
            self._vec_ok = False
        return conn

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(_SCHEMA)
            if self._vec_ok:
                conn.execute(
                    f"CREATE VIRTUAL TABLE IF NOT EXISTS notes_vec USING vec0("
                    f"note_id INTEGER PRIMARY KEY, embedding FLOAT[{DIM}])"
                )
            conn.commit()
        logger.info(
            f"MemoryStore ready at {self.path} (vector search: "
            f"{'on' if self._vec_ok else 'off - LIKE fallback'})"
        )

    @property
    def vector_search_enabled(self) -> bool:
        return self._vec_ok

    # ---------- writes ----------

    def add(
        self,
        text: str,
        *,
        kind: str = "note",
        due_at: Optional[str] = None,
        speaker: Optional[str] = None,
        tags: Optional[str] = None,
        source: str = "voice",
        meta: Optional[dict] = None,
    ) -> int:
        text = (text or "").strip()
        if not text:
            raise ValueError("empty text")
        if kind not in KINDS:
            kind = "note"

        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO notes(kind,text,speaker,created_at,due_at,done,tags,"
                "source,meta) VALUES (?,?,?,?,?,0,?,?,?)",
                (
                    kind, text, speaker, _now(), due_at, tags, source,
                    json.dumps(meta, ensure_ascii=False) if meta else None,
                ),
            )
            note_id = int(cur.lastrowid)
            if self._vec_ok:
                try:
                    vec = get_embedder().encode_one(text)
                    conn.execute(
                        "INSERT INTO notes_vec(note_id, embedding) VALUES (?,?)",
                        (note_id, _pack(vec)),
                    )
                except Exception as e:
                    # A note without a vector is still retrievable by listing.
                    logger.warning(f"embedding failed for note {note_id}: {e}")
            conn.commit()
        return note_id

    def complete(self, note_id: int) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute("UPDATE notes SET done=1 WHERE id=?", (note_id,))
            conn.commit()
            return cur.rowcount > 0

    def delete(self, note_id: int) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute("DELETE FROM notes WHERE id=?", (note_id,))
            if self._vec_ok:
                conn.execute("DELETE FROM notes_vec WHERE note_id=?", (note_id,))
            conn.commit()
            return cur.rowcount > 0

    # ---------- reads ----------

    def search(
        self, query: str, k: int = 5, kind: Optional[str] = None,
        min_score: float = 0.45,
    ) -> list[dict[str, Any]]:
        """Hybrid recall: dense vectors fused with FTS5 keyword ranks.

        Dense-only retrieval on short notes suffers from hub vectors - a terse
        entry like "Dentist appointment" sits close to almost any query and
        outranks the genuinely relevant note. Reciprocal rank fusion lets a
        strong keyword hit pull the right row up, and a row both sides agree on
        wins outright.
        """
        query = (query or "").strip()
        if not query:
            return []

        K_RRF = 60.0
        over = max(k * 4, 10)

        with self._lock, self._connect() as conn:
            dense: list[int] = []
            scores: dict[int, float] = {}
            if self._vec_ok:
                try:
                    vec = get_embedder().encode_query(query)
                    for r in conn.execute(
                        "SELECT note_id, distance FROM notes_vec "
                        "WHERE embedding MATCH ? AND k = ? ORDER BY distance",
                        (_pack(vec), over),
                    ).fetchall():
                        nid = int(r["note_id"])
                        dense.append(nid)
                        scores[nid] = round(1.0 - (r["distance"] ** 2) / 2.0, 4)
                except Exception as e:
                    logger.warning(f"vector search failed: {e}")

            keyword: list[int] = []
            try:
                fts_q = " OR ".join(
                    w for w in "".join(
                        c if (c.isalnum() or c.isspace()) else " " for c in query
                    ).split() if len(w) > 2
                )
                if fts_q:
                    keyword = [
                        int(r["rowid"])
                        for r in conn.execute(
                            "SELECT rowid FROM notes_fts WHERE notes_fts MATCH ? "
                            "ORDER BY rank LIMIT ?",
                            (fts_q, over),
                        ).fetchall()
                    ]
            except Exception as e:
                logger.debug(f"fts search skipped: {e}")

            if not dense and not keyword:
                return []

            fused: dict[int, float] = {}
            for rank, nid in enumerate(dense):
                fused[nid] = fused.get(nid, 0.0) + 1.0 / (K_RRF + rank)
            for rank, nid in enumerate(keyword):
                fused[nid] = fused.get(nid, 0.0) + 1.0 / (K_RRF + rank)

            out: list[dict[str, Any]] = []
            for nid, _ in sorted(fused.items(), key=lambda kv: -kv[1]):
                note = conn.execute("SELECT * FROM notes WHERE id=?", (nid,)).fetchone()
                if not note:
                    continue
                if kind and note["kind"] != kind:
                    continue
                d = dict(note)
                d["score"] = scores.get(nid, 0.0)
                # keyword-only hits have no cosine score; keep them, they matched
                # literally. Dense hits must clear the noise floor, which for
                # BGE-small sits around 0.43 on short notes - an unrelated query
                # ("quantum chromodynamics") still scored 0.432 against a compressor
                # note, while genuine matches ran 0.45-0.82.
                if nid in scores and nid not in keyword and d["score"] < min_score:
                    continue
                out.append(d)
                if len(out) >= k:
                    break
            return out

    def due(self, before_iso: Optional[str] = None, limit: int = 20) -> list[dict]:
        """Reminders that are due and not yet done."""
        before = before_iso or _now()
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM notes WHERE done=0 AND due_at IS NOT NULL "
                "AND due_at <= ? ORDER BY due_at LIMIT ?",
                (before, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def upcoming(self, limit: int = 20) -> list[dict]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM notes WHERE done=0 AND due_at IS NOT NULL "
                "AND due_at > ? ORDER BY due_at LIMIT ?",
                (_now(), limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def recent(self, limit: int = 20, kind: Optional[str] = None) -> list[dict]:
        with self._lock, self._connect() as conn:
            if kind:
                rows = conn.execute(
                    "SELECT * FROM notes WHERE kind=? ORDER BY id DESC LIMIT ?",
                    (kind, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM notes ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
            return [dict(r) for r in rows]

    def topics(self, threshold: float = 0.0, min_size: int = 2) -> list[dict]:
        """Group stored notes into themes using the embeddings already on disk.

        Greedy single-pass clustering on cosine similarity rather than k-means:
        the number of themes is not known ahead of time, and a garage assistant
        accumulates a few dozen notes, not thousands.

        The cut-off is derived from the data, not fixed. BGE-small puts related
        notes at roughly 0.54-0.62 and unrelated ones at 0.34-0.50 - too narrow a
        gap for a constant to work across different note sets, so the threshold
        is the 80th percentile of observed similarity. Groupings are therefore
        approximate; the tool description says so rather than implying certainty.
        """
        import numpy as np

        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT n.id, n.kind, n.text, v.embedding FROM notes n "
                "JOIN notes_vec v ON v.note_id = n.id ORDER BY n.id"
            ).fetchall() if self._vec_ok else []
        if not rows:
            return []

        ids = [r["id"] for r in rows]
        texts = {r["id"]: r["text"] for r in rows}
        kinds = {r["id"]: r["kind"] for r in rows}
        vecs = np.stack([
            np.frombuffer(r["embedding"], dtype=np.float32) for r in rows
        ])
        # vectors are already L2-normalised, so a dot product is the cosine
        sim = vecs @ vecs.T

        if threshold <= 0:
            n = len(ids)
            off = sim[~np.eye(n, dtype=bool)] if n > 1 else np.array([0.0])
            threshold = float(np.percentile(off, 80)) if off.size else 1.0
            threshold = max(0.50, min(threshold, 0.80))

        unassigned = set(range(len(ids)))
        clusters: list[list[int]] = []
        while unassigned:
            # start from whichever note is closest to the most others
            seed = max(unassigned, key=lambda i: float(
                sum(sim[i][j] for j in unassigned if j != i)))
            members = [j for j in unassigned if sim[seed][j] >= threshold]
            if seed not in members:
                members.append(seed)
            clusters.append(members)
            unassigned -= set(members)

        out = []
        for members in sorted(clusters, key=len, reverse=True):
            if len(members) < min_size:
                continue
            # the member most similar to the rest is the best label for the group
            rep = max(members, key=lambda i: float(sum(sim[i][j] for j in members)))
            out.append({
                "theme": texts[ids[rep]][:90],
                "size": len(members),
                "notes": [{"id": ids[i], "kind": kinds[ids[i]],
                           "text": texts[ids[i]][:110]} for i in members],
            })
        return out

    def count(self) -> int:
        with self._lock, self._connect() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0])


def get_memory() -> MemoryStore:
    return MemoryStore.instance()
