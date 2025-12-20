import csv, os
root = os.path.expanduser(os.environ.get("XICHI_OUT","~/XiChi"))
eq_csv = os.path.join(root, "json", "equations.csv")
out_csv = os.path.join(root, "json", "conflict_table.csv")

def guess_key(eq:str)->str:
    # crude keys to help de-dup (edit as needed)
    for token in [r'c_T', r'\xi_R', r'm_\gamma', r'\Omega', r'F_{E}', r'F_{B}', r'\nabla\cdot', r'\nabla\times']:
        if token in eq: return token
    return eq[:32]

with open(eq_csv, newline='', encoding='utf-8') as f, \
     open(out_csv,'w',newline='',encoding='utf-8') as g:
    r = csv.DictReader(f)
    w = csv.writer(g)
    w.writerow(['key','equation','source','assumes','contradicts','minimal_edit','notes'])
    for row in r:
        eq = row['equation']
        key = guess_key(eq)
        w.writerow([key, eq, row['source'], '', '', '', ''])

print("Wrote", out_csv)
