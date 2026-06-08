# routers/modelo_proprio.py
"""
Endpoint para resolver modelos economicos definidos pelo usuario.
Usa sympy para algebra simbolica.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Any
import sympy as sp
import numpy as np
import re

router = APIRouter()


class Parametro(BaseModel):
    nome:  str
    valor: float
    descricao: str = ""


class Equacao(BaseModel):
    nome:      str        # ex: "Consumo" ou "C"
    expressao: str        # ex: "c0 + c1*(Y - T)"
    variavel:  str        # variavel do lado esquerdo ex: "C"


class VariavelLivre(BaseModel):
    nome:  str            # ex: "Y"
    min:   float = 0
    max:   float = 2000
    pontos: int  = 200


class ModeloInput(BaseModel):
    parametros:     list[Parametro]
    equacoes:       list[Equacao]
    variavel_livre: VariavelLivre | None = None


class ResultadoModelo(BaseModel):
    status:      str
    valores:     dict[str, float]
    series:      dict[str, list[float]] | None = None
    erros:       list[str]
    latex:       dict[str, str]


@router.post("/resolver", response_model=ResultadoModelo)
def resolver_modelo(modelo: ModeloInput) -> ResultadoModelo:
    """
    Resolve um modelo economico definido pelo usuario.

    Exemplo de input:
    {
      "parametros": [
        {"nome": "c0", "valor": 100},
        {"nome": "c1", "valor": 0.75},
        {"nome": "T",  "valor": 200},
        {"nome": "G",  "valor": 300},
        {"nome": "I0", "valor": 200}
      ],
      "equacoes": [
        {"nome": "Consumo",    "variavel": "C", "expressao": "c0 + c1*(Y - T)"},
        {"nome": "Investimento","variavel": "I", "expressao": "I0"},
        {"nome": "Produto",    "variavel": "Y", "expressao": "C + I + G"}
      ],
      "variavel_livre": {"nome": "Y", "min": 0, "max": 2000, "pontos": 200}
    }
    """
    erros  = []
    valores: dict[str, float] = {}
    series: dict[str, list[float]] | None = None
    latex_map: dict[str, str] = {}

    try:
        # 1. Criar namespace com parâmetros
        namespace: dict[str, Any] = {}
        for p in modelo.parametros:
            namespace[p.nome] = p.valor
            valores[p.nome]   = p.valor

        # 2. Gerar LaTeX de cada equação
        for eq in modelo.equacoes:
            try:
                expr_sym = sp.sympify(eq.expressao, locals=namespace)
                latex_map[eq.variavel] = f"{eq.variavel} = {sp.latex(expr_sym)}"
            except Exception:
                latex_map[eq.variavel] = f"{eq.variavel} = {eq.expressao}"

        # 3. Tentar resolver o sistema simbolicamente
        # Detectar variáveis desconhecidas (não são parâmetros)
        todas_vars = set()
        for eq in modelo.equacoes:
            todas_vars.add(eq.variavel)

        # Criar símbolos para variáveis endógenas
        simbolos = {v: sp.Symbol(v) for v in todas_vars}
        namespace_sym = {**namespace, **simbolos}

        # Montar sistema de equações: variavel - expressao = 0
        sistema = []
        for eq in modelo.equacoes:
            try:
                lhs  = simbolos[eq.variavel]
                rhs  = sp.sympify(eq.expressao, locals=namespace_sym)
                sistema.append(sp.Eq(lhs, rhs))
            except Exception as e:
                erros.append(f"Erro na equacao '{eq.nome}': {e}")

        if sistema and not erros:
            try:
                solucao = sp.solve(sistema, list(simbolos.values()), dict=True)
                if solucao:
                    for var, val in solucao[0].items():
                        try:
                            valores[str(var)] = float(val.evalf())
                        except Exception:
                            valores[str(var)] = float(val)
            except Exception as e:
                erros.append(f"Nao foi possivel resolver o sistema: {e}")
                # Fallback: avaliar equações em sequência
                for eq in modelo.equacoes:
                    try:
                        ns_eval = {**namespace, **valores}
                        resultado = eval(eq.expressao, {"__builtins__": {}}, ns_eval)
                        valores[eq.variavel] = float(resultado)
                    except Exception as e2:
                        erros.append(f"Fallback falhou em '{eq.nome}': {e2}")

        # 4. Gerar séries se houver variável livre
        if modelo.variavel_livre and not erros:
            vl   = modelo.variavel_livre
            grid = np.linspace(vl.min, vl.max, vl.pontos).tolist()
            series = {vl.nome: grid}

            for eq in modelo.equacoes:
                if eq.variavel == vl.nome:
                    continue
                try:
                    serie = []
                    for x in grid:
                        ns_eval = {**namespace, **valores, vl.nome: x}
                        val = eval(eq.expressao, {"__builtins__": {}}, ns_eval)
                        serie.append(float(val))
                    series[eq.variavel] = serie
                except Exception as e:
                    erros.append(f"Erro ao gerar serie de '{eq.variavel}': {e}")

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return ResultadoModelo(
        status="ok" if not erros else "parcial",
        valores=valores,
        series=series,
        erros=erros,
        latex=latex_map,
    )


@router.post("/validar")
def validar_expressao(payload: dict) -> dict:
    """
    Valida se uma expressao matematica e valida.
    """
    expressao  = payload.get("expressao", "")
    parametros = payload.get("parametros", {})

    try:
        namespace = {k: sp.Symbol(k) for k in parametros}
        sp.sympify(expressao, locals=namespace)
        return {"valido": True, "erro": None}
    except Exception as e:
        return {"valido": False, "erro": str(e)}