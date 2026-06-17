"""
Camada de validação econômica e engine de cenários.

Funções puras — sem dependências HTTP ou Pydantic.

Contratos internos
──────────────────
ValidationResult  → {valid, warnings, errors, violations}
SolverOutput      → {variables, expressions, metadata}
"""
import sympy as sp
from typing import TypedDict


# ─────────────────────────────────────────────────────────────────────────────
#  CONTRATOS INTERNOS (typed dicts)
# ─────────────────────────────────────────────────────────────────────────────

class ValidationResult(TypedDict):
    valid:      bool    # False quando há errors (violações bloqueantes)
    warnings:   list    # violações não-bloqueantes (modo "warning")
    errors:     list    # violações bloqueantes
    violations: list    # todas as violações (warnings + errors)


class SolverOutput(TypedDict):
    variables:   dict   # {str: float | str}
    expressions: dict   # {str: str} — solução simbólica
    metadata:    dict   # {endogenas, parametros, erros}


# ─────────────────────────────────────────────────────────────────────────────
#  MATRIZ DE REGRAS ECONÔMICAS
# ─────────────────────────────────────────────────────────────────────────────
#
# bloqueante_sempre=True  → vai para errors[] em QUALQUER modo (sempre bloqueia)
# bloqueante_sempre=False → vai para warnings[] em "warning"; errors[] em "fail_fast"

