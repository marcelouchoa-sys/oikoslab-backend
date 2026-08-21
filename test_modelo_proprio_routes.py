"""
Testes de rota HTTP pra routers/modelo_proprio.py — router principal
("Ativo (principal)" no CLAUDE.md), estava em 0% de cobertura de rota
antes deste arquivo. services/economy_engine.py e
services/dependency_graph.py já tinham testes unitários próprios
(test_economy_engine_grafo.py, test_dependency_graph*.py) — aqui é a
camada HTTP (parsing de request, contrato de resposta, status code) que
nunca tinha sido exercitada.
"""
import pytest
from fastapi.testclient import TestClient

from main import app
import services.config as cfg

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_config():
    """services/config.py é estado global mutável compartilhado por todo o
    processo pytest — qualquer teste que mude ECONOMIC_VALIDATION_MODE/
    ENABLED precisa restaurar, senão vaza pros outros arquivos de teste
    rodando na mesma sessão."""
    enabled_original = cfg.ECONOMIC_VALIDATION_ENABLED
    modo_original = cfg.ECONOMIC_VALIDATION_MODE
    yield
    cfg.ECONOMIC_VALIDATION_ENABLED = enabled_original
    cfg.ECONOMIC_VALIDATION_MODE = modo_original


# ── GET /modelo/blocos ────────────────────────────────────────────────

def test_listar_blocos():
    res = client.get("/modelo/blocos")
    assert res.status_code == 200
    data = res.json()
    assert "blocos" in data and "modelos" in data
    assert "consumo_keynesiano" in {b["id"] for b in data["blocos"]}
    assert "cruz_keynesiana" in {m["id"] for m in data["modelos"]}


def test_obter_bloco_existente():
    res = client.get("/modelo/blocos/consumo_keynesiano")
    assert res.status_code == 200
    data = res.json()
    assert data["equacao"]["variavel"] == "C"
    assert any(p["nome"] == "c" for p in data["parametros"])


def test_obter_bloco_inexistente_404():
    res = client.get("/modelo/blocos/nao_existe")
    assert res.status_code == 404


# ── GET /modelo/modelos/{id} ──────────────────────────────────────────

def test_obter_modelo_pronto_cruz_keynesiana():
    res = client.get("/modelo/modelos/cruz_keynesiana")
    assert res.status_code == 200
    data = res.json()
    assert {e["variavel"] for e in data["equacoes"]} == {"C", "I", "G", "Y"}
    nomes_param = [p["nome"] for p in data["parametros"]]
    assert len(nomes_param) == len(set(nomes_param))  # dedup entre blocos


def test_obter_modelo_pronto_inexistente_404():
    res = client.get("/modelo/modelos/nao_existe")
    assert res.status_code == 404


# ── POST /modelo/resolver ─────────────────────────────────────────────

