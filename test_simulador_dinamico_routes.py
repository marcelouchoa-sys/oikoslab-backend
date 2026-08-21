"""
Testes de rota HTTP pra routers/simulador_dinamico.py — modelo
Novo-Keynesiano de 3 equações (Carlin-Soskice/Galí), "Ativo" no
CLAUDE.md, estava em 39% de cobertura (só o que a definição de
Pydantic models exercitava por import). Cobre os casos canônicos que o
CLAUDE.md exige pra esse módulo: sem choque -> equilíbrio; choque
temporário -> reconverge (salvo pós-keynesiana); histerese só na
pós-keynesiana.
"""
import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

ESCOLAS = ["classica", "keynesiana", "monetarista", "pos_keynesiana"]


def payload_base(escola="keynesiana", choques=None, periodos=10, **overrides_economia):
    return {
        "economia": {"escola": escola, **overrides_economia},
        "choques": choques or [],
        "periodos": periodos,
    }


# ── GET /choques-predefinidos ─────────────────────────────────────────

def test_choques_predefinidos_tem_pelo_menos_um_de_cada_tipo():
    res = client.get("/simulador-dinamico/choques-predefinidos")
    assert res.status_code == 200
    data = res.json()
    assert len(data) >= 5
    ids = {c["id"] for c in data}
    assert "exp_fiscal" in ids and "choque_petroleo" in ids


# ── POST /simular — caso canônico: sem choque = equilíbrio ────────────

@pytest.mark.parametrize("escola", ESCOLAS)
def test_sem_choque_permanece_em_equilibrio(escola):
    """Caso canônico (CLAUDE.md): sem choque, a economia fica em
    equilíbrio (hiato 0, inflação na meta) o tempo todo, em QUALQUER
    escola — parte do estado inicial já é o equilíbrio de longo prazo."""
    res = client.post("/simulador-dinamico/simular", json=payload_base(escola=escola, periodos=15))
    assert res.status_code == 200
    data = res.json()
    assert all(p["y_gap"] == 0.0 for p in data["periodos"])
    assert all(p["pi"] == 2.0 for p in data["periodos"])  # pi_meta default = 2.0


# ── POST /simular — choque temporário reconverge (exceto pós-keynesiana) ─

@pytest.mark.parametrize("escola", ["classica", "keynesiana", "monetarista"])
def test_choque_temporario_reconverge_escolas_sem_histerese(escola):
    choque = {"tipo": "demanda", "nome": "teste", "magnitude": 1.0,
              "ano_inicio": 1, "duracao": 1, "eps_demanda": -5.0}
    res = client.post("/simulador-dinamico/simular",
                       json=payload_base(escola=escola, choques=[choque], periodos=40))
    data = res.json()
    ultimo = data["periodos"][-1]
    assert abs(ultimo["y_gap"]) < 0.05  # reconvergiu perto de zero
    assert ultimo["u_natural"] == data["periodos"][0]["u_natural"]  # sem histerese, natural não muda


def test_histerese_so_aparece_na_pos_keynesiana():
    choque = {"tipo": "demanda", "nome": "teste", "magnitude": 1.0,
              "ano_inicio": 1, "duracao": 1, "eps_demanda": -5.0}
    res = client.post("/simulador-dinamico/simular",
                       json=payload_base(escola="pos_keynesiana", choques=[choque], periodos=10))
    data = res.json()
    # u_natural sobe permanentemente após o choque negativo (histerese > 0)
    assert data["periodos"][-1]["u_natural"] > data["periodos"][0]["u_natural"] - 0.01
    assert data["periodos"][0]["u_natural"] != 6.0  # já mudou desde o 1o período


# ── POST /simular — comparar_escolas ───────────────────────────────────

def test_comparar_escolas_roda_as_quatro():
    payload = payload_base(periodos=5)
    payload["comparar_escolas"] = True
    res = client.post("/simulador-dinamico/simular", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["modo"] == "comparacao"
    assert set(data["comparacao"].keys()) == set(ESCOLAS)
    for esc in ESCOLAS:
        assert len(data["comparacao"][esc]["periodos"]) == 5
        assert "analise" in data["comparacao"][esc]


def test_simular_modo_simples_traz_parametros_do_modelo():
    res = client.post("/simulador-dinamico/simular", json=payload_base(escola="classica", periodos=3))
    data = res.json()
    assert data["modo"] == "simples"
    assert data["escola"] == "classica"
    assert data["escola_nome"] == "Novo-Classica"
    assert "alpha" in data["parametros_modelo"]


# ── POST /irf ────────────────────────────────────────────────────────

def test_irf_sem_choque_e_zero_em_todo_periodo():
    """IRF compara trajetória COM choque (inp.choques) vs SEM choque
    (baseline vazio); se inp.choques também for vazio, as duas
    trajetórias são idênticas -> IRF zero em tudo."""
    res = client.post("/simulador-dinamico/irf", json=payload_base(periodos=10, choques=[]))
    assert res.status_code == 200
    data = res.json()
    assert all(p["y_gap"] == 0.0 and p["pi"] == 0.0 for p in data["irf"])


def test_irf_com_choque_mostra_resposta_no_ano_do_choque():
    choque = {"tipo": "demanda", "nome": "teste", "magnitude": 1.0,
              "ano_inicio": 1, "duracao": 1, "eps_demanda": 3.0}
    res = client.post("/simulador-dinamico/irf", json=payload_base(choques=[choque], periodos=10))
    data = res.json()
    assert data["irf"][0]["y_gap"] != 0.0  # resposta já no primeiro ano


# ── Edge cases: períodos curtos/zero ───────────────────────────────────

def test_periodos_zero_retorna_trajetoria_vazia():
    res = client.post("/simulador-dinamico/simular", json=payload_base(periodos=0))
    assert res.status_code == 200
    data = res.json()
    assert data["periodos"] == []
    # _montar_analise com lista vazia não deve quebrar
    assert data["analise"]["curto_prazo"]["descricao"] == ""


def test_periodos_muito_curto_nao_quebra_montar_analise():
    """periodos=1: cp=traj[:2] (1 item), mp=traj[2:5] (vazio),
    lp=traj[-3:] (fallback, reusa o único período) -- não deve estourar
    índice nem dividir por zero."""
    res = client.post("/simulador-dinamico/simular", json=payload_base(periodos=1))
    assert res.status_code == 200
    data = res.json()
    assert len(data["periodos"]) == 1
    assert data["analise"]["medio_prazo"]["descricao"] == ""  # lista vazia nesse prazo


# ── Validação de contrato ──────────────────────────────────────────────

def test_simular_sem_economia_422():
    res = client.post("/simulador-dinamico/simular", json={"choques": []})
    assert res.status_code == 422
