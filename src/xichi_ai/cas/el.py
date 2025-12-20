from sympy import symbols, Function, diff
from pathlib import Path

def euler_lagrange(L, q, dq):
    # Simplified EL operator: d/dt(∂L/∂q̇) - ∂L/∂q for toy checks
    t = symbols('t', real=True)
    dL_dqdot = diff(L, dq)
    ddt = diff(dL_dqdot, t)
    dL_dq = diff(L, q)
    return ddt - dL_dq

def smoke_el(report_path: str):
    # Simple sanity check: L = 1/2 qdot^2 - V(q) -> EL: q̈ + V'(q) = 0
    from sympy import symbols, Function, diff
    t = symbols('t', real=True)
    q = Function('q')(t)
    qdot = diff(q, t)
    V = Function('V')
    L = (qdot**2)/2 - V(q)
    EL = diff(qdot, t) + diff(V(q), q)
    Path(report_path).write_text(f"# CAS Smoke Test\n\nEL: {EL}\n", encoding="utf-8")
    print(f"[cas] wrote {report_path}")
