# routers/exemplos_didaticos.py
#
# Calculadoras didáticas simples (consumo/investimento), sem relação com a
# tabela Supabase `funcoes` do Construtor de Funções — renomeado de
# funcoes.py para não colidir de nome com esse outro sistema.
from fastapi import APIRouter
from pydantic import BaseModel
import numpy as np

router = APIRouter()


class ParamsConsumo(BaseModel):
    c0:    float = 100
    c1:    float = 0.75
    Y_min: float = 0
    Y_max: float = 2000


class ParamsInvestimento(BaseModel):
    I0:    float = 200
    b:     float = 50
    r_min: float = 0
    r_max: float = 20


@router.post("/consumo")
def calcular_consumo(p: ParamsConsumo):
    Y = np.linspace(p.Y_min, p.Y_max, 200).tolist()
    C = [p.c0 + p.c1 * y for y in Y]
    return {"Y": Y, "C": C, "c0": p.c0, "c1": p.c1, "multiplicador": 1/(1-p.c1)}


@router.post("/investimento")
def calcular_investimento(p: ParamsInvestimento):
    r = np.linspace(p.r_min, p.r_max, 200).tolist()
    I = [max(0.0, p.I0 - p.b * ri) for ri in r]
    return {"r": r, "I": I, "I0": p.I0, "b": p.b}
