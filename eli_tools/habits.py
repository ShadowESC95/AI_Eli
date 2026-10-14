"""
eli_tools/habits.py

Simple habit/pattern system:
- You can store regex patterns that map to actions + args.
- Router can consult habits first, then fall back.

Storage: SQLite using the same memory DB file for simplicity.
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional
import re
import json

from eli_tools import memory_db

def _connect():
    memory_db.init_db()
    import sqlite3
    con = sqlite3.connect(memory_db.DEFAULT_DB_PATH, timeout=30.0)
    con.execute("PRAGMA foreign_keys=ON;")
    return con

def init_habits() -> None:
    con = _connect()
    try:
        con.execute("""
          CREATE TABLE IF NOT EXISTS habits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pattern TEXT NOT NULL,
            action TEXT NOT NULL,
            args_json TEXT NOT NULL DEFAULT '{}',
            enabled INTEGER NOT NULL DEFAULT 1
          );
        """)
        con.commit()
    finally:
        con.close()

def add_habit(pattern: str, action: str, args: Optional[Dict[str, Any]] = None, enabled: bool = True) -> Dict[str, Any]:
    init_habits()
    con = _connect()
    try:
        con.execute(
            "INSERT INTO habits(pattern,action,args_json,enabled) VALUES (?,?,?,?)",
            (pattern, action, json.dumps(args or {}), 1 if enabled else 0),
        )
        con.commit()
        return {"ok": True}
    finally:
        con.close()

def list_habits(limit: int = 50) -> List[Dict[str, Any]]:
    init_habits()
    con = _connect()
    try:
        rows = con.execute(
            "SELECT id,pattern,action,args_json,enabled FROM habits ORDER BY id DESC LIMIT ?",
            (max(1,int(limit)),),
        ).fetchall()
        out = []
        for hid, pat, act, ajson, en in rows:
            out.append({"id": hid, "pattern": pat, "action": act, "args": json.loads(ajson or "{}"), "enabled": bool(en)})
        return out
    finally:
        con.close()

def match(text: str) -> Optional[Dict[str, Any]]:
    init_habits()
    t = text or ""
    con = _connect()
    try:
        rows = con.execute(
            "SELECT pattern,action,args_json FROM habits WHERE enabled=1 ORDER BY id DESC LIMIT 200"
        ).fetchall()
        for pat, act, ajson in rows:
            try:
                if re.search(pat, t, flags=re.I):
                    return {"action": act, "args": json.loads(ajson or "{}")}
            except Exception:
                continue
        return None
    finally:
        con.close()
