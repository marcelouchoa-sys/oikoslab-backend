"""
Endpoint para resolver modelos economicos definidos pelo usuario.
Usa sympy para algebra simbolica.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Any
import sympy as sp
import numpy as np

router = APIRouter()


class Parametro(BaseModel):
    nome: str
    valor: float
    descricao: str = ""


class Equacao(BaseModel):
    nome: str
    expressao: str
    variavel: str


class VariavelLivre(BaseModel):
    nome: str
    min: float = 0
    max: float = 2000
    pontos: int = 200


class ModeloInput(BaseModel):
    parametros: list[Parametro]
    equacoes: list[Equacao]
    variavel_livre: VariavelLivre | None = None


class ResultadoModelo(BaseModel):
    status: str
    valores: dict[str, float]
    series: dict[str, list[float]] | None = None
    erros: list[str]
    latex: dict[str, str]


@router.post("/resolver", response_model=ResultadoModelo)
def resolver_modelo(modelo: ModeloInput) -> ResultadoModelo:

    erros = []
    valores: dict[str, float] = {}
    series: dict[str, list[float]] | None = None
    latex_map: dict[str, str] = {}

    try:

        # =====================================================
        # 1. Namespace dos parâmetros
        # =====================================================

        namespace: dict[str, Any] = {}

        for p in modelo.parametros:
            nome = p.nome.strip()

            if not nome:
                continue

            namespace[nome] = p.valor
            valores[nome] = p.valor

        # =====================================================
        # 2. Latex
        # =====================================================

        for eq in modelo.equacoes:

            if not eq.variavel.strip():
                continue

            if not eq.expressao.strip():
                continue

            try:
                expr_sym = sp.sympify(eq.expressao, locals=namespace)

                latex_map[
                    eq.variavel.strip()
                ] = f"{eq.variavel.strip()} = {sp.latex(expr_sym)}"

            except Exception:
                latex_map[
                    eq.variavel.strip()
                ] = f"{eq.variavel.strip()} = {eq.expressao}"

        # =====================================================
        # 3. Resolver sistema
        # =====================================================

        todas_vars = set()

        for eq in modelo.equacoes:

            if not eq.variavel.strip():
                continue

            todas_vars.add(eq.variavel.strip())

        simbolos = {
            v: sp.Symbol(v)
            for v in todas_vars
            if v.strip()
        }

        namespace_sym = {
            **namespace,
            **simbolos
        }

        sistema = []

        for eq in modelo.equacoes:

            if not eq.variavel.strip():
                continue

            if not eq.expressao.strip():
                continue

            try:

                lhs = simbolos[eq.variavel.strip()]

                rhs = sp.sympify(
                    eq.expressao,
                    locals=namespace_sym
                )

                sistema.append(
                    sp.Eq(lhs, rhs)
                )

            except Exception as e:
                erros.append(
                    f"Erro na equacao '{eq.nome}': {e}"
                )

        if sistema and not erros:

            try:

                solucao = sp.solve(
                    sistema,
                    list(simbolos.values()),
                    dict=True
                )

                if solucao:

                    for var, val in solucao[0].items():

                        try:
                            valores[str(var)] = float(val.evalf())

                        except Exception:
                            valores[str(var)] = float(val)

            except Exception as e:

                erros.append(
                    f"Nao foi possivel resolver o sistema: {e}"
                )

                # Fallback
                for eq in modelo.equacoes:

                    if not eq.variavel.strip():
                        continue

                    if not eq.expressao.strip():
                        continue

                    try:

                        ns_eval = {
                            **namespace,
                            **valores
                        }

                        resultado = eval(
                            eq.expressao,
                            {"__builtins__": {}},
                            ns_eval
                        )

                        valores[
                            eq.variavel.strip()
                        ] = float(resultado)

                    except Exception as e2:

                        erros.append(
                            f"Fallback falhou em '{eq.nome}': {e2}"
                        )

        # =====================================================
        # 4. Séries
        # =====================================================

        if modelo.variavel_livre and not erros:

            vl = modelo.variavel_livre

            grid = np.linspace(
                vl.min,
                vl.max,
                vl.pontos
            ).tolist()

            series = {
                vl.nome: grid
            }

            for eq in modelo.equacoes:

                if not eq.variavel.strip():
                    continue

                if not eq.expressao.strip():
                    continue

                if eq.variavel.strip() == vl.nome:
                    continue

                try:

                    serie = []

                    for x in grid:

                        ns_eval = {
                            **namespace,
                            **valores,
                            vl.nome: x
                        }

                        val = eval(
                            eq.expressao,
                            {"__builtins__": {}},
                            ns_eval
                        )

                        serie.append(float(val))

                    series[
                        eq.variavel.strip()
                    ] = serie

                except Exception as e:

                    erros.append(
                        f"Erro ao gerar serie de '{eq.variavel}': {e}"
                    )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

    return ResultadoModelo(
        status="ok" if not erros else "parcial",
        valores=valores,
        series=series,
        erros=erros,
        latex=latex_map,
    )


@router.post("/validar")
def validar_expressao(payload: dict) -> dict:

    expressao = payload.get("expressao", "")
    parametros = payload.get("parametros", {})

    try:

        namespace = {
            k: sp.Symbol(k)
            for k in parametros
            if str(k).strip()
        }

        sp.sympify(
            expressao,
            locals=namespace
        )

        return {
            "valido": True,
            "erro": None
        }

    except Exception as e:

        return {
            "valido": False,
            "erro": str(e)
        }