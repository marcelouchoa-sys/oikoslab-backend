"""
Camada de validação econômica e engine de cenários.

Funções puras — sem dependências HTTP ou Pydantic.
"""
import sympy as sp


# ─────────────────────────────────────────────────────────────────────────────
#  RESTRIÇÕES ECONÔMICAS
# ─────────────────────────────────────────────────────────────────────────────

# variável → (mínimo_aceitável, mensagem_de_violação)
# None como mínimo = sem restrição (ex: inflação pode ser negativa)
_RESTRICOES: dict[str, tuple[float | None, str]] = {
    'r':    (0.0, 'Taxa de juros negativa (inviável economicamente)'),
    'i':    (0.0, 'Taxa de juros negativa (inviável economicamente)'),
    'Y':    (0.0, 'Produto negativo (inviável economicamente)'),
    'C':    (0.0, 'Consumo negativo (inviável economicamente)'),
    'I':    (0.0, 'Investimento negativo (inviável economicamente)'),
    'G':    (0.0, 'Gasto do governo negativo'),
    'Qd':   (0.0, 'Quantidade demandada negativa'),
    'Qs':   (0.0, 'Quantidade ofertada negativa'),
    'P':    (0.0, 'Preço negativo (inviável em mercados reais)'),
    'W':    (0.0, 'Salário negativo'),
    'L':    (0.0, 'Nível de emprego negativo'),
    'kstar':(0.0, 'Capital por trabalhador negativo'),
    'pi':   (None, ''),  # inflação: deflação é possível
}

# Lista legível das restrições para o campo "restricoes" do output
RESTRICOES_PADRAO: list[str] = [
    'r ≥ 0  — taxa de juros não-negativa',
    'Y ≥ 0  — produto não-negativo',
    'C ≥ 0  — consumo não-negativo',
    'I ≥ 0  — investimento não-negativo',
    'P ≥ 0  — preço não-negativo',
    'Qd ≥ 0 — quantidade demandada não-negativa',
    'Qs ≥ 0 — quantidade ofertada não-negativa',
    'W ≥ 0  — salário não-negativo',
    'L ≥ 0  — emprego não-negativo',
]


# ─────────────────────────────────────────────────────────────────────────────
#  1. VARIABLE CLASSIFICATION LAYER
# ─────────────────────────────────────────────────────────────────────────────

def classificar_variaveis(equacoes: list, parametros: dict) -> dict:
    """
    Classifica todos os símbolos do sistema em endógenos e exógenos.

    Endógena : aparece no sistema e NÃO tem valor em parametros.
    Exógena  : tem valor explícito em parametros.
    Nunca assume valor 0 para símbolos não definidos.

    Args:
        equacoes  : lista de objetos com .expressao e .variavel
        parametros: dict {nome: valor} dos parâmetros explícitos

    Returns:
        {'endogenas': list[str], 'exogenas': list[str]}
    """
    from services.motor_sistemas import _split_equacao

    todos: set[str] = set()
    for eq in equacoes:
        lhs, rhs = _split_equacao(eq)
        if lhs and lhs.isidentifier():
            todos.add(lhs)
        try:
            for s in sp.sympify(rhs).free_symbols:
                todos.add(str(s))
        except Exception:
            pass

    endogenas = sorted(s for s in todos if s not in parametros)
    exogenas  = sorted(s for s in todos if s in parametros)
    return {'endogenas': endogenas, 'exogenas': exogenas}


# ─────────────────────────────────────────────────────────────────────────────
#  3. EQUATION DEDUPLICATION LAYER
# ─────────────────────────────────────────────────────────────────────────────

def normalizar_sistema(equacoes: list) -> list[str]:
    """
    Remove duplicatas simbólicas e normaliza para 'lhs = rhs'.

    Duplicata: lhs − rhs == 0 após sp.expand (comparação de string na forma
    expandida — rápido e suficiente para modelos econômicos lineares).

    Returns:
        lista de strings 'lhs = rhs' sem duplicatas.
    """
    from services.motor_sistemas import _split_equacao

    vistas: set[str] = set()
    normalizadas: list[str] = []

    for eq in equacoes:
        lhs, rhs = _split_equacao(eq)
        if not lhs or not rhs:
            continue
        try:
            canonical = str(sp.expand(sp.sympify(lhs) - sp.sympify(rhs)))
        except Exception:
            canonical = f"{lhs}={rhs}"

        if canonical in vistas:
            continue
        vistas.add(canonical)
        normalizadas.append(f"{lhs.strip()} = {rhs.strip()}")

    return normalizadas


