import os, re, csv
root = os.path.expanduser(os.environ.get("XICHI_OUT","~/XiChi"))
txt_root = os.path.join(root, "txt")
out_csv = os.path.join(root, "json", "equations_fuzzy.csv")
os.makedirs(os.path.dirname(out_csv), exist_ok=True)

greek = "αβγδεζηθικλμνξοπρστυφχψωΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ"
math_ops = "±≈≃≅≤≥→←↔⋅·∑∏∫∮∂∇∞ΩΞχμγλρσπθ"
ascii_ops = r"[=+\-*/^_<>]"
digits = r"\d"

line_has_math = re.compile(
    rf"([{re.escape(greek)}])|[{re.escape(math_ops)}]|{ascii_ops}.*{digits}|{digits}.*{ascii_ops}"
)

rows = []
for dirpath, _, files in os.walk(txt_root):
    for fn in files:
        if not fn.endswith(".txt"): continue
        path = os.path.join(dirpath, fn)
        rel = os.path.relpath(path, txt_root)
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for ln in f:
                s = ln.strip()
                if len(s) < 3: continue
                if line_has_math.search(s):
                    s = " ".join(s.split())
                    rows.append([rel, "line", s])

# de-dup
seen = set(); dedup = []
for r in rows:
    key = tuple(r)
    if key in seen: continue
    seen.add(key); dedup.append(r)

os.makedirs(os.path.dirname(out_csv), exist_ok=True)
with open(out_csv, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["source","kind","snippet"])
    w.writerows(dedup)

print(f"Wrote {len(dedup)} math-ish snippets -> {out_csv}")
