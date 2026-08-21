"""Testes de rota HTTP pra routers/exemplos_didaticos.py — calculadoras
didáticas simples (consumo/investimento), sem relação com EconomyEngine."""
import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_consumo_com_defaults():
    res = client.post("/exemplos-didaticos/consumo", json={})
    assert res.status_code == 200
    data = res.json()
    assert len(data["Y"]) == 200
    assert len(data["C"]) == 200
    assert data["multiplicador"] == pytest.approx(1 / (1 - 0.75))
    # C = c0 + c1*Y no primeiro ponto (Y=Y_min=0)
    assert data["C"][0] == pytest.approx(data["c0"])


def test_investimento_com_defaults():
    res = client.post("/exemplos-didaticos/investimento", json={})
    assert res.status_code == 200
    data = res.json()
    assert len(data["r"]) == 200
    assert len(data["I"]) == 200


def test_investimento_nunca_fica_negativo():
    """I = max(0, I0 - b*r) -- clampa em zero, nunca deveria virar negativo
    mesmo com r alto o suficiente pra zerar o investimento."""
    res = client.post("/exemplos-didaticos/investimento", json={"I0": 100, "b": 50, "r_min": 0, "r_max": 20})
    data = res.json()
    assert min(data["I"]) == 0.0
    assert all(v >= 0 for v in data["I"])
