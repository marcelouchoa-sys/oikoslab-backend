# routers/islmbp.py
from fastapi import APIRouter
from pydantic import BaseModel
import numpy as np

from services.validador import aplicar_validacao_economica, EconomicValidationError

router = APIRouter()

def _gate(eq: dict) -> tuple[dict, bool]:
    """Aplica hard gate econômico; retorna (validation, blocked)."""
    try:
        return aplicar_validacao_economica(eq), False
    except EconomicValidationError as exc:
        return exc.result, True


def _invalid_response(result: dict) -> dict:
    return {
        "status":     "invalid_solution",
        "errors":     [v["mensagem"] for v in result["errors"]],
        "violations": result["violations"],
        "economia": {
            "valid":      False,
            "warnings":   result["warnings"],
            "errors":     result["errors"],
            "violations": result["violations"],
        },
    }


class ParametrosISLM(BaseModel):
    c0:     float = 100
    c1:     float = 0.75
    I0:     float = 200
    b:      float = 50
    G:      float = 300
    T:      float = 200
    M:      float = 1000
    P:      float = 1.0
    k:      float = 0.5
    h:      float = 100
    aberta: bool  = False
    r_star: float = 0.03
    Y_star: float = 1500
    e:      float = 1.0
    kf:     float = 200
    x0:     float = 100
    x1:     float = 0.1
    m0:     float = 50
    m1:     float = 0.15


def _resolver(p: ParametrosISLM) -> dict:
    if not p.aberta:
        A     = p.c0 - p.c1*p.T + p.I0 + p.G
        denom = (1 - p.c1) + (p.b * p.k / p.h)
        Y     = (A + p.b * p.M / (p.P * p.h)) / denom
        r     = (p.k * Y - p.M / p.P) / p.h
        C     = p.c0 + p.c1 * (Y - p.T)
        I     = p.I0 - p.b * r
        return {"Y": Y, "r": r, "C": C, "I": I, "NX": 0.0, "e": p.e}
    else:
        if p.kf >= 1e5:
            r = p.r_star
            Y = (p.c0 - p.c1*p.T + p.I0 - p.b*r + p.G + p.x0 + p.x1*p.e - p.m0) / (1 - p.c1 + p.m1)
        else:
            A = (1 - p.c1 + p.m1 + (p.b * p.m1) / p.kf)
            B = (p.c0 - p.c1*p.T + p.I0 + p.G + p.x0 + p.x1*p.e - p.m0
                 + p.b*p.r_star - (p.b/p.kf)*(p.x0 + p.x1*p.e - p.m0))
            Y  = B / A
            NX = p.x0 + p.x1*p.e - p.m0 - p.m1*Y
            r  = p.r_star - NX / p.kf
        C  = p.c0 + p.c1*(Y - p.T)
        I  = p.I0 - p.b*r
        NX = p.x0 + p.x1*p.e - p.m0 - p.m1*Y
        return {"Y": Y, "r": r, "C": C, "I": I, "NX": NX, "e": p.e}


@router.post("/equilibrio")
def calcular_equilibrio(p: ParametrosISLM):
    eq = _resolver(p)
    validation, blocked = _gate(eq)
    if blocked:
        return _invalid_response(validation)
    return {"status": "ok", "equilibrio": eq, "economia": validation}


@router.post("/curvas")
def calcular_curvas(p: ParametrosISLM):
    eq = _resolver(p)
    validation, blocked = _gate(eq)
    if blocked:
        return _invalid_response(validation)

    Y_center = eq["Y"]
    Y_grid   = np.linspace(max(100, Y_center - 800), Y_center + 800, 200)

    r_IS = [(p.c0 - p.c1*p.T + p.I0 + p.G - (1 - p.c1)*Y) / p.b for Y in Y_grid]
    r_LM = [(p.k*Y - p.M/p.P) / p.h for Y in Y_grid]

    return {
        "status":     "ok",
        "Y_grid":     Y_grid.tolist(),
        "r_IS":       r_IS,
        "r_LM":       r_LM,
        "equilibrio": eq,
        "economia":   validation,
    }