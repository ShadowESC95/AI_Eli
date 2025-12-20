from pathlib import Path
from sympy import symbols, Function, diff, simplify, Eq

def _d(name):
    return symbols(name, real=True)

def _f(name, t):
    return Function(name)(t)

def derive_and_check(report_path: str):
    """
    Illustrative CAS pass:
      - Minimal 1D-in-time Lagrangian with Xi(t), chi(t), phi(t), A(t).
      - Stueckelberg-like mass m(Xi, chi).
      - Electromagnetic proxy term ~ (A_dot)^2 with epsilon/mu maps.
      - Derive EL equations.
      - Show Maxwell-like recovery with m->0, constant coeffs.
    """
    t = _d('t')
    Xi  = _f('Xi', t)
    chi = _f('chi', t)
    phi = _f('phi', t)
    A   = _f('A', t)   # proxy for a single gauge dof
    Xi_dot  = diff(Xi, t)
    chi_dot = diff(chi, t)
    phi_dot = diff(phi, t)
    A_dot   = diff(A, t)

    # Coefficients as symbolic constants (could be functions of Xi, chi)
    ZXi, Zchi, ZXichi = symbols('Z_Xi Z_chi Z_Xi_chi', real=True)
    aE, aB = symbols('aE aB', real=True)      # ε^{-1}, μ^{-1} proxies
    beta, gammaE = symbols('beta gammaE', real=True)
    y0 = symbols('y0', real=True)             # Stückelberg Y
    m0 = symbols('m0', real=True)             # mass map -> set 0 in Maxwell limit

    # Potentials (simple quadratics to keep analytic)
    m_Xi, m_chi = symbols('m_Xi m_chi', real=True, positive=True)
    lam_Xi, lam_chi, lam_Xichi = symbols('lam_Xi lam_chi lam_Xi_chi', real=True)

    V = (m_Xi**2)*Xi**2/2 + (m_chi**2)*chi**2/2 + lam_Xi*Xi**4 + lam_chi*chi**4 + lam_Xichi*Xi**2*chi**2

    # Minimal 0+1D Lagrangian capturing structure (time-only reduction of the field theory)
    L = 0
    # Scalars kinetic + cross-kinetic
    L += (ZXi*Xi_dot**2 + Zchi*chi_dot**2 + ZXichi*Xi_dot*chi_dot)/2
    # EM energy proxy with coupling (keep just A_dot^2 term as stand-in for F^2)
    L += -(aE/2)*(A_dot**2)
    # Xi-chi ↔ E mixing proxy
    L += beta*gammaE*Xi_dot*chi_dot*A_dot*0  # set to zero in 0+1D to keep algebra simple
    # Stückelberg term: 1/2 Y (phi_dot - m A)^2
    L += (y0/2)*(phi_dot - m0*A)**2
    # Potential
    L += -V

    # Euler–Lagrange in 0+1D: d/dt(∂L/∂qdot) - ∂L/∂q = 0
    def EL(q, qdot):
        return simplify(diff(diff(L, qdot), t) - diff(L, q))

    EL_Xi  = EL(Xi, Xi_dot)
    EL_chi = EL(chi, chi_dot)
    EL_phi = EL(phi, phi_dot)
    EL_A   = EL(A, A_dot)

    # Recovery to "Maxwell-like": m0 -> 0 eliminates Proca/Stueckelberg coupling from A-eqn.
    # Also set constants to constants (no Xi/chi dependence in this toy) and ignore potentials.
    subs_maxwell = {
        m0: 0,
        y0: 1,  # arbitrary positive
        lam_Xi: 0, lam_chi: 0, lam_Xichi: 0,
        m_Xi: 0, m_chi: 0
    }
    EL_A_maxwell = simplify(EL_A.subs(subs_maxwell))

    # In this reduction, EL_A becomes d/dt(aE * A_dot) = 0 (i.e., aE * Ä = 0) if y0*(phi_dot) decouples.
    # But note phi eqn couples: with m0=0, EL_phi => d/dt(y0 * phi_dot) = 0.
    # Together they describe free massless modes (proxy for Maxwell sector).

    lines = []
    lines.append("# CAS Verification Report (Illustrative 0+1D)")
    lines.append("")
    lines.append("## Euler–Lagrange equations (symbolic)")
    lines.append(f"EL_Xi  = {EL_Xi}")
    lines.append(f"EL_chi = {EL_chi}")
    lines.append(f"EL_phi = {EL_phi}")
    lines.append(f"EL_A   = {EL_A}")
    lines.append("")
    lines.append("## Maxwell-like recovery (m0 -> 0, no scalar potentials)")
    lines.append(f"EL_A | Maxwell-limit = {EL_A_maxwell}")
    lines.append("Expected: proportional to Ä (free gauge mode in this toy).")
    lines.append("")
    Path(report_path).write_text("\n".join(lines), encoding="utf-8")
    print(f"[cas-verify] wrote {report_path}")
