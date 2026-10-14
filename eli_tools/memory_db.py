#!/usr/bin/env python3
"""
eli_tools.memory_db

Single source of truth for persistent memory (SQLite).

Your DB already has these tables:
- entries (primary)
- entries_fts (fts5 for search)
- summaries
- habits

This module provides:
- add_entry / recent / search / stats
- optional FTS search if entries_fts exists
- safe JSON fields (tags_json/meta_json) when present

It also remains compatible with an old "memory" table if present, but
entries is the preferred backend.

Design rule: memory DB should *never* crash the assistant. Fail soft.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
import sqlite3
import json
import time

def _now() -> float:
    return time.time()

def _j(x: Any, default: str) -> str:
    try:
        return json.dumps(x, ensure_ascii=False)
    except Exception:
        return default

def _loads(s: str, default: Any) -> Any:
    try:
        return json.loads(s) if s else default
    except Exception:
        return default

class MemoryDB:
    def __init__(self, db_path: str | Path):
        self.path = Path(db_path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(str(self.path))
        con.row_factory = sqlite3.Row
        return con

    def _table_exists(self, con: sqlite3.Connection, name: str) -> bool:
        r = con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
        return bool(r)

    def _init_db(self) -> None:
        # Create minimal "entries" if missing (do not destroy existing schema).
        with self._connect() as con:
            if not self._table_exists(con, "entries"):
                con.execute("""
                CREATE TABLE IF NOT EXISTS entries (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  ts REAL NOT NULL,
                  kind TEXT NOT NULL,
                  content TEXT NOT NULL,
                  tags TEXT NOT NULL DEFAULT '[]',
                  meta TEXT NOT NULL DEFAULT '{}',
                  role TEXT NOT NULL DEFAULT '',
                  session_id TEXT NOT NULL DEFAULT '',
                  convo_id TEXT NOT NULL DEFAULT '',
                  tags_json TEXT NOT NULL DEFAULT '[]',
                  meta_json TEXT NOT NULL DEFAULT '{}',
                  timestamp REAL
                );
                """)
                con.execute("CREATE INDEX IF NOT EXISTS idx_entries_ts ON entries(ts DESC);")
                con.execute("CREATE INDEX IF NOT EXISTS idx_entries_kind ON entries(kind);")
                con.execute("CREATE INDEX IF NOT EXISTS idx_entries_role ON entries(role);")
            # "memory" legacy table support (optional)
            if not self._table_exists(con, "memory"):
                # create it only if someone explicitly asks for it later; do not add noise
                pass

    def add_entry(self, *, kind: str, content: str, role: str = "user",
                  tags: Optional[Sequence[str]] = None,
                  meta: Optional[Dict[str, Any]] = None,
                  session_id: str = "", convo_id: str = "") -> int:
        tags = list(tags or [])
        meta = dict(meta or {})
        ts = _now()
        with self._connect() as con:
            # prefer entries with json fields
            cols = [r["name"] for r in con.execute("PRAGMA table_info(entries)").fetchall()]
            has_tags_json = "tags_json" in cols
            has_meta_json = "meta_json" in cols
            has_timestamp = "timestamp" in cols

            data = {
                "ts": ts,
                "kind": kind,
                "content": content,
                "tags": _j(tags, "[]"),
                "meta": _j(meta, "{}"),
                "role": role,
                "session_id": session_id,
                "convo_id": convo_id,
            }
            if has_tags_json:
                data["tags_json"] = _j(tags, "[]")
            if has_meta_json:
                data["meta_json"] = _j(meta, "{}")
            if has_timestamp:
                data["timestamp"] = ts

            keys = ", ".join(data.keys())
            qs = ", ".join(["?"] * len(data))
            cur = con.execute(f"INSERT INTO entries ({keys}) VALUES ({qs})", tuple(data.values()))
            return int(cur.lastrowid)

    def recent(self, limit: int = 20, *, kind: Optional[str] = None) -> List[Dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        with self._connect() as con:
            if kind:
                rows = con.execute("SELECT * FROM entries WHERE kind=? ORDER BY ts DESC LIMIT ?", (kind, limit)).fetchall()
            else:
                rows = con.execute("SELECT * FROM entries ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def search(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        """
        Full-text if entries_fts exists, else fallback to LIKE.
        """
        limit = max(1, min(int(limit), 200))
        q = (query or "").strip()
        if not q:
            return []
        with self._connect() as con:
            if self._table_exists(con, "entries_fts"):
                # FTS5 match
                rows = con.execute("""
                    SELECT e.*
                    FROM entries_fts f
                    JOIN entries e ON e.id = f.rowid
                    WHERE entries_fts MATCH ?
                    ORDER BY e.ts DESC
                    LIMIT ?
                """, (q, limit)).fetchall()
                return [dict(r) for r in rows]
            # fallback
            like = f"%{q}%"
            rows = con.execute("""
                SELECT * FROM entries
                WHERE content LIKE ? OR kind LIKE ? OR tags LIKE ?
                ORDER BY ts DESC
                LIMIT ?
            """, (like, like, like, limit)).fetchall()
            return [dict(r) for r in rows]

    def stats(self) -> Dict[str, Any]:
        with self._connect() as con:
            r1 = con.execute("SELECT COUNT(*) AS n FROM entries").fetchone()
            r2 = con.execute("SELECT kind, COUNT(*) AS n FROM entries GROUP BY kind ORDER BY n DESC LIMIT 30").fetchall()
            newest = con.execute("SELECT ts FROM entries ORDER BY ts DESC LIMIT 1").fetchone()
        return {
            "path": str(self.path),
            "entries": int(r1["n"]) if r1 else 0,
            "kinds_top": [{"kind": r["kind"], "n": int(r["n"])} for r in r2],
            "newest_ts": float(newest["ts"]) if newest else None,
        }

# Convenience singleton used in some legacy code paths
_default_db: Optional[MemoryDB] = None

def get_default(db_path: str | Path) -> MemoryDB:
    global _default_db
    if _default_db is None or str(_default_db.path) != str(Path(db_path).expanduser().resolve()):
        _default_db = MemoryDB(db_path)
    return _default_db
