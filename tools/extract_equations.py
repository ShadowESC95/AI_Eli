import os, re, csv, sys
root = os.path.expanduser(os.environ.get("XICHI_OUT","~/XiChi"))
txt_root = os.path.join(root, "txt")
out_csv = os.path.join(root, "json", "equations.csv")
os.makedirs(os.path.dirname(out_csv), exist_ok=True)

# regexes for $...$, \[...\], \begin{equation}...\end{equation}
inline = re.compile(r'\$(?P<eq>(?:\\.|[^$])+?)\$', re.DOTALL)
display = re.compile(r'\\\[(?P<eq>(?:\\.|[^\\])+?)\\\]', re.DOTALL)
env = re.compile(r'\\begin\{equation\*?\}(?P<eq>.*?)\\end\{equation\*?\}', re.DOTALL)

rows = []
for dirpath,_,files in os.walk(txt_root):
    for fn in files:
        if not fn.endswith('.txt'): continue
        path = os.path.join(dirpath, fn)
        rel = os.path.relpath(path, txt_root)
        with open(path,'r',encoding='utf-8',errors='replace') as f:
            t = f.read()
        for rx,src in [(inline,'inline'),(display,'display'),(env,'env')]:
            for m in rx.finditer(t):
                eq = ' '.join(m.group('eq').split())
                rows.append([rel, src, eq[:4096]])

with open(out_csv,'w',newline='',encoding='utf-8') as f:
    w = csv.writer(f)
    w.writerow(['source','kind','equation'])
    w.writerows(rows)

print(f"Wrote {len(rows)} equations -> {out_csv}")
