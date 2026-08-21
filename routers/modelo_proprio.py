
# routers/modelo_proprio.py
"""
Adaptador HTTP para o laboratório de modelos econômicos do OikosLab.

Responsabilidades deste arquivo:
  - Definir contratos HTTP (request/response models Pydantic)
  - Rotear requisições para EconomyEngine (único processador)
  - Gerir biblioteca de blocos pré-configurados

Toda lógica de resolução, validação e formatação vive em EconomyEngine.
Nenhuma chamada direta ao solver é feita aqui.
"""

from typing import Annotated

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, BeforeValidator
import sympy as sp

from services.validador import simular_cenario as _simular_cenario
from services.economy_engine import EconomyEngine
from services.parse_numero import parse_numero_br
from services.dependency_graph import (
    resolver_grafo_versionado,
    ordenar_topologicamente,
    DependenciaNaoResolvidaError,
)

router = APIRouter()


def _converter_se_string(v):
    """BeforeValidator: só strings passam por parse_numero_br (formato BR
    -- ponto pode ser milhar, vírgula é decimal); número já vem inequívoco
    do JSON e passa direto. Defesa em profundidade: o frontend hoje já
    manda `valor` como número (nunca string) pra estes campos, mas um
    valor de parâmetro é exatamente o tipo de dado que já vazou como
    string BR-formatada uma vez (bug real: "80.596" virando 80.596 em vez
    de 80596) -- essa validação garante que, mesmo se algo no futuro
    (frontend, script, chamada direta à API) mandar string aqui de novo,
    o parse é seguro."""
    return parse_numero_br(v) if isinstance(v, str) else v


NumeroBR = Annotated[float, BeforeValidator(_converter_se_string)]


# =============================================================
#  MODELOS DE ENTRADA
# =============================================================

class Parametro(BaseModel):
    nome:      str
    valor:     NumeroBR
    descricao: str = ""


class Equacao(BaseModel):
    nome:      str = ""
    variavel:  str = ""      # lado esquerdo explícito (ex: "C"); inferido se vazio
    expressao: str           # "C = a + c*(Y-T)"  ou apenas o lado direito


class VariavelLivre(BaseModel):
    nome:    str
    min:     float     = 0
    max:     float     = 2000
    pontos:  int       = 200
    mostrar: list[str] = []  # quais endógenas plotar (vazio = todas)


class ModeloInput(BaseModel):
    parametros:     list[Parametro]
    equacoes:       list[Equacao]
    variavel_livre: VariavelLivre | None  = None
    sensibilidades: list[VariavelLivre]  = []


class VariacaoInput(BaseModel):
    nome:  str = ""
    param: str
    valor: NumeroBR


class CenarioInput(BaseModel):
    equacoes:        list[Equacao]
    parametros_base: dict[str, NumeroBR]
    variacoes:       list[VariacaoInput]


class FuncaoGrafoInput(BaseModel):
    """
    Um nó do grafo de dependências de uma modelo_versao específica — ver
    services/dependency_graph.py:resolver_grafo_versionado (porte
    versionado de frontend/lib/dependency-graph.ts).

    `funcao_id` é a identidade estável da Funcao — é o que `depende_de`
    referencia, tanto aqui quanto na coluna `depende_de` do banco (uma
    expressão referencia "a função Preço", nunca uma versão específica
    dela). `funcao_versao_id` é a versão EXATA pinada nesta modelo_versao
    (nunca "a atual" — ver modelo_versao_funcoes em
    0002_modelos_versionamento.sql); é ela que vira nó do grafo.

    O backend não tem client Supabase configurado hoje, então este
    endpoint não resolve `modelo_versao_id` sozinho: quem chama (frontend,
    que já tem acesso ao Supabase) busca modelo_versao_funcoes +
    funcao_versoes e manda a lista completa aqui — mesmo padrão que
    /resolver já usa (equações inteiras no payload, sem lookup por id no
    servidor).
    """
    funcao_id:        str
    funcao_versao_id: str
    nome:             str = ""
    variavel:         str = ""
    variaveis_usadas: list[str] = []
    depende_de:       list[str] = []


class GrafoInput(BaseModel):
    modelo_versao_id: str | None = None
    funcoes:          list[FuncaoGrafoInput]


# =============================================================
#  BIBLIOTECA DE BLOCOS ECONÔMICOS
# =============================================================

