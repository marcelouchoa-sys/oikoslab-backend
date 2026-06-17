
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

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import sympy as sp

from services.validador import simular_cenario as _simular_cenario
from services.economy_engine import EconomyEngine

router = APIRouter()


# =============================================================
#  MODELOS DE ENTRADA
# =============================================================

class Parametro(BaseModel):
    nome:      str
    valor:     float
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
    valor: float


class CenarioInput(BaseModel):
    equacoes:        list[Equacao]
    parametros_base: dict[str, float]
    variacoes:       list[VariacaoInput]


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
        return EconomyEngine.resolve_single(payload.equacoes, params)['valores']

    return _simular_cenario(
        _resolve,
        payload.parametros_base,
        [v.model_dump() for v in payload.variacoes],
    )


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
