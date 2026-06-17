"""
Motor matemático de resolução de sistemas econômicos.

Camada de serviço pura — sem dependências HTTP ou Pydantic.
Recebe equações no formato interno do OikosLab e devolve soluções SymPy.
"""

import sympy as sp


def _split_equacao(eq) -> tuple[str, str]:
    """Normaliza equação em (lhs_str, rhs_str). Aceita 'C = a + c*Y' ou variavel+expressao."""
    expr = eq.expressao.strip()
    if "=" in expr:
        lhs, rhs = expr.split("=", 1)
        return lhs.strip(), rhs.strip()
    return eq.variavel.strip(), expr


def resolve_sistema(
    equacoes: list,
    valores_param: dict,
    endogenas,
) -> tuple[dict, dict, list]:
    """
    Resolve sistema simultâneo de equações econômicas.

    Args:
        equacoes     : lista de objetos com .expressao (str) e .variavel (str)
        valores_param: {nome_param: float} — parâmetros exógenos
        endogenas    : iterable[str] — nomes das variáveis a resolver.
                       Se list, a ORDEM é preservada: variáveis ao final tendem
                       a ser escolhidas como parâmetros livres em sistemas
                       subdeterminados (comportamento SymPy com eliminação gaussiana).

    Returns:
        (sol_numerica, sol_simbolica, erros)
        - sol_numerica : {str: float | str} — float quando determinado, str quando simbólico
        - sol_simbolica: {Symbol: Expr}     — útil para elasticidades e séries
        - erros        : list[str]
    """
    erros: list[str] = []
    # Preserva ordem se lista/tupla; ordena se set (sem ordem garantida)
    endogenas_seq = endogenas if isinstance(endogenas, (list, tuple)) else sorted(endogenas)
    simbolos = {v: sp.Symbol(v) for v in endogenas_seq}
    param_subs = {sp.Symbol(k): v for k, v in valores_param.items()}

    sistema: list[sp.Equality] = []
    for eq in equacoes:
        lhs, rhs = _split_equacao(eq)
        if not lhs or not rhs:
            continue
        try:
            lhs_e = sp.sympify(lhs, locals=simbolos)
            rhs_e = sp.sympify(rhs, locals=simbolos)
            sistema.append(sp.Eq(lhs_e, rhs_e))
        except Exception as e:
            erros.append(f"Erro ao interpretar '{lhs} = {rhs}': {e}")

    if not sistema:
        return {}, {}, erros or ["Nenhuma equação válida."]

    incognitas = list(simbolos.values())

    # Solução simbólica — mantém parâmetros como letras (habilita derivadas/elasticidades)
    sol_simbolica: dict = {}
    try:
        sol = sp.solve(sistema, incognitas, dict=True)
        if sol:
            sol_simbolica = sol[0]
    except Exception as e:
        erros.append(f"Solução simbólica falhou: {e}")

    # Solução numérica — substitui valores dos parâmetros
    # Retorna float quando totalmente determinado; str simbólico quando há variáveis livres.
    sol_numerica: dict = {}
    try:
        sistema_num = [eq.subs(param_subs) for eq in sistema]
        sol = sp.solve(sistema_num, incognitas, dict=True)
        if sol:
            for var, val in sol[0].items():
                evaluated = val.subs(param_subs)
                try:
                    sol_numerica[str(var)] = float(evaluated.evalf())
                except Exception:
                    sol_numerica[str(var)] = str(val)
        elif sol_simbolica:
            # fallback: avalia solução simbólica com os valores fornecidos
            for var, expr in sol_simbolica.items():
                evaluated = expr.subs(param_subs)
                try:
                    sol_numerica[str(var)] = float(evaluated.evalf())
                except Exception:
                    sol_numerica[str(var)] = str(evaluated)
    except Exception as e:
        erros.append(f"Solução numérica falhou: {e}")

    return sol_numerica, sol_simbolica, erros
