
# routers/modelo_proprio.py
"""
Laboratorio de Modelos Economicos.
Resolve modelos definidos pelo usuario com algebra simbolica (sympy).

Capacidades:
  1. Deteccao automatica de variaveis endogenas vs parametros
  2. Resolucao de sistemas de equacoes simultaneas
  3. Biblioteca de blocos economicos prontos
  4. Analise de sensibilidade (variar parametro -> ver efeito)
  5. Elasticidades / derivadas analiticas (dY/dG etc.)
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import sympy as sp
import numpy as np

from services.motor_sistemas import resolve_sistema as _resolver_sistema, _split_equacao
from services.validador import (
    classificar_variaveis,
    validar_solucao,
    validar_consistencia_estrutural,
    simular_cenario as _simular_cenario,
    EconomicValidationError,
    aplicar_validacao_economica,
    RESTRICOES_PADRAO,
)

router = APIRouter()


# =============================================================
#  MODELOS DE ENTRADA / SAIDA
# =============================================================
class Parametro(BaseModel):
    nome:  str
    valor: float
    descricao: str = ""


class Equacao(BaseModel):
    nome:      str = ""
    variavel:  str = ""          # opcional: lado esquerdo (ex "C"). Se vazio, inferido.
    expressao: str               # pode ser "C = a + c*(Y-T)" ou so o lado direito


class VariavelLivre(BaseModel):
    nome:   str
    min:    float = 0
    max:    float = 2000
    pontos: int   = 200
    mostrar: list[str] = []      # quais endogenas plotar (vazio = todas)


class ModeloInput(BaseModel):
    parametros:     list[Parametro]
    equacoes:       list[Equacao]
    variavel_livre: VariavelLivre | None = None
    # sensibilidade pode variar PARAMETROS (nao so a variavel livre)
    sensibilidades: list[VariavelLivre] = []


class VariacaoInput(BaseModel):
    nome:  str = ""
    param: str
    valor: float


class CenarioInput(BaseModel):
    equacoes:        list[Equacao]
    parametros_base: dict[str, float]
    variacoes:       list[VariacaoInput]


# =============================================================
#  HELPERS
# =============================================================
def _detectar(equacoes: list[Equacao], param_nomes: set[str]):
    """
    OBJETIVO 1: separa endogenas de parametros.
    Endogena = qualquer simbolo que aparece no lado ESQUERDO de uma equacao.
    Parametro = simbolo nas expressoes que nunca e lado esquerdo.
    Retorna (endogenas:set, lhs_list:list, todos_simbolos:set).
    """
    endogenas = set()
    lhs_list = []
    todos = set()

    for eq in equacoes:
        lhs, rhs = _split_equacao(eq)
        if not lhs or not rhs:
            continue
        # o lhs pode ser uma variavel simples (caso padrao)
        lhs_sym = sp.Symbol(lhs) if lhs.isidentifier() else None
        if lhs_sym is not None:
            endogenas.add(lhs)
        lhs_list.append((lhs, rhs))
        # coletar simbolos de ambos os lados
        try:
            for s in sp.sympify(rhs).free_symbols:
                todos.add(str(s))
        except Exception:
            pass
        if lhs.isidentifier():
            todos.add(lhs)

    return endogenas, lhs_list, todos


# =============================================================
#  OBJETIVO 3: BIBLIOTECA DE BLOCOS ECONOMICOS
# =============================================================
BLOCOS = {
    "consumo_keynesiano": {
        "nome": "Consumo Keynesiano",
        "equacao": {"variavel": "C", "expressao": "a + c*(Y - T)", "nome": "Consumo"},
        "parametros": [
            {"nome": "a", "valor": 100, "descricao": "Consumo autonomo"},
            {"nome": "c", "valor": 0.75, "descricao": "Propensao marginal a consumir"},
            {"nome": "T", "valor": 200, "descricao": "Impostos"},
        ],
    },
    "investimento": {
        "nome": "Investimento",
        "equacao": {"variavel": "I", "expressao": "I0", "nome": "Investimento"},
        "parametros": [{"nome": "I0", "valor": 200, "descricao": "Investimento autonomo"}],
    },
    "investimento_juro": {
        "nome": "Investimento sensivel ao juro",
        "equacao": {"variavel": "I", "expressao": "I0 - b*r", "nome": "Investimento"},
        "parametros": [
            {"nome": "I0", "valor": 200, "descricao": "Investimento autonomo"},
            {"nome": "b", "valor": 50, "descricao": "Sensibilidade ao juro"},
            {"nome": "r", "valor": 0.05, "descricao": "Taxa de juros"},
        ],
    },
    "governo": {
        "nome": "Governo",
        "equacao": {"variavel": "G", "expressao": "G0", "nome": "Gasto do governo"},
        "parametros": [{"nome": "G0", "valor": 300, "descricao": "Gastos do governo"}],
    },
    "exportacoes_liquidas": {
        "nome": "Exportacoes Liquidas",
        "equacao": {"variavel": "NX", "expressao": "X - M", "nome": "Exportacoes liquidas"},
        "parametros": [
            {"nome": "X", "valor": 150, "descricao": "Exportacoes"},
            {"nome": "M", "valor": 120, "descricao": "Importacoes"},
        ],
    },
    "produto": {
        "nome": "Produto (Demanda Agregada)",
        "equacao": {"variavel": "Y", "expressao": "C + I + G", "nome": "Produto"},
        "parametros": [],
    },
    "produto_aberto": {
        "nome": "Produto (Economia Aberta)",
        "equacao": {"variavel": "Y", "expressao": "C + I + G + NX", "nome": "Produto"},
        "parametros": [],
    },
    "demanda_moeda": {
        "nome": "Demanda por Moeda (LM)",
        "equacao": {"variavel": "Md", "expressao": "k*Y - h*r", "nome": "Demanda por moeda"},
        "parametros": [
            {"nome": "k", "valor": 0.5, "descricao": "Sensibilidade da demanda de moeda a renda"},
            {"nome": "h", "valor": 100, "descricao": "Sensibilidade da demanda de moeda ao juro"},
        ],
    },
    "solow_ss": {
        "nome": "Solow (Capital de Estado Estacionario)",
        "equacao": {"variavel": "kstar", "expressao": "(s/(n+delta))**(1/(1-alpha))", "nome": "Capital por trabalhador (SS)"},
        "parametros": [
            {"nome": "s", "valor": 0.2, "descricao": "Taxa de poupanca"},
            {"nome": "n", "valor": 0.02, "descricao": "Crescimento populacional"},
            {"nome": "delta", "valor": 0.1, "descricao": "Depreciacao"},
            {"nome": "alpha", "valor": 0.33, "descricao": "Participacao do capital"},
        ],
    },
}

# Modelos completos (conjuntos de blocos)
MODELOS_PRONTOS = {
    "cruz_keynesiana": {
        "nome": "Cruz Keynesiana",
        "descricao": "Modelo de renda de equilibrio com consumo, investimento e governo.",
        "blocos": ["consumo_keynesiano", "investimento", "governo", "produto"],
    },
    "economia_aberta": {
        "nome": "Economia Aberta",
        "descricao": "Cruz keynesiana com setor externo (exportacoes liquidas).",
        "blocos": ["consumo_keynesiano", "investimento", "governo", "exportacoes_liquidas", "produto_aberto"],
    },
}


@router.get("/blocos")
def listar_blocos():
    return {
        "blocos": [{"id": k, "nome": v["nome"]} for k, v in BLOCOS.items()],
        "modelos": [{"id": k, "nome": v["nome"], "descricao": v["descricao"], "blocos": v["blocos"]}
                    for k, v in MODELOS_PRONTOS.items()],
    }


@router.get("/blocos/{bloco_id}")
def obter_bloco(bloco_id: str):
    b = BLOCOS.get(bloco_id)
    if not b:
        raise HTTPException(404, "Bloco nao encontrado.")
    return b


@router.get("/modelos/{modelo_id}")
def obter_modelo_pronto(modelo_id: str):
    m = MODELOS_PRONTOS.get(modelo_id)
    if not m:
        raise HTTPException(404, "Modelo nao encontrado.")
    equacoes, parametros, vistos = [], [], set()
    for bid in m["blocos"]:
        b = BLOCOS[bid]
        equacoes.append(b["equacao"])
        for p in b["parametros"]:
            if p["nome"] not in vistos:
                parametros.append(p); vistos.add(p["nome"])
    return {"nome": m["nome"], "descricao": m["descricao"],
            "equacoes": equacoes, "parametros": parametros}


# =============================================================
#  ENDPOINT PRINCIPAL: RESOLVER
# =============================================================
@router.post("/resolver")
def resolver_modelo(modelo: ModeloInput) -> dict:
    erros: list[str] = []
    valores: dict[str, float] = {}
    series = None
    latex_map: dict[str, str] = {}
    dependencias: list[str] = []
    elasticidades: dict[str, dict] = {}

    valores_param = {p.nome: p.valor for p in modelo.parametros}
    param_nomes = set(valores_param.keys())

    # ── ETAPA 1: NORMALIZAÇÃO (antes de qualquer outro processamento) ────────
    # Deduplicar preservando objetos Equacao originais (não apenas strings)
    _vistas_canon: set[str] = set()
    equacoes_unicas: list[Equacao] = []
    for _eq in modelo.equacoes:
        _lhs, _rhs = _split_equacao(_eq)
        if not _lhs or not _rhs:
            continue
        try:
            _canon = str(sp.expand(sp.sympify(_lhs) - sp.sympify(_rhs)))
        except Exception:
            _canon = f"{_lhs}={_rhs}"
        if _canon not in _vistas_canon:
            _vistas_canon.add(_canon)
            equacoes_unicas.append(_eq)
    equacoes_norm = [f"{_split_equacao(e)[0].strip()} = {_split_equacao(e)[1].strip()}" for e in equacoes_unicas]

    # ── ETAPA 2: CLASSIFICAÇÃO DE VARIÁVEIS ──────────────────────────────────
    classificacao = classificar_variaveis(equacoes_unicas, valores_param)

    # ── ETAPA 3: LaTeX das equações de entrada ────────────────────────────────
    for eq in equacoes_unicas:
        lhs, rhs = _split_equacao(eq)
        try:
            latex_map[lhs or eq.nome] = f"{lhs} = {sp.latex(sp.sympify(rhs))}"
        except Exception:
            latex_map[lhs or eq.nome] = f"{lhs} = {rhs}"

    # ── ETAPA 4: DETECÇÃO DE ENDÓGENAS ───────────────────────────────────────
    endogenas, _, todos = _detectar(equacoes_unicas, param_nomes)
    endogenas_lhs = set(endogenas)
    param_detectados = todos - endogenas
    faltando = param_detectados - param_nomes
    if faltando:
        endogenas |= faltando
        param_detectados = todos - endogenas
    endogenas_ordered = sorted(endogenas_lhs) + sorted(faltando)

    # ── ETAPA 5: RESOLUÇÃO SIMBÓLICA/NUMÉRICA ────────────────────────────────
    sol_num, sol_sym, errs = _resolver_sistema(equacoes_unicas, valores_param, endogenas_ordered)
    erros += errs
    valores = sol_num
    sol_simbolica_str = {str(k): str(v) for k, v in sol_sym.items()} if sol_sym else {}

    if sol_sym:
        for var, expr in sol_sym.items():
            try:
                latex_map[f"sol_{var}"] = f"{var} = {sp.latex(expr)}"
            except Exception:
                latex_map[f"sol_{var}"] = f"{var} = {str(expr)}"

    # ── ETAPA 6: VALIDAÇÃO DA SOLUÇÃO (per-equation + structural) ────────────
    erros_consist      = validar_solucao(equacoes_unicas, valores)
    consist_estrutural = validar_consistencia_estrutural(valores)

    # ── ETAPA 7: VALIDAÇÃO ECONÔMICA — HARD GATE (não bypassável) ────────────
    # "warning" → retorna ValidationResult, nunca bloqueia execução
    # "fail_fast" → lança EconomicValidationError se valid=False:
    #               endpoint retorna invalid_solution SEM valores numéricos
    try:
        validation = aplicar_validacao_economica(valores)
    except EconomicValidationError as exc:
        return {
            "status":     "invalid_solution",
            "errors":     [v["mensagem"] for v in exc.result["errors"]],
            "violations": exc.result["violations"],
            "economia": {
                "valid":                  False,
                "warnings":               exc.result["warnings"],
                "errors":                 exc.result["errors"],
                "violations":             exc.result["violations"],
                "restricoes":             RESTRICOES_PADRAO,
                "consistencia":           erros_consist,
                "consistencia_estrutural": consist_estrutural,
                "interpretacao":          [],
            },
        }

    # ---- OBJ 5: elasticidades / derivadas analiticas ----
    # para cada endogena resolvida simbolicamente, dEndogena/dParametro
    if sol_sym:
        for endog, expr in sol_sym.items():
            nome_e = str(endog)
            derivs = {}
            for pnome in sorted(param_detectados):
                try:
                    d = sp.diff(expr, sp.Symbol(pnome))
                    d_val = float(d.subs({sp.Symbol(k): v for k, v in valores_param.items()}).evalf())
                    if abs(d_val) > 1e-9:
                        derivs[pnome] = round(d_val, 4)
                        # relacao qualitativa
                        seta = "↑" if d_val > 0 else "↓"
                        dependencias.append(f"↑ {pnome} → {seta} {nome_e}")
                except Exception:
                    pass
            if derivs:
                elasticidades[nome_e] = derivs

    # ---- OBJ 4: series (variavel livre OU sensibilidades) ----
    sensis = list(modelo.sensibilidades)
    if modelo.variavel_livre:
        sensis.append(modelo.variavel_livre)

    if sensis and sol_sym:
        series = {}
        for sl in sensis:
            grid = np.linspace(sl.min, sl.max, sl.pontos)
            chave_x = f"{sl.nome}"
            series[chave_x] = grid.tolist()
            # quais endogenas plotar
            alvos = sl.mostrar or [str(k) for k in sol_sym.keys()]
            for alvo in alvos:
                if alvo not in [str(k) for k in sol_sym.keys()]:
                    continue
                expr = sol_sym[sp.Symbol(alvo)]
                serie = []
                for x in grid:
                    subs = {sp.Symbol(k): v for k, v in valores_param.items()}
                    subs[sp.Symbol(sl.nome)] = x  # varia o parametro/variavel
                    try:
                        serie.append(float(expr.subs(subs).evalf()))
                    except Exception:
                        serie.append(None)
                series[f"{alvo}_vs_{sl.nome}"] = serie

    return {
        # ── Campos legados (compatibilidade com frontend) ─────────────────────
        "status": "ok" if not erros else "parcial",
        "valores": valores,
        "endogenas": sorted(endogenas),
        "parametros_detectados": sorted(param_detectados),
        "series": series,
        "erros": erros,
        "latex": latex_map,
        "dependencias": sorted(set(dependencias)),
        "elasticidades": elasticidades,
        # ── Bloco 1: Matemática ───────────────────────────────────────────────
        "matematica": {
            "equacoes_normalizadas": equacoes_norm,
            "variaveis": classificacao,
        },
        # ── Bloco 2: Solução estruturada ──────────────────────────────────────
        "solucao": {
            "numerica": valores,
            "simbolica": sol_simbolica_str,
        },
        # ── Bloco 3: Interpretação econômica ──────────────────────────────────
        "economia": {
            "valid":                   validation["valid"],
            "interpretacao":           sorted(set(dependencias)),
            "restricoes":              RESTRICOES_PADRAO,
            "warnings":                validation["warnings"],
            "errors":                  validation["errors"],
            "violations":              validation["violations"],
            "consistencia":            erros_consist,
            "consistencia_estrutural": consist_estrutural,
        },
    }


@router.post("/simular-cenario")
def simular_cenarios(payload: CenarioInput) -> dict:
    """
    Executa cenário base + variações e retorna comparativo.

    Body:
        equacoes       : lista de equações do modelo
        parametros_base: valores dos parâmetros no cenário base
        variacoes      : [{'nome': str, 'param': str, 'valor': float}]

    Returns:
        {'base': {valores}, 'cenarios': [{nome, param, valor, solucao, delta}]}
    """
    def _resolve(params: dict) -> dict:
        endogenas, _, todos = _detectar(payload.equacoes, set(params.keys()))
        endogenas_lhs = set(endogenas)
        param_detectados = todos - endogenas
        faltando = param_detectados - set(params.keys())
        if faltando:
            endogenas |= faltando
        endogenas_ordered = sorted(endogenas_lhs) + sorted(faltando)
        sol_num, _, _ = _resolver_sistema(payload.equacoes, params, endogenas_ordered)
        return {k: v for k, v in sol_num.items() if isinstance(v, (int, float))}

    return _simular_cenario(_resolve, payload.parametros_base, [v.model_dump() for v in payload.variacoes])


@router.post("/validar")
def validar_expressao(payload: dict) -> dict:
    expressao  = payload.get("expressao", "")
    parametros = payload.get("parametros", {})
    try:
        namespace = {k: sp.Symbol(k) for k in parametros}
        sp.sympify(expressao.split("=", 1)[-1], locals=namespace)
        return {"valido": True, "erro": None}
    except Exception as e:
        return {"valido": False, "erro": str(e)}