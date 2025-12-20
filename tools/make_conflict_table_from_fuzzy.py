import csv, os, re
root = os.path.expanduser(os.environ.get("XICHI_OUT","~/XiChi"))
inp = os.path.join(root, "json", "equations_fuzzy.csv")
outp = os.path.join(root, "json", "conflict_table.csv")

hotkeys = [
  ("c_T", r"\bc_T\b|c_T=1"),
  ("Omega2", r"Ω|\bOmega\b"),
  ("Stueckelberg", r"[Ss]tueckelberg"),
  ("m_gamma", r"m.?γ|m[_ ]?gamma"),
  ("FE", r"\bF[_ ]?E\b|F_E"),
  ("FB", r"\bF[_ ]?B\b|F_B"),
  ("nabla", r"∇|\\nabla"),
  ("div", r"∇·|\bdiv\b"),
  ("curl", r"∇×|\bcurl\b"),
  ("xi_chi", r"Ξ|χ|\bXi\b|\bchi\b"),
]

def key_for(s):
  for k, rx in hotkeys:
    if re.search(rx, s): return k
  return s[:40]

with open(inp, newline='', encoding='utf-8') as f, \
     open(outp, 'w', newline='', encoding='utf-8') as g:
  r = csv.DictReader(f)
  w = csv.writer(g)
  w.writerow(['key','snippet','source','assumes','contradicts','minimal_edit','notes'])
  for row in r:
    s = row['snippet']
    key = key_for(s)
    w.writerow([key, s, row['source'], '', '', '', ''])

print("Wrote", outp)