# ─────────────────────────────────────────────────────────────────────────────
#  2. ECONOMIC CONSTRAINT LAYER
# ─────────────────────────────────────────────────────────────────────────────

def validar_restricoes_economicas(solucao: dict) -> list[dict]:
    """
    Verifica restrições mínimas de viabilidade econômica.
    NÃO bloqueia a solução — retorna apenas warnings.

    Returns:
        lista de {'variavel', 'tipo', 'valor', 'mensagem'}
    """
    warnings: list[dict] = []
    for var, val in solucao.items():
        if not isinstance(val, (int, float)):
            continue
        restricao = _RESTRICOES.get(var)
        if restricao is None or restricao[0] is None:
            continue
        minimo, mensagem = restricao
        if val < minimo:
            warnings.append({
                'variavel': var,
                'tipo': 'violacao_economica',
                'valor': round(float(val), 6),
                'mensagem': mensagem,
            })
    return warnings


# ─────────────────────────────────────────────────────────────────────────────
#  4. SOLUTION VALIDATION LAYER
# ─────────────────────────────────────────────────────────────────────────────

def validar_solucao(equacoes: list, solucao: dict) -> list[str]:
    """
    Recalcula cada equação com a solução encontrada e verifica consistência.
    Ignora equações com símbolos livres (solução simbólica parcial).

    Tolerância: 1e-6.

    Returns:
        lista de strings descrevendo inconsistências (vazia = tudo ok).
    """
    from services.motor_sistemas import _split_equacao

    erros: list[str] = []
    subs = {sp.Symbol(k): v for k, v in solucao.items() if isinstance(v, (int, float))}
    if not subs:
        return []

    for eq in equacoes:
        lhs, rhs = _split_equacao(eq)
        if not lhs or not rhs:
            continue
        try:
            lhs_val = float(sp.sympify(lhs).subs(subs).evalf())
            rhs_val = float(sp.sympify(rhs).subs(subs).evalf())
            diff = abs(lhs_val - rhs_val)
            if diff > 1e-6:
                erros.append(
                    f"'{lhs} = {rhs}': "
                    f"LHS={lhs_val:.6g}, RHS={rhs_val:.6g} "
                    f"(diff={diff:.2e})"
                )
        except Exception:
            pass  # Equação ainda tem símbolos livres — pula

    return erros


# ─────────────────────────────────────────────────────────────────────────────
#  6. SCENARIO ENGINE
# ─────────────────────────────────────────────────────────────────────────────

def simular_cenario(
    resolver_fn,
    parametros_base: dict,
    variacoes: list[dict],
) -> dict:
    """
    Executa cenário base + variações e retorna resultados comparativos.

    Args:
        resolver_fn  : callable(params: dict) → dict[str, float | str]
                       — recebe parâmetros e retorna solução numérica
        parametros_base: {'param': valor} do cenário base
        variacoes    : [{'nome': str, 'param': str, 'valor': float}, ...]
                       — cada entrada define uma variação de um único parâmetro

    Returns:
        {
            'base'    : {'param1': v1, ...},  # solução do cenário base
            'cenarios': [
                {
                    'nome'            : str,
                    'parametro_variado': str,
                    'valor'           : float,
                    'solucao'         : dict,
                    'delta_vs_base'   : dict,  # diferença em relação ao base
                },
                ...
            ]
        }
    """
    base = resolver_fn(parametros_base)
    cenarios: list[dict] = []

    for var in variacoes:
        params = dict(parametros_base)
        params[var['param']] = var['valor']
        sol = resolver_fn(params)

        delta = {
            k: round(float(sol[k]) - float(base.get(k, 0)), 6)
            for k in sol
            if isinstance(sol.get(k), (int, float))
            and isinstance(base.get(k), (int, float))
        }

        cenarios.append({
            'nome': var.get('nome') or f"{var['param']}={var['valor']}",
            'parametro_variado': var['param'],
            'valor': var['valor'],
            'solucao': sol,
            'delta_vs_base': delta,
        })

    return {'base': base, 'cenarios': cenarios}