_REGRAS_ECONOMICAS: dict[str, dict] = {
    'Y':     {'min': 0.0, 'gravidade': 'alta',  'bloqueante_sempre': True,
               'mensagem': 'Produto negativo (inviável economicamente)'},
    'C':     {'min': 0.0, 'gravidade': 'alta',  'bloqueante_sempre': True,
               'mensagem': 'Consumo negativo (inviável economicamente)'},
    'I':     {'min': 0.0, 'gravidade': 'media', 'bloqueante_sempre': True,
               'mensagem': 'Investimento negativo (inviável economicamente)'},
    'P':     {'min': 0.0, 'gravidade': 'alta',  'bloqueante_sempre': True,
               'mensagem': 'Preço negativo (inviável em mercados reais)'},
    'Qd':    {'min': 0.0, 'gravidade': 'media', 'bloqueante_sempre': True,
               'mensagem': 'Quantidade demandada negativa'},
    'Qs':    {'min': 0.0, 'gravidade': 'media', 'bloqueante_sempre': True,
               'mensagem': 'Quantidade ofertada negativa'},
    # ── warning por padrão; fail_fast opcional ────────────────────────────────
    'r':     {'min': 0.0, 'gravidade': 'alta',  'bloqueante_sempre': False,
               'mensagem': 'Taxa de juros negativa (inviável economicamente)'},
    'i':     {'min': 0.0, 'gravidade': 'alta',  'bloqueante_sempre': False,
               'mensagem': 'Taxa de juros negativa (inviável economicamente)'},
    'G':     {'min': 0.0, 'gravidade': 'baixa', 'bloqueante_sempre': False,
               'mensagem': 'Gasto do governo negativo'},
    'W':     {'min': 0.0, 'gravidade': 'media', 'bloqueante_sempre': False,
               'mensagem': 'Salário negativo'},
    'L':     {'min': 0.0, 'gravidade': 'media', 'bloqueante_sempre': False,
               'mensagem': 'Nível de emprego negativo'},
    'kstar': {'min': 0.0, 'gravidade': 'media', 'bloqueante_sempre': False,
               'mensagem': 'Capital por trabalhador negativo'},
    'pi':    {'min': None, 'gravidade': 'baixa', 'bloqueante_sempre': False,
               'mensagem': ''},  # deflação é possível — sem restrição
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

# Tolerância numérica para consistência estrutural
_EPSILON = 1e-6


# ─────────────────────────────────────────────────────────────────────────────
#  1. VARIABLE CLASSIFICATION LAYER
# ─────────────────────────────────────────────────────────────────────────────

def classificar_variaveis(equacoes: list, parametros: dict) -> dict:
    """
    Classifica todos os símbolos do sistema em endógenos e exógenos.

    Endógena : aparece no sistema e NÃO tem valor em parametros.
    Exógena  : tem valor explícito em parametros.
    Nunca assume valor 0 para símbolos não definidos.

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
#  2. EQUATION DEDUPLICATION LAYER
# ─────────────────────────────────────────────────────────────────────────────

def normalizar_sistema(equacoes: list) -> list[str]:
    """
    Remove duplicatas simbólicas e normaliza para 'lhs = rhs'.

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
#  3. ECONOMIC CONSTRAINT LAYER
# ─────────────────────────────────────────────────────────────────────────────

def validar_restricoes_economicas(solucao: dict, modo: str = "warning") -> ValidationResult:
    """
    Verifica restrições mínimas de viabilidade econômica contra _REGRAS_ECONOMICAS.

    bloqueante_sempre=True  → sempre vai para errors[] (bloqueia em qualquer modo)
    bloqueante_sempre=False → warnings[] em "warning"; errors[] em "fail_fast"

    Args:
        solucao: {variavel: valor} retornado pelo solver
        modo: "warning" | "fail_fast"

    Returns:
        ValidationResult — {valid, warnings, errors, violations}
        valid=False quando errors não vazio.
    """
    warnings_list: list[dict] = []
    errors_list:   list[dict] = []

    for var, val in solucao.items():
        if not isinstance(val, (int, float)):
            continue
        regra = _REGRAS_ECONOMICAS.get(var)
        if regra is None or regra['min'] is None:
            continue
        if val < regra['min']:
            is_blocking = regra['bloqueante_sempre'] or (modo == "fail_fast")
            item = {
                'variavel':  var,
                'tipo':      'violacao_economica',
                'gravidade': regra['gravidade'],
                'valor':     round(float(val), 6),
                'mensagem':  regra['mensagem'],
                'bloqueante': is_blocking,
            }
            if is_blocking:
                errors_list.append(item)
            else:
                warnings_list.append(item)

    all_violations = errors_list + warnings_list
    return {
        'valid':      len(errors_list) == 0,
        'warnings':   warnings_list,
        'errors':     errors_list,
        'violations': all_violations,
    }


# ─────────────────────────────────────────────────────────────────────────────
#  4. STRUCTURAL CONSISTENCY LAYER
# ─────────────────────────────────────────────────────────────────────────────

def validar_consistencia_estrutural(solucao: dict) -> list[dict]:
    """
    Verifica identidades contábeis conhecidas.

    Tolerância: _EPSILON = 1e-6.
    Só verifica quando TODAS as variáveis da identidade estão na solução.

    Returns:
        lista de {'identidade', 'lhs', 'rhs', 'diff', 'mensagem'}
    """
    erros: list[dict] = []
    vals = {k: float(v) for k, v in solucao.items() if isinstance(v, (int, float))}

    # Y = C + I + G  (demanda agregada fechada)
    if all(k in vals for k in ('Y', 'C', 'I', 'G')):
        esperado = vals['C'] + vals['I'] + vals['G']
        diff = abs(vals['Y'] - esperado)
        if diff > _EPSILON:
            erros.append({
                'identidade': 'Y = C + I + G',
                'lhs':        round(vals['Y'], 6),
                'rhs':        round(esperado, 6),
                'diff':       round(diff, 9),
                'mensagem':   f"Y({vals['Y']:.4g}) ≠ C+I+G({esperado:.4g}), diff={diff:.2e}",
            })

    # Qd = Qs  (equilíbrio microeconômico)
    if all(k in vals for k in ('Qd', 'Qs')):
        diff = abs(vals['Qd'] - vals['Qs'])
        if diff > _EPSILON:
            erros.append({
                'identidade': 'Qd = Qs',
                'lhs':        round(vals['Qd'], 6),
                'rhs':        round(vals['Qs'], 6),
                'diff':       round(diff, 9),
                'mensagem':   f"Qd({vals['Qd']:.4g}) ≠ Qs({vals['Qs']:.4g}), diff={diff:.2e}",
            })

    # Md = Ms  (equilíbrio monetário)
    if all(k in vals for k in ('Md', 'Ms')):
        diff = abs(vals['Md'] - vals['Ms'])
        if diff > _EPSILON:
            erros.append({
                'identidade': 'Md = Ms',
                'lhs':        round(vals['Md'], 6),
                'rhs':        round(vals['Ms'], 6),
                'diff':       round(diff, 9),
                'mensagem':   f"Md({vals['Md']:.4g}) ≠ Ms({vals['Ms']:.4g}), diff={diff:.2e}",
            })

    return erros


# ─────────────────────────────────────────────────────────────────────────────
#  5. SOLUTION VALIDATION LAYER (per-equation)
# ─────────────────────────────────────────────────────────────────────────────

def validar_solucao(equacoes: list, solucao: dict) -> list[str]:
    """
    Recalcula cada equação com a solução e verifica consistência numérica.
    Ignora equações com símbolos livres (solução simbólica parcial).

    Tolerância: 1e-6.

    Returns:
        lista de strings descrevendo inconsistências.
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
            if diff > _EPSILON:
                erros.append(
                    f"'{lhs} = {rhs}': "
                    f"LHS={lhs_val:.6g}, RHS={rhs_val:.6g} "
                    f"(diff={diff:.2e})"
                )
        except Exception:
            pass  # equação ainda tem símbolos livres — pula

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
        resolver_fn    : callable(params: dict) → dict[str, float | str]
        parametros_base: {'param': valor} do cenário base
        variacoes      : [{'nome': str, 'param': str, 'valor': float}, ...]

    Returns:
        {'base': {valores_base}, 'cenarios': [{nome, parametro_variado, valor, solucao, delta_vs_base}]}
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
            'nome':              var.get('nome') or f"{var['param']}={var['valor']}",
            'parametro_variado': var['param'],
            'valor':             var['valor'],
            'solucao':           sol,
            'delta_vs_base':     delta,
        })

    return {'base': base, 'cenarios': cenarios}


# ─────────────────────────────────────────────────────────────────────────────
#  PONTO ÚNICO DE ENTRADA — HARD GATE DO PIPELINE
# ─────────────────────────────────────────────────────────────────────────────

class EconomicValidationError(Exception):
    """
    Lançada em modo fail_fast quando a solução tem errors (violações bloqueantes).
    Carrega o ValidationResult completo para o endpoint formatar a resposta.
    """

    def __init__(self, result: dict):
        self.result: dict = result  # ValidationResult
        msgs = "; ".join(v["mensagem"] for v in result["errors"])
        super().__init__(f"Violação de restrição econômica: {msgs}")


def aplicar_validacao_economica(
    solucao: dict,
    modo: str | None = None,
) -> dict:
    """
    Hard gate obrigatório do pipeline econômico.

    Fluxo garantido:
        Solver → aplicar_validacao_economica → Formatter → Response

    Regras:
    - Não pode ser ignorado (ECONOMIC_VALIDATION_ENABLED=False é o único bypass)
    - Em "warning": retorna ValidationResult; valid=False é informacional
    - Em "fail_fast": lança EconomicValidationError se valid=False,
      impedindo o endpoint de retornar valores da solução

    Args:
        solucao: {variavel: valor} do solver
        modo: sobrescreve ECONOMIC_VALIDATION_MODE se fornecido

    Returns:
        ValidationResult — {valid, warnings, errors, violations}

    Raises:
        EconomicValidationError: em fail_fast com valid=False
    """
    from services.config import ECONOMIC_VALIDATION_ENABLED, ECONOMIC_VALIDATION_MODE
    if not ECONOMIC_VALIDATION_ENABLED:
        return {'valid': True, 'warnings': [], 'errors': [], 'violations': []}

    modo_efetivo = modo if modo is not None else ECONOMIC_VALIDATION_MODE
    result = validar_restricoes_economicas(solucao, modo_efetivo)

    if not result['valid'] and modo_efetivo == "fail_fast":
        raise EconomicValidationError(result)

    return result
