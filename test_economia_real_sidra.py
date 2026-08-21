"""
Testes do Data Hub v1 — busca de série SIDRA (routers/economia_real.py).

Sem pytest-asyncio no projeto: as funções async são testadas com
asyncio.run() em testes síncronos comuns, mesmo padrão que o resto da
suíte já usa (sem dependência nova).
"""
import asyncio

import pytest
from fastapi import HTTPException

from routers.economia_real import _parse_valor_sidra, buscar_sidra
import routers.economia_real as economia_real_mod


# ── _parse_valor_sidra — pura, sem rede ──────────────────────────────

def test_parse_valor_numerico_simples():
    assert _parse_valor_sidra("5.4") == 5.4


def test_parse_valor_com_virgula_decimal():
    assert _parse_valor_sidra("5,4") == 5.4


@pytest.mark.parametrize("marcador", ["-", "..", "...", "X", "", "   "])
def test_parse_valores_suprimidos_viram_none(marcador):
    assert _parse_valor_sidra(marcador) is None


def test_parse_valor_nao_numerico_vira_none():
    assert _parse_valor_sidra("abc") is None


# ── buscar_sidra — HTTP mockado, sem rede real ───────────────────────

class _RespostaFake:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class _ClientFake:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self._status_code = status_code

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url):
        return _RespostaFake(self._payload, self._status_code)


def _mockar_httpx(monkeypatch, payload, status_code=200):
    monkeypatch.setattr(
        economia_real_mod.httpx,
        "AsyncClient",
        lambda timeout=None: _ClientFake(payload, status_code),
    )


def test_buscar_sidra_descarta_linha_de_descritores(monkeypatch):
    """O SIDRA sempre devolve o primeiro elemento do array como um
    dicionário de nomes de coluna (D1C: '...(Código)' etc), não um dado
    real — buscar_sidra precisa descartar esse elemento."""
    payload = [
        {"NC": "Nível Territorial (Código)", "D3C": "Trimestre Móvel (Código)"},
        {"NC": "1", "NN": "Brasil", "MN": "%", "V": "5.4",
         "D2N": "Taxa de desocupação", "D3C": "202601", "D3N": "nov-dez-jan 2026"},
        {"NC": "1", "NN": "Brasil", "MN": "%", "V": "...",
         "D2N": "Taxa de desocupação", "D3C": "202602", "D3N": "dez-jan-fev 2026"},
    ]
    _mockar_httpx(monkeypatch, payload)

    resultado = asyncio.run(buscar_sidra("6381", "4099"))

    assert len(resultado["pontos"]) == 2
    assert resultado["pontos"][0] == {
        "periodo_codigo": "202601",
        "periodo_label": "nov-dez-jan 2026",
        "valor": 5.4,
        "valor_bruto": "5.4",
    }
    assert resultado["pontos"][1]["valor"] is None
    assert resultado["pontos"][1]["valor_bruto"] == "..."
    assert resultado["unidade"] == "%"
    assert resultado["nome_variavel"] == "Taxa de desocupação"
    assert resultado["tabela"] == "6381"
    assert resultado["variavel"] == "4099"


def test_buscar_sidra_sem_observacoes_levanta_404(monkeypatch):
    _mockar_httpx(monkeypatch, [{"NC": "só o descritor de colunas"}])

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(buscar_sidra("0", "0"))
    assert exc_info.value.status_code == 404


def test_buscar_sidra_status_nao_200_levanta_502(monkeypatch):
    _mockar_httpx(monkeypatch, {}, status_code=500)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(buscar_sidra("6381", "4099"))
    assert exc_info.value.status_code == 502


# ── nível territorial (Brasil vs. Município) ──────────────────────────
# `n1` era hardcoded na URL até essa mudança -- só dava pra buscar Brasil.
# `nivel` agora é parâmetro, default '1' preserva o comportamento antigo
# pra qualquer chamador que não passe `nivel` explicitamente.

def test_buscar_sidra_default_continua_nivel_brasil_n1(monkeypatch):
    """Nenhum chamador antigo passa `nivel` -- tem que continuar montando
    n1 exatamente como antes (regressão do fluxo Brasil)."""
    payload = [
        {"NC": "descritor"},
        {"NC": "1", "NN": "Brasil", "MN": "%", "V": "5.4",
         "D2N": "Taxa de desocupação", "D3C": "202601", "D3N": "nov-dez-jan 2026"},
    ]
    _mockar_httpx(monkeypatch, payload)

    resultado = asyncio.run(buscar_sidra("6381", "4099"))

    assert resultado["nivel"] == "1"
    assert resultado["localidade"] == "1"
    assert "/n1/1/" in resultado["fonte_url"]


def test_buscar_sidra_nivel_municipio_monta_n6_com_codigo_ibge(monkeypatch):
    """Caso real que motivou a mudança: PIB municipal (tabela 5938,
    variável 37) de Seropédica-RJ (código IBGE 3305554 -- confirmado
    contra a API de localidades do IBGE; 3305109 é São João de Meriti,
    não Seropédica)."""
    payload = [
        {"NC": "descritor"},
        {"NC": "6", "NN": "Município", "MC": "40", "MN": "Mil Reais", "V": "3760076",
         "D1C": "3305554", "D1N": "Seropédica (RJ)",
         "D2N": "Produto Interno Bruto a preços correntes", "D3C": "2023", "D3N": "2023"},
    ]
    _mockar_httpx(monkeypatch, payload)

    resultado = asyncio.run(buscar_sidra("5938", "37", localidade="3305554", nivel="6"))

    assert resultado["nivel"] == "6"
    assert resultado["localidade"] == "3305554"
    assert "/n6/3305554/" in resultado["fonte_url"]
    assert resultado["pontos"][0]["valor"] == 3760076.0