BLOCOS = {
    "consumo_keynesiano": {
        "nome": "Consumo Keynesiano",
        "equacao": {"variavel": "C", "expressao": "a + c*(Y - T)", "nome": "Consumo"},
        "parametros": [
            {"nome": "a", "valor": 100,  "descricao": "Consumo autonomo"},
            {"nome": "c", "valor": 0.75, "descricao": "Propensao marginal a consumir"},
            {"nome": "T", "valor": 200,  "descricao": "Impostos"},
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
            {"nome": "I0", "valor": 200,  "descricao": "Investimento autonomo"},
            {"nome": "b",  "valor": 50,   "descricao": "Sensibilidade ao juro"},
            {"nome": "r",  "valor": 0.05, "descricao": "Taxa de juros"},
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
        "equacao": {
            "variavel":  "kstar",
            "expressao": "(s/(n+delta))**(1/(1-alpha))",
            "nome":      "Capital por trabalhador (SS)",
        },
        "parametros": [
            {"nome": "s",     "valor": 0.2,  "descricao": "Taxa de poupanca"},
            {"nome": "n",     "valor": 0.02, "descricao": "Crescimento populacional"},
            {"nome": "delta", "valor": 0.1,  "descricao": "Depreciacao"},
            {"nome": "alpha", "valor": 0.33, "descricao": "Participacao do capital"},
        ],
    },
}

MODELOS_PRONTOS = {
    "cruz_keynesiana": {
        "nome":    "Cruz Keynesiana",
        "descricao": "Modelo de renda de equilibrio com consumo, investimento e governo.",
        "blocos":  ["consumo_keynesiano", "investimento", "governo", "produto"],
    },
    "economia_aberta": {
        "nome":    "Economia Aberta",
        "descricao": "Cruz keynesiana com setor externo (exportacoes liquidas).",
        "blocos":  ["consumo_keynesiano", "investimento", "governo", "exportacoes_liquidas", "produto_aberto"],
    },
}


# =============================================================
#  ENDPOINTS DE CONSULTA (biblioteca)
# =============================================================

@router.get("/blocos")
def listar_blocos():
    return {
        "blocos":  [{"id": k, "nome": v["nome"]} for k, v in BLOCOS.items()],
        "modelos": [
            {"id": k, "nome": v["nome"], "descricao": v["descricao"], "blocos": v["blocos"]}
            for k, v in MODELOS_PRONTOS.items()
        ],
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
                parametros.append(p)
                vistos.add(p["nome"])
    return {"nome": m["nome"], "descricao": m["descricao"],
            "equacoes": equacoes, "parametros": parametros}


# =============================================================
#  ENDPOINT PRINCIPAL: RESOLVER
#  Todo o pipeline passa por EconomyEngine.run() — sem bypass.
# =============================================================

@router.post("/resolver")
def resolver_modelo(modelo: ModeloInput) -> dict:
    return EconomyEngine.run(
        equacoes=modelo.equacoes,
        parametros={p.nome: p.valor for p in modelo.parametros},
        variavel_livre=modelo.variavel_livre,
        sensibilidades=modelo.sensibilidades,
    )


# =============================================================
#  SIMULAÇÃO DE CENÁRIOS
#  Usa EconomyEngine.resolve_single() — solver sempre gateado.
# =============================================================

def _anexar_diagnosticos(resultado: dict, diagnosticos: list[dict]) -> dict:
    """
    Anexa valido/violacoes a `resultado` (saída de `_simular_cenario`) a
    partir de `diagnosticos` — um item por chamada de `_resolve`, na mesma
    ordem: base primeiro, depois cada variação.

    Isolada como função própria (em vez de zip() inline no endpoint) e
    indexada com fallback explícito: zip() trunca silenciosamente se as
    duas listas tiverem tamanhos diferentes, o que deixaria cenários no
    fim da lista sem as chaves valido/violacoes — e `violacoes` ausente
    (não `[]`) quebra `cen.violacoes.map()` no frontend
    (construtor/page.tsx). Contrato garantido aqui: TODO cenário sempre
    sai com `valido: bool` e `violacoes: list` (nunca None/ausente), e um
    diagnóstico faltando é tratado como inválido (mais seguro do que
    assumir válido silenciosamente).
    """
    diag_base = diagnosticos[0] if diagnosticos else {"valid": False, "violations": []}
    resultado["base_valido"] = diag_base["valid"]
    resultado["base_violacoes"] = diag_base["violations"] or []

    diagnosticos_variacoes = diagnosticos[1:]
    for i, cenario in enumerate(resultado["cenarios"]):
        diagnostico = diagnosticos_variacoes[i] if i < len(diagnosticos_variacoes) else None
        cenario["valido"] = diagnostico["valid"] if diagnostico else False
        cenario["violacoes"] = (diagnostico["violations"] if diagnostico else None) or []

    return resultado


@router.post("/simular-cenario")
def simular_cenarios(payload: CenarioInput) -> dict:
    """
    Executa cenário base + variações e retorna comparativo.

    Body:
        equacoes       : lista de equações do modelo
        parametros_base: valores dos parâmetros no cenário base
        variacoes      : [{'nome': str, 'param': str, 'valor': float}]

    Returns:
        {
          'base': {valores}, 'base_valido': bool, 'base_violacoes': [...],
          'cenarios': [{nome, parametro_variado, valor, solucao, delta_vs_base,
                        valido, violacoes}],
        }

    `valido`/`violacoes` são novos (aditivo — `base`/`solucao` continuam no
    mesmo formato de sempre, dict achatado {variavel: valor}). Antes desse
    campo, `EconomyEngine.resolve_single()` já rodava o hard gate
    internamente pra cada cenário, mas só `valores` chegava até aqui —
    `valid`/`violations` eram descartados, então um cenário economicamente
    inválido aparecia silencioso: no modo padrão (warning) com números
    que violam restrição mas parecem normais; no modo fail_fast com
    `solucao` vazio sem explicação nenhuma. Capturado aqui via closure
    (mesma ordem de chamada de `_resolve`: base primeiro, depois cada
    variação, na ordem de `payload.variacoes`) — sem duplicar a lógica de
    validação, que já mora inteira no EconomyEngine. Ver
    `_anexar_diagnosticos` para a garantia de que violacoes nunca vem
    ausente/null no JSON de resposta.
    """
    diagnosticos: list[dict] = []

    def _resolve(params: dict) -> dict:
        resultado = EconomyEngine.resolve_single(payload.equacoes, params)
        diagnosticos.append({"valid": resultado["valid"], "violations": resultado["violations"]})
        return resultado["valores"]

    resultado = _simular_cenario(
        _resolve,
        payload.parametros_base,
        [v.model_dump() for v in payload.variacoes],
    )

    return _anexar_diagnosticos(resultado, diagnosticos)


# =============================================================
#  VALIDAÇÃO SINTÁTICA DE EXPRESSÕES
# =============================================================

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


# =============================================================
#  GRAFO DE DEPENDÊNCIAS ENTRE FUNCAO
#  Porte de frontend/lib/dependency-graph.ts — ver services/dependency_graph.py.
# =============================================================

@router.post("/grafo")
def calcular_grafo(payload: GrafoInput) -> dict:
    """
    Ordena topologicamente as `Funcao` de uma modelo_versao e detecta
    ciclos de dependência (`depende_de` apontando, direta ou
    indiretamente, de volta pra si mesma). O grafo opera sobre
    `funcao_versao_id` — a versão exata pinada nesta modelo_versao, não
    "a função" em geral — resolvida a partir de `depende_de` (que
    referencia `funcao_id`) via resolver_grafo_versionado.

    Resposta sempre 200 — ciclo NÃO é erro HTTP, é um resultado válido do
    diagnóstico (mesmo espírito do EconomicHardGate: nunca uma falha
    genérica, sempre um diagnóstico estruturado). `valido=False` é o sinal
    de bloqueio; quem chama decide o que fazer (não resolve o modelo, etc).
    Uma dependência não resolvida (funcao_id ausente do payload — snapshot
    incompleto) também vira `valido=False` em vez de erro HTTP, pelo mesmo
    motivo.
    """
    try:
        grafo = resolver_grafo_versionado(payload.funcoes)
    except DependenciaNaoResolvidaError as exc:
        return {
            "ordem_calculo": [],
            "ciclos":        [],
            "ciclos_nomes":  [],
            "valido":        False,
            "motivo":        str(exc),
        }

    ordem, ciclos = ordenar_topologicamente(grafo)

    nomes = {f.funcao_versao_id: (f.nome or f.funcao_versao_id) for f in payload.funcoes}
    ciclos_nomeados = [[nomes.get(cid, cid) for cid in ciclo] for ciclo in ciclos]

    valido = len(ciclos) == 0
    motivo = None
    if not valido:
        motivo = "; ".join(
            "Dependência circular: " + " → ".join(nomeado + [nomeado[0]])
            for nomeado in ciclos_nomeados
        )

    return {
        "ordem_calculo": ordem,
        "ciclos":        ciclos,
        "ciclos_nomes":  ciclos_nomeados,
        "valido":        valido,
        "motivo":        motivo,
    }
