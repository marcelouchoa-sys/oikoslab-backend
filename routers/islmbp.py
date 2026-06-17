# routers/islmbp.py
"""
Adaptador HTTP para o modelo IS-LM-BP.

Toda computação econômica passa por EconomyEngine — nenhuma lógica econômica aqui.
"""
from fastapi import APIRouter
from pydantic import BaseModel

from services.economy_engine import EconomyEngine

router = APIRouter()


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


@router.post("/equilibrio")
def calcular_equilibrio(p: ParametrosISLM) -> dict:
    return EconomyEngine.run_islm(p.model_dump())


@router.post("/curvas")
def calcular_curvas(p: ParametrosISLM) -> dict:
    return EconomyEngine.run_islm_curvas(p.model_dump())
