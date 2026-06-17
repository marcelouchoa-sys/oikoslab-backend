# routers/motor_sistemas_economicos.py
"""
Motor de resolução de sistemas econômicos simbólicos.

Recebe expressões SymPy nativas e retorna soluções estruturadas.
Toda resolução passa por EconomyEngine — único ponto de entrada do pipeline.
"""

import sympy as sp
from typing import Optional

from routers.modelo_proprio import Equacao as _MPEquacao
from services.economy_engine import EconomyEngine
from services.validador import EconomicValidationError


# ─────────────────────────────────────────────────────────────────────────────
#  CONVERSÃO SymPy → formato modelo_proprio
# ─────────────────────────────────────────────────────────────────────────────

def _to_equacao(expr: sp.Basic) -> _MPEquacao:
    """Serializa uma expressão SymPy para o formato Equacao do modelo_proprio."""
    if isinstance(expr, sp.Equality):
        return _MPEquacao(expressao=f"{expr.lhs} = {expr.rhs}")
    # Expressão sem Eq: interpreta como expr == 0
    return _MPEquacao(expressao=f"0 = {expr}")


# ─────────────────────────────────────────────────────────────────────────────
#  DETECÇÃO DE VARIÁVEIS (auxiliar para metadados do output)
# ─────────────────────────────────────────────────────────────────────────────

def _detectar_variaveis(
    equacoes: list[sp.Basic],
    variaveis: Optional[list[sp.Symbol]],
    contexto: Optional[dict],
) -> tuple[list[sp.Symbol], list[sp.Symbol]]:
    """Classifica símbolos em endógenos e exógenos para metadados do output."""
    todos: set[sp.Symbol] = set()
    for eq in equacoes:
        todos |= eq.free_symbols

    exogenas_nomes = {str(k) for k in (contexto or {}).keys()}

    if variaveis is not None:
        endogenas = list(variaveis)
        exogenas = [s for s in sorted(todos, key=str) if str(s) in exogenas_nomes]
    else:
        endogenas = [s for s in sorted(todos, key=str) if str(s) not in exogenas_nomes]
        exogenas = [s for s in sorted(todos, key=str) if str(s) in exogenas_nomes]

    return endogenas, exogenas


# ─────────────────────────────────────────────────────────────────────────────
#  FUNÇÃO PRINCIPAL — delega ao EconomyEngine
# ─────────────────────────────────────────────────────────────────────────────

def resolve_sistema(
    equacoes: list[sp.Basic],
    variaveis: Optional[list[sp.Symbol]] = None,
    contexto: Optional[dict] = None,
) -> dict:
    """
    Resolve sistema de equações econômicas simbólicas via EconomyEngine.

    Args:
        equacoes : lista de sp.Eq ou expressões SymPy (implicitamente == 0).
        variaveis: símbolos a resolver; se None, auto-detectado subtraindo o contexto.
        contexto : parâmetros exógenos como {nome_ou_Symbol: valor_numerico}.

    Returns:
        {
            "solucao"  : dict — solução numérica,
            "endogenas": list[str],
            "exogenas" : list[str],
            "tipo"     : "sistema" | "equacao_unica",
            "erros"    : list[str],
            "economia" : ValidationResult,
        }
    """
    if not equacoes:
        return {
            "solucao": {},
            "endogenas": [],
            "exogenas": [],
            "tipo": "sistema",
            "erros": ["Lista de equações vazia."],
        }

    endogenas, exogenas = _detectar_variaveis(equacoes, variaveis, contexto)
    eq_objects = [_to_equacao(eq) for eq in equacoes]
    parametros = {str(k): float(v) for k, v in (contexto or {}).items()}
    tipo = "equacao_unica" if len(equacoes) == 1 else "sistema"

    result = EconomyEngine.run(eq_objects, parametros)

    return {
        "solucao":   result.get("valores", {}),
        "endogenas": [str(s) for s in endogenas],
        "exogenas":  [str(s) for s in exogenas],
        "tipo":      tipo,
        "erros":     result.get("erros", []),
        "economia":  result.get("economia", {}),
    }


# ─────────────────────────────────────────────────────────────────────────────
#  TESTES (python -m routers.motor_sistemas_economicos)
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json

    def _print(titulo: str, resultado: dict) -> None:
        print(f"\n-- {titulo} --")
        print(json.dumps(resultado, default=str, indent=2))

    # Caso 1: equilíbrio oferta-demanda (sistema 3 equações, 3 incógnitas)
    P, Qd, Qs = sp.symbols("P Qd Qs")
    _print(
        "Oferta-Demanda (P=16, Qd=Qs=68)",
        resolve_sistema([
            sp.Eq(Qd, 100 - 2 * P),
            sp.Eq(Qs, 20 + 3 * P),
            sp.Eq(Qd, Qs),
        ]),
    )

    # Caso 2: equação única
    Y, c, Inv, G, T = sp.symbols("Y c Inv G T")
    _print(
        "Equacao unica (Y=1400)",
        resolve_sistema(
            [sp.Eq(Y, c * (Y - T) + Inv + G)],
            contexto={"c": 0.75, "Inv": 200, "G": 300, "T": 200},
        ),
    )

    # Caso 3: IS-LM simplificado (2 equações, 2 incógnitas)
    r2, Y2 = sp.symbols("r Y")
    _print(
        "IS-LM (equilibrio simultaneo)",
        resolve_sistema([
            sp.Eq(Y2, 800 - 40 * r2),
            sp.Eq(Y2, 400 + 20 * r2),
        ]),
    )
