# routers/motor_sistemas_economicos.py
"""
Motor de resolução de sistemas econômicos simbólicos.

Recebe expressões SymPy nativas e retorna soluções estruturadas.
Para equação única, delega para services.motor_sistemas.resolve_sistema
sem duplicar a lógica de resolução escalar.
"""

import sympy as sp
from typing import Optional

from routers.modelo_proprio import Equacao as _MPEquacao
from services.motor_sistemas import resolve_sistema as _mp_resolve


# ─────────────────────────────────────────────────────────────────────────────
#  CONVERSÃO SymPy → formato modelo_proprio
# ─────────────────────────────────────────────────────────────────────────────

def _to_equacao(expr: sp.Basic) -> _MPEquacao:
    """Serializa uma expressão SymPy para o formato Equacao do modelo_proprio."""
    if isinstance(expr, sp.Equality):
        return _MPEquacao(expressao=f"{expr.lhs} = {expr.rhs}")
    # Expressão sem Eq: interpreta como expr == 0
    return _MPEquacao(expressao=f"0 = {expr}")


def _to_float(val: sp.Basic) -> float | sp.Basic:
    """Converte para float quando possível; retorna simbólico caso contrário."""
    try:
        return float(val.evalf())
    except Exception:
        return val


# ─────────────────────────────────────────────────────────────────────────────
#  DETECÇÃO DE VARIÁVEIS
# ─────────────────────────────────────────────────────────────────────────────

def _detectar_variaveis(
    equacoes: list[sp.Basic],
    variaveis: Optional[list[sp.Symbol]],
    contexto: Optional[dict],
) -> tuple[list[sp.Symbol], list[sp.Symbol]]:
    """
    Classifica símbolos livres em endógenos (a resolver) e exógenos (parâmetros).

    Regra: símbolo exógeno = presente no contexto.
    Se variaveis for fornecido explicitamente, usa como endógenas sem inferência.
    """
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
#  FUNÇÃO PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────

def resolve_sistema(
    equacoes: list[sp.Basic],
    variaveis: Optional[list[sp.Symbol]] = None,
    contexto: Optional[dict] = None,
) -> dict:
    """
    Resolve sistema de equações econômicas simbólicas.

    Args:
        equacoes : lista de sp.Eq ou expressões SymPy (implicitamente == 0).
        variaveis: símbolos a resolver; se None, auto-detectado subtraindo o contexto.
        contexto : parâmetros exógenos como {nome_ou_Symbol: valor_numerico}.

    Returns:
        {
            "solucao"  : dict (solução única) | list[dict] (soluções múltiplas),
            "endogenas": list[str],
            "exogenas" : list[str],
            "tipo"     : "sistema" | "equacao_unica",
            "erros"    : list[str],
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

    # ── FALLBACK: equação única → delega para modelo_proprio ─────────────────
    if len(equacoes) == 1:
        eq = _to_equacao(equacoes[0])
        valores_param = {str(k): float(v) for k, v in (contexto or {}).items()}
        endogenas_nomes = {str(s) for s in endogenas}

        sol_num, _sol_sym, erros = _mp_resolve([eq], valores_param, endogenas_nomes)

        return {
            "solucao": sol_num,
            "endogenas": [str(s) for s in endogenas],
            "exogenas": [str(s) for s in exogenas],
            "tipo": "equacao_unica",
            "erros": erros,
        }

    # ── SISTEMA: resolução direta via sp.solve ────────────────────────────────
    param_subs: dict[sp.Symbol, float] = {
        sp.Symbol(str(k)): float(v)
        for k, v in (contexto or {}).items()
    }

    sistema = [eq.subs(param_subs) if param_subs else eq for eq in equacoes]

    solucao: dict | list = {}
    erros: list[str] = []

    try:
        resultado = sp.solve(sistema, endogenas, dict=True)
        if not resultado:
            erros.append("Sistema sem solução ou subdeterminado.")
        elif len(resultado) == 1:
            solucao = {str(k): _to_float(v) for k, v in resultado[0].items()}
        else:
            # Múltiplas soluções (ex: sistemas não-lineares)
            solucao = [
                {str(k): _to_float(v) for k, v in sol.items()}
                for sol in resultado
            ]
    except NotImplementedError:
        erros.append("SymPy não consegue resolver este sistema analiticamente.")
    except Exception as e:
        erros.append(f"Erro ao resolver sistema: {e}")

    return {
        "solucao": solucao,
        "endogenas": [str(s) for s in endogenas],
        "exogenas": [str(s) for s in exogenas],
        "tipo": "sistema",
        "erros": erros,
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

    # Caso 2: equação única → fallback modelo_proprio
    # Cruz Keynesiana: Y = c*(Y-T) + Inv + G  →  Y(1-c) = Inv + G - c*T
    # Nota: evitar "I" como nome — SymPy reserva I para unidade imaginária
    Y, c, Inv, G, T = sp.symbols("Y c Inv G T")
    _print(
        "Equacao unica (fallback modelo_proprio, Y=1400)",
        resolve_sistema(
            [sp.Eq(Y, c * (Y - T) + Inv + G)],
            contexto={"c": 0.75, "Inv": 200, "G": 300, "T": 200},
        ),
    )

    # Caso 3: IS-LM simplificado (2 equações, 2 incógnitas)
    # IS: Y = 800 - 40r   (demanda agregada sensível ao juro)
    # LM: Y = 400 + 20r   (equilíbrio no mercado de moeda)
    r2, Y2 = sp.symbols("r Y")
    _print(
        "IS-LM (equilibrio simultaneo)",
        resolve_sistema([
            sp.Eq(Y2, 800 - 40 * r2),
            sp.Eq(Y2, 400 + 20 * r2),
        ]),
    )

    # Caso 4: IS-LM com parâmetros exógenos via contexto
    a, b, k, h, M = sp.symbols("a b k h M")
    r3, Y3 = sp.symbols("r Y")
    # IS: Y = a - b*r     (a=800, b=40)
    # LM: k*Y - h*r = M   (k=0.5, h=20, M=100)
    _print(
        "IS-LM parametrico (contexto exogeno)",
        resolve_sistema(
            [
                sp.Eq(Y3, a - b * r3),
                sp.Eq(k * Y3 - h * r3, M),
            ],
            contexto={"a": 800, "b": 40, "k": 0.5, "h": 20, "M": 100},
        ),
    )