def test_resolver_cruz_keynesiana_multiplicador_canonico():
    """Caso canônico: multiplicador keynesiano dY/dG = 1/(1-c)."""
    payload = {
        "parametros": [
            {"nome": "a", "valor": 100},
            {"nome": "c", "valor": 0.75},
            {"nome": "T", "valor": 200},
            {"nome": "I0", "valor": 200},
            {"nome": "G0", "valor": 300},
        ],
        "equacoes": [
            {"nome": "Consumo",      "variavel": "C", "expressao": "a + c*(Y - T)"},
            {"nome": "Investimento", "variavel": "I", "expressao": "I0"},
            {"nome": "Governo",      "variavel": "G", "expressao": "G0"},
            {"nome": "Produto",      "variavel": "Y", "expressao": "C + I + G"},
        ],
    }
    res = client.post("/modelo/resolver", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["valores"]["Y"] > 0
    assert data["elasticidades"]["Y"]["G0"] == pytest.approx(1 / (1 - 0.75), rel=1e-3)


def test_resolver_parametro_string_formato_br_nao_infla_resultado_1000x():
    """Bug real relatado testando o projeto de Renda per capita de
    Seropédica: Pop = 80.596 (Censo 2022, formato BR -- ponto é milhar)
    chegando como STRING "80.596" era parseado por float() puro como
    80.596 (~80) em vez de 80596 -- Yp = PIB*1000/Pop saía ~1000x maior
    (46.653.382 em vez de 46.653,38), e o multiplicador dYp/dPop na mesma
    proporção errada (-578854.81 em vez de ~-0.58). NumeroBR
    (BeforeValidator em Parametro.valor, ver routers/modelo_proprio.py)
    corrige isso na borda HTTP, não só na ingestão do SIDRA."""
    payload = {
        "parametros": [
            {"nome": "PIB", "valor": 3760076},
            {"nome": "Pop", "valor": "80.596"},  # string BR -- o caso do bug
        ],
        "equacoes": [
            {"nome": "Renda per capita", "variavel": "Yp", "expressao": "(PIB * 1000) / Pop"},
        ],
    }
    res = client.post("/modelo/resolver", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["valores"]["Yp"] == pytest.approx(46653.38, rel=1e-3)
    assert data["elasticidades"]["Yp"]["Pop"] == pytest.approx(-0.5789, rel=1e-2)


def test_resolver_bloqueia_produto_negativo():
    payload = {
        "parametros": [
            {"nome": "a", "valor": -5000},
            {"nome": "c", "valor": 0.5},
            {"nome": "T", "valor": 0},
            {"nome": "I0", "valor": 0},
            {"nome": "G0", "valor": 0},
        ],
        "equacoes": [
            {"variavel": "C", "expressao": "a + c*(Y - T)"},
            {"variavel": "I", "expressao": "I0"},
            {"variavel": "G", "expressao": "G0"},
            {"variavel": "Y", "expressao": "C + I + G"},
        ],
    }
    res = client.post("/modelo/resolver", json=payload)
    assert res.status_code == 200  # hard gate formata resposta, nunca levanta erro HTTP
    assert res.json()["economia"]["valid"] is False


def test_resolver_equacoes_vazias():
    res = client.post("/modelo/resolver", json={"parametros": [], "equacoes": []})
    assert res.status_code == 200
    data = res.json()
    assert data["valores"] == {} or data["erros"]


def test_resolver_parametro_faltando_vira_endogena_extra():
    """Parâmetro referenciado na expressão mas não declarado em `parametros`
    é tratado como endógena adicional — comportamento documentado do
    Construtor (nunca exige cadastro prévio de Y, C etc)."""
    res = client.post("/modelo/resolver", json={
        "parametros": [],
        "equacoes": [{"variavel": "Y", "expressao": "C + 100"}],
    })
    assert res.status_code == 200
    data = res.json()
    assert "C" in data["endogenas"] or "C" in data["parametros_detectados"]


def test_resolver_expressao_invalida_nao_derruba_pipeline():
    res = client.post("/modelo/resolver", json={
        "parametros": [],
        "equacoes": [{"variavel": "Y", "expressao": "))) sintaxe quebrada((("}],
    })
    assert res.status_code == 200
    assert len(res.json()["erros"]) > 0


def test_resolver_multiplas_equacoes_iguais_deduplicadas():
    """Duas equações canonicamente idênticas (mesmo depois de reescritas)
    contam como uma só — EconomyEngine._parse dedup simbólico."""
    res = client.post("/modelo/resolver", json={
        "parametros": [],
        "equacoes": [
            {"variavel": "Y", "expressao": "10"},
            {"variavel": "Y", "expressao": "10"},
        ],
    })
    assert res.status_code == 200
    data = res.json()
    assert len(data["matematica"]["equacoes_normalizadas"]) == 1


# ── POST /modelo/simular-cenario ──────────────────────────────────────

def test_simular_cenario_parametros_base_string_formato_br_nao_infla():
    """Mesmo bug do PIB per capita (ver
    test_resolver_parametro_string_formato_br_nao_infla_resultado_1000x),
    exercitado em parametros_base (dict[str, NumeroBR]) -- garante que a
    correção cobre os DOIS endpoints que recebem valor de parâmetro, não
    só /resolver."""
    payload = {
        "equacoes": [{"variavel": "Yp", "expressao": "(PIB * 1000) / Pop"}],
        "parametros_base": {"PIB": 3760076, "Pop": "80.596"},
        "variacoes": [{"nome": "Pop maior", "param": "Pop", "valor": "90.000"}],
    }
    res = client.post("/modelo/simular-cenario", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["base"]["Yp"] == pytest.approx(46653.38, rel=1e-3)
    # variação também usa NumeroBR -- "90.000" tem que virar 90000, não 90
    assert data["cenarios"][0]["solucao"]["Yp"] == pytest.approx(3760076 * 1000 / 90000, rel=1e-3)


def test_simular_cenario_base_mais_variacoes():
    payload = {
        "equacoes": [
            {"variavel": "C", "expressao": "a + c*(Y - T)"},
            {"variavel": "I", "expressao": "I0"},
            {"variavel": "G", "expressao": "G0"},
            {"variavel": "Y", "expressao": "C + I + G"},
        ],
        "parametros_base": {"a": 100, "c": 0.75, "T": 200, "I0": 200, "G0": 300},
        "variacoes": [{"nome": "G maior", "param": "G0", "valor": 400}],
    }
    res = client.post("/modelo/simular-cenario", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert "base" in data and "cenarios" in data
    assert len(data["cenarios"]) == 1
    assert data["cenarios"][0]["solucao"]["Y"] > data["base"]["Y"]


def test_simular_cenario_sem_variacoes():
    payload = {
        "equacoes": [{"variavel": "Y", "expressao": "G0"}],
        "parametros_base": {"G0": 100},
        "variacoes": [],
    }
    res = client.post("/modelo/simular-cenario", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["cenarios"] == []
    assert data["base"]["Y"] == 100


def test_simular_cenario_base_valida_sinaliza_valido_true():
    """Base sem violação -- valido=True e violacoes vazio, tanto pra base
    quanto pro único cenário (sem nenhum choque forte)."""
    payload = {
        "equacoes": [
            {"variavel": "C", "expressao": "a + c*(Y - T)"},
            {"variavel": "I", "expressao": "I0"},
            {"variavel": "G", "expressao": "G0"},
            {"variavel": "Y", "expressao": "C + I + G"},
        ],
        "parametros_base": {"a": 100, "c": 0.75, "T": 200, "I0": 200, "G0": 300},
        "variacoes": [{"nome": "G um pouco maior", "param": "G0", "valor": 350}],
    }
    res = client.post("/modelo/simular-cenario", json=payload)
    data = res.json()
    assert data["base_valido"] is True
    assert data["base_violacoes"] == []
    assert data["cenarios"][0]["valido"] is True
    assert data["cenarios"][0]["violacoes"] == []


def test_simular_cenario_variacao_invalida_e_sinalizada_nao_fica_silenciosa():
    """Achado do levantamento de estado: EconomyEngine.resolve_single() já
    roda o hard gate por cenário, mas o router só extraía 'valores' —
    um cenário com Y<0 (regra bloqueante_sempre=True, ver validador.py)
    passava batido sem sinal nenhum de que violou restrição econômica.
    Agora 'valido'/'violacoes' vêm no cenário específico que quebrou,
    sem afetar o cenário base (que continua válido)."""
    payload = {
        "equacoes": [
            {"variavel": "C", "expressao": "a + c*(Y - T)"},
            {"variavel": "I", "expressao": "I0"},
            {"variavel": "G", "expressao": "G0"},
            {"variavel": "Y", "expressao": "C + I + G"},
        ],
        "parametros_base": {"a": 100, "c": 0.75, "T": 200, "I0": 200, "G0": 300},
        "variacoes": [
            # 'a' extremamente negativo derruba Y pra negativo -- bloqueante
            # sempre (Y é regra bloqueante_sempre=True em validador.py,
            # dispara mesmo no modo "warning" default).
            {"nome": "Choque catastrófico", "param": "a", "valor": -100000},
        ],
    }
    res = client.post("/modelo/simular-cenario", json=payload)
    assert res.status_code == 200
    data = res.json()

    assert data["base_valido"] is True  # base continua ok, só o cenário quebrou

    cenario = data["cenarios"][0]
    assert cenario["valido"] is False
    assert len(cenario["violacoes"]) > 0
    assert any("Produto negativo" in v["mensagem"] or "negativo" in v["mensagem"].lower() for v in cenario["violacoes"])


def test_anexar_diagnosticos_cenario_invalido_sem_violacoes_no_payload():
    """Bug reportado ao testar Cenários na UI: um cenário chegou no
    frontend com valido=False mas violacoes=undefined, quebrando
    cen.violacoes.map() em construtor/page.tsx. A causa suspeita era o
    zip() de _anexar_diagnosticos truncar silenciosamente se
    `diagnosticos` viesse mais curto que `resultado['cenarios']` --
    cenários sobrando ficariam sem as chaves valido/violacoes de jeito
    nenhum (nem [] vazio). Simula esse descompasso diretamente (2
    cenários, só 1 diagnóstico de variação) e também um diagnóstico com
    violations=None (payload corrompido) -- em ambos os casos, todo
    cenário tem que sair com violacoes como list, nunca None/ausente."""
    from routers.modelo_proprio import _anexar_diagnosticos

    resultado = {
        "base": {"Y": 1400},
        "cenarios": [
            {"nome": "cenario 1", "solucao": {"Y": 1500}},
            {"nome": "cenario 2 (sem diagnostico correspondente)", "solucao": {"Y": -50}},
        ],
    }
    diagnosticos = [
        {"valid": True, "violations": []},   # base
        {"valid": True, "violations": []},   # cenario 1 -- falta o da cenario 2
    ]

    out = _anexar_diagnosticos(resultado, diagnosticos)

    assert out["cenarios"][0]["valido"] is True
    assert out["cenarios"][0]["violacoes"] == []
    # cenario 2 não tem diagnóstico -- tratado como inválido (seguro), mas
    # violacoes SEMPRE list, nunca None/ausente (isso é o que evita o
    # crash do .map() no frontend)
    assert out["cenarios"][1]["valido"] is False
    assert out["cenarios"][1]["violacoes"] == []
    assert isinstance(out["cenarios"][1]["violacoes"], list)


def test_anexar_diagnosticos_violations_none_vira_lista_vazia():
    """Payload corrompido (violations=None em vez de []) não deve vazar
    None pro JSON de resposta -- sempre normalizado pra lista."""
    from routers.modelo_proprio import _anexar_diagnosticos

    resultado = {"base": {}, "cenarios": [{"nome": "x", "solucao": {}}]}
    diagnosticos = [
        {"valid": False, "violations": None},  # base corrompida
        {"valid": False, "violations": None},  # cenario corrompido
    ]

    out = _anexar_diagnosticos(resultado, diagnosticos)

    assert out["base_violacoes"] == []
    assert out["cenarios"][0]["violacoes"] == []


# ── POST /modelo/validar ──────────────────────────────────────────────

def test_validar_expressao_valida():
    res = client.post("/modelo/validar", json={"expressao": "a + b*Y", "parametros": {"a": 1, "b": 2}})
    assert res.status_code == 200
    assert res.json() == {"valido": True, "erro": None}


def test_validar_expressao_invalida():
    res = client.post("/modelo/validar", json={"expressao": "((( quebrado", "parametros": {}})
    assert res.status_code == 200
    data = res.json()
    assert data["valido"] is False
    assert data["erro"]


def test_validar_sem_parametros_no_body():
    """payload é dict solto (não Pydantic model) — 'parametros' ausente
    precisa usar o default {} sem levantar KeyError."""
    res = client.post("/modelo/validar", json={"expressao": "2 + 2"})
    assert res.status_code == 200
    assert res.json()["valido"] is True


# ── POST /modelo/grafo ────────────────────────────────────────────────

def test_grafo_rota_sem_ciclo():
    payload = {
        "funcoes": [
            {"funcao_id": "a", "funcao_versao_id": "va", "nome": "A", "depende_de": []},
            {"funcao_id": "b", "funcao_versao_id": "vb", "nome": "B", "depende_de": ["a"]},
        ]
    }
    res = client.post("/modelo/grafo", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["valido"] is True
    assert data["ordem_calculo"].index("va") < data["ordem_calculo"].index("vb")


def test_grafo_rota_ciclo_2_nos():
    payload = {
        "funcoes": [
            {"funcao_id": "a", "funcao_versao_id": "va", "nome": "A", "depende_de": ["b"]},
            {"funcao_id": "b", "funcao_versao_id": "vb", "nome": "B", "depende_de": ["a"]},
        ]
    }
    res = client.post("/modelo/grafo", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["valido"] is False
    assert "A" in data["motivo"] and "B" in data["motivo"]


def test_grafo_rota_ciclo_3_nos():
    payload = {
        "funcoes": [
            {"funcao_id": "a", "funcao_versao_id": "va", "nome": "A", "depende_de": ["c"]},
            {"funcao_id": "b", "funcao_versao_id": "vb", "nome": "B", "depende_de": ["a"]},
            {"funcao_id": "c", "funcao_versao_id": "vc", "nome": "C", "depende_de": ["b"]},
        ]
    }
    res = client.post("/modelo/grafo", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["valido"] is False
    assert len(data["ciclos"]) == 1
    assert len(data["ciclos"][0]) == 3


def test_grafo_rota_dependencia_nao_resolvida():
    payload = {
        "funcoes": [
            {"funcao_id": "a", "funcao_versao_id": "va", "nome": "A", "depende_de": ["fantasma"]},
        ]
    }
    res = client.post("/modelo/grafo", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["valido"] is False
    assert "fantasma" in data["motivo"]


def test_grafo_rota_lista_vazia():
    res = client.post("/modelo/grafo", json={"funcoes": []})
    assert res.status_code == 200
    data = res.json()
    assert data["valido"] is True
    assert data["ordem_calculo"] == []


# ── Validação de contrato Pydantic (erros 422) ────────────────────────

def test_resolver_sem_campo_obrigatorio_422():
    res = client.post("/modelo/resolver", json={"parametros": []})  # falta 'equacoes'
    assert res.status_code == 422


def test_grafo_sem_campo_obrigatorio_422():
    res = client.post("/modelo/grafo", json={})  # falta 'funcoes'
    assert res.status_code == 422
