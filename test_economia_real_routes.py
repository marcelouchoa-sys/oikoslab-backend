"""
Testes de rota HTTP pra routers/economia_real.py — /paises, /dados,
/calibrar (World Bank). test_economia_real_sidra.py já cobre
buscar_sidra/_parse_valor_sidra e a rota /sidra; este arquivo cobre o
que faltava: as rotas de World Bank, que estavam em 0% de cobertura de
rota (só chamavam a API de verdade, nunca teve teste automatizado).
httpx mockado via conftest.py:mockar_httpx — nenhuma chamada de rede real.
"""
from fastapi.testclient import TestClient

from main import app
import routers.economia_real as economia_real_mod

client = TestClient(app)


class _ClientHttpQueBrigaAoChamar:
    """Simula falha de rede/parsing no meio da chamada — `.get()` estoura
    exceção em vez de devolver uma resposta malformada. Cobre o
    `except Exception: resultados[nome] = []` de /dados, diferente de
    `test_buscar_dados_resposta_vazia_do_worldbank` (que cobre resposta
    HTTP válida mas sem série)."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url):
        raise RuntimeError("timeout simulado")


# ── GET /economia-real/paises ─────────────────────────────────────────

def test_listar_paises_filtra_agregados(mockar_httpx):
    """Região 'NA' (id) marca agregados tipo 'World'/'Aggregates' no World
    Bank — a rota filtra esses fora, só devolve países de verdade."""
    payload = [
        {"page": 1},
        [
            {"id": "BRA", "name": "Brazil",       "region": {"id": "LCN", "value": "Latin America & Caribbean"}},
            {"id": "WLD", "name": "World",         "region": {"id": "NA",  "value": "Aggregates"}},
            {"id": "USA", "name": "United States", "region": {"id": "NAC", "value": "North America"}},
        ],
    ]
    mockar_httpx(economia_real_mod, payload)

    res = client.get("/economia-real/paises")
    assert res.status_code == 200
    data = res.json()
    codigos = {p["codigo"] for p in data}
    assert codigos == {"BRA", "USA"}  # WLD (agregado) filtrado fora
    # ordenado por nome
    assert [p["nome"] for p in data] == sorted(p["nome"] for p in data)


# ── GET /economia-real/dados/{pais}/{ano_ini}/{ano_fim} ───────────────

def test_buscar_dados_agrega_todos_indicadores(mockar_httpx):
    payload = [
        {"page": 1},
        [
            {"date": "2020", "value": 100.0},
            {"date": "2021", "value": None},   # value nulo é descartado
            {"date": "2019", "value": 90.0},
        ],
    ]
    mockar_httpx(economia_real_mod, payload)

    res = client.get("/economia-real/dados/BRA/2019/2021")
    assert res.status_code == 200
    data = res.json()
    assert data["pais"] == "BRA"
    assert data["ano_ini"] == 2019
    assert data["ano_fim"] == 2021
    # todos os 12 indicadores presentes, cada um com a mesma série (mock)
    assert set(data["dados"].keys()) == set(economia_real_mod.INDICADORES.keys())
    serie_pib = data["dados"]["pib"]
    assert len(serie_pib) == 2  # value=None descartado
    assert [p["ano"] for p in serie_pib] == [2019, 2020]  # ordenado por ano


def test_buscar_dados_resposta_vazia_do_worldbank(mockar_httpx):
    """World Bank pode devolver só metadados sem série (país/indicador sem
    dado pro período) — vira lista vazia por indicador, sem erro."""
    mockar_httpx(economia_real_mod, [{"page": 1}, []])

    res = client.get("/economia-real/dados/ZZZ/2019/2021")
    assert res.status_code == 200
    data = res.json()
    assert all(serie == [] for serie in data["dados"].values())


def test_buscar_dados_excecao_por_indicador_nao_derruba_a_rota(monkeypatch):
    """Falha de rede (timeout, conexão recusada) num indicador específico
    é isolada pelo próprio try/except do loop — cada indicador falha
    independente, a rota sempre devolve 200 com lista vazia pros que
    quebraram."""
    monkeypatch.setattr(
        economia_real_mod.httpx, "AsyncClient", lambda timeout=None: _ClientHttpQueBrigaAoChamar()
    )
    res = client.get("/economia-real/dados/BRA/2019/2021")
    assert res.status_code == 200
    data = res.json()
    assert all(serie == [] for serie in data["dados"].values())


# ── GET /economia-real/calibrar/{pais}/{ano_ini}/{ano_fim} ────────────

def test_calibrar_modelo_com_dados_reais(mockar_httpx):
    payload = [
        {"page": 1},
        [{"date": "2020", "value": 60.0}, {"date": "2021", "value": 62.0}],
    ]
    mockar_httpx(economia_real_mod, payload)

    res = client.get("/economia-real/calibrar/BRA/2020/2021")
    assert res.status_code == 200
    data = res.json()
    assert data["pais"] == "BRA"
    assert data["periodo"] == "2020-2021"
    assert "parametros_calibrados" in data
    assert "dados_resumo" in data
    assert "series_historicas" in data
    # c1 (propensao marginal) sempre no intervalo (0, 1)
    assert 0 < data["parametros_calibrados"]["c1"] < 1


def test_calibrar_modelo_usa_defaults_quando_sem_dado(mockar_httpx):
    """Sem nenhum dado real (série vazia pra tudo), a calibração cai nos
    defaults hardcoded (or 60, or 20, or 5...) em vez de quebrar com
    ZeroDivisionError ou None em cálculo aritmético."""
    mockar_httpx(economia_real_mod, [{"page": 1}, []])

    res = client.get("/economia-real/calibrar/ZZZ/2020/2021")
    assert res.status_code == 200
    data = res.json()
    # c1 = round((consumo_pct or 60) / 100 * 0.9, 2) com consumo_pct=None -> usa o default 60
    assert data["parametros_calibrados"]["c1"] == round(60 / 100 * 0.9, 2)
    assert data["dados_resumo"]["pib_medio_usd"] is None


# ── GET /economia-real/sidra/{tabela}/{variavel} (rota, não só a função) ─

def test_sidra_rota_http_ponta_a_ponta(mockar_httpx):
    """test_economia_real_sidra.py já cobre buscar_sidra() como função
    Python direta — aqui é a rota HTTP em si (linha `return await
    buscar_sidra(...)` do handler), nunca exercitada via TestClient."""
    payload = [
        {"NC": "descritor"},
        {"NC": "1", "NN": "Brasil", "MN": "%", "V": "5.4",
         "D2N": "Taxa de desocupação", "D3C": "202601", "D3N": "nov-dez-jan 2026"},
    ]
    mockar_httpx(economia_real_mod, payload)

    res = client.get("/economia-real/sidra/6381/4099")
    assert res.status_code == 200
    data = res.json()
    assert data["tabela"] == "6381"
    assert data["pontos"][0]["valor"] == 5.4
    assert data["nivel"] == "1"  # sem ?municipio, continua Brasil (regressão)


def test_sidra_rota_com_municipio_busca_nivel_6(mockar_httpx):
    """?municipio= é a única forma nova de sair do nível Brasil (v1 do
    Data Hub não expõe seletor de nível territorial completo, só
    Brasil/Município -- ver docstring de sidra_serie)."""
    payload = [
        {"NC": "descritor"},
        {"NC": "6", "NN": "Município", "MC": "40", "MN": "Mil Reais", "V": "3760076",
         "D1C": "3305554", "D1N": "Seropédica (RJ)",
         "D2N": "Produto Interno Bruto a preços correntes", "D3C": "2023", "D3N": "2023"},
    ]
    mockar_httpx(economia_real_mod, payload)

    res = client.get("/economia-real/sidra/5938/37", params={"municipio": "3305554"})
    assert res.status_code == 200
    data = res.json()
    assert data["nivel"] == "6"
    assert data["localidade"] == "3305554"


# ── buscar_world_bank — função exportada, não usada por nenhuma rota hoje ─
# (/dados e /calibrar duplicam a mesma lógica inline em vez de chamá-la;
# verificado via grep — nenhum call site além da própria definição.
# Testada mesmo assim: é lógica pública, real, só não está conectada.)

def test_buscar_world_bank_funcao_isolada(mockar_httpx):
    import asyncio

    payload = [
        {"page": 1},
        [{"date": "2020", "value": 50.0}, {"date": "2021", "value": None}],
    ]
    mockar_httpx(economia_real_mod, payload)

    resultado = asyncio.run(economia_real_mod.buscar_world_bank("BRA", "NY.GDP.MKTP.CD", 2020, 2021))
    assert resultado == [{"ano": 2020, "valor": 50.0}]


def test_buscar_world_bank_status_nao_200_retorna_lista_vazia(mockar_httpx):
    import asyncio

    mockar_httpx(economia_real_mod, {}, status_code=500)
    resultado = asyncio.run(economia_real_mod.buscar_world_bank("BRA", "NY.GDP.MKTP.CD", 2020, 2021))
    assert resultado == []
