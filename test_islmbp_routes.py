"""Testes de rota HTTP pra routers/islmbp.py (legado, mas ainda ativo —
mantido por compatibilidade). Rotas eram 0% cobertas; a lógica em si já
é testada via services/economy_engine.py (test_economy_engine_edge_cases.py
cobre run_islm/run_islm_curvas diretamente) — aqui só a camada HTTP."""
import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_equilibrio_com_defaults():
    res = client.post("/islmbp/equilibrio", json={})
    assert res.status_code == 200
    data = res.json()
    assert "equilibrio" in data
    assert data["equilibrio"]["Y"] is not None


def test_equilibrio_economia_aberta():
    """kf=1e6 -> mobilidade perfeita (Mundell-Fleming): r = r_star fixo
    (default r_star=0.03 em ParametrosISLM)."""
    res = client.post("/islmbp/equilibrio", json={"aberta": True, "kf": 1e6})
    assert res.status_code == 200
    assert res.json()["equilibrio"]["r"] == pytest.approx(0.03)


def test_curvas_gera_grades():
    res = client.post("/islmbp/curvas", json={})
    assert res.status_code == 200
    data = res.json()
    assert len(data["Y_grid"]) == 200
    assert len(data["r_IS"]) == 200
    assert len(data["r_LM"]) == 200
