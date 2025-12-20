import os, sqlite3, time

root = os.path.expanduser(os.environ.get("XICHI_OUT","~/XiChi"))
txt_root = os.path.join(root, "txt")
db_path  = os.path.join(root, "sqlite", "xichi_corpus.sqlite")
os.makedirs(os.path.dirname(db_path), exist_ok=True)

con = sqlite3.connect(db_path)
cur = con.cursor()
cur.executescript("""
PRAGMA journal_mode=WAL;
DROP TABLE IF EXISTS docs;
DROP TABLE IF EXISTS fts;

CREATE TABLE docs(
  id INTEGER PRIMARY KEY,
  rel_path TEXT UNIQUE,
  size_bytes INTEGER,
  mtime REAL
);

-- unicode61 tokenizer keeps Greek/Unicode; no stemming; keep diacritics
CREATE VIRTUAL TABLE fts USING fts5(
  rel_path UNINDEXED,
  text,
  content='',
  tokenize = 'unicode61 remove_diacritics 0'
);
""")

rows_docs = []
rows_fts = []

for dirpath, _, files in os.walk(txt_root):
    for fn in files:
        if not fn.endswith(".txt"): continue
        path = os.path.join(dirpath, fn)
        rel = os.path.relpath(path, txt_root)
        try:
            st = os.stat(path)
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                t = f.read()
            rows_docs.append((rel, st.st_size, st.st_mtime))
            rows_fts.append((rel, t))
        except Exception as e:
            print("SKIP", rel, e)

cur.executemany("INSERT INTO docs(rel_path,size_bytes,mtime) VALUES (?,?,?) ON CONFLICT(rel_path) DO UPDATE SET size_bytes=excluded.size_bytes, mtime=excluded.mtime", rows_docs)
cur.executemany("INSERT INTO fts(rel_path,text) VALUES (?,?)", rows_fts)

con.commit()
con.close()
print(f"Indexed {len(rows_docs)} files into {db_path}")
