from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import httpx

router = APIRouter()

# ── World Bank API ────────────────────────────────────────────────
INDICADORES = {
    "pib":        "NY.GDP.MKTP.CD",      # PIB em USD corrente
    "pib_capita": "NY.GDP.PCAP.CD",      # PIB per capita
    "inflacao":   "FP.CPI.TOTL.ZG",      # Inflacao (IPCA)
    "desemprego": "SL.UEM.TOTL.ZS",      # Desemprego %
    "populacao":  "SP.POP.TOTL",         # Populacao
    "exportacoes":"NE.EXP.GNFS.ZS",      # Exportacoes % PIB
    "importacoes":"NE.IMP.GNFS.ZS",      # Importacoes % PIB
    "consumo":    "NE.CON.TOTL.ZS",      # Consumo % PIB
    "investimento":"NE.GDI.TOTL.ZS",     # Investimento % PIB
    "gasto_gov":  "NE.CON.GOVT.ZS",      # Gasto governo % PIB
    "taxa_juros": "FR.INR.RINR",         # Taxa de juros real
    "cambio":     "PA.NUS.FCRF",         # Taxa de cambio
}

async def buscar_world_bank(pais: str, indicador: str, ano_ini: int, ano_fim: int) -> list:
    url = (
        f"https://api.worldbank.org/v2/country/{pais}/indicator/{indicador}"
        f"?date={ano_ini}:{ano_fim}&format=json&per_page=100"
    )
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url)
        if resp.status_code != 200:
            return []
        data = resp.json()
        if len(data) < 2 or not data[1]:
            return []
        return [
            {"ano": int(item["date"]), "valor": item["value"]}
            for item in data[1]
            if item["value"] is not None
        ]

@router.get("/paises")
async def listar_paises():
    url = "https://api.worldbank.org/v2/country?format=json&per_page=300"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url)
        data = resp.json()
        paises = [
            {"codigo": p["id"], "nome": p["name"], "regiao": p["region"]["value"]}
            for p in data[1]
            if p["region"]["id"] != "NA"
        ]
        return sorted(paises, key=lambda x: x["nome"])

@router.get("/dados/{pais}/{ano_ini}/{ano_fim}")
async def buscar_dados(pais: str, ano_ini: int, ano_fim: int):
    resultados = {}
    async with httpx.AsyncClient(timeout=15) as client:
        for nome, codigo in INDICADORES.items():
            url = (
                f"https://api.worldbank.org/v2/country/{pais}/indicator/{codigo}"
                f"?date={ano_ini}:{ano_fim}&format=json&per_page=100"
            )
            try:
                resp = await client.get(url)
                data = resp.json()
                if len(data) >= 2 and data[1]:
                    serie = [
                        {"ano": int(item["date"]), "valor": item["value"]}
                        for item in data[1]
                        if item["value"] is not None
                    ]
                    resultados[nome] = sorted(serie, key=lambda x: x["ano"])
                else:
                    resultados[nome] = []
            except Exception:
                resultados[nome] = []

    return {
        "pais":    pais,
        "ano_ini": ano_ini,
        "ano_fim": ano_fim,
        "dados":   resultados,
    }

@router.get("/calibrar/{pais}/{ano_ini}/{ano_fim}")
async def calibrar_modelo(pais: str, ano_ini: int, ano_fim: int):
    """
    Busca dados reais e calibra automaticamente os parametros
    do modelo IS-LM para o pais e periodo selecionados.
    """
    dados_brutos = await buscar_dados(pais, ano_ini, ano_fim)
    dados = dados_brutos["dados"]

    def media(serie: list) -> float | None:
        vals = [x["valor"] for x in serie if x["valor"] is not None]
        return sum(vals) / len(vals) if vals else None

    def ultimo(serie: list) -> float | None:
        if not serie:
            return None
        return sorted(serie, key=lambda x: x["ano"])[-1]["valor"]

    pib_val      = media(dados.get("pib", []))
    consumo_pct  = media(dados.get("consumo", []))
    invest_pct   = media(dados.get("investimento", []))
    gov_pct      = media(dados.get("gasto_gov", []))
    inflacao_val = media(dados.get("inflacao", []))
    desempr_val  = media(dados.get("desemprego", []))
    juros_val    = media(dados.get("taxa_juros", []))
    export_pct   = media(dados.get("exportacoes", []))
    import_pct   = media(dados.get("importacoes", []))

    # Calibracao dos parametros IS-LM
    c1  = round((consumo_pct or 60) / 100 * 0.9, 2)  # propensao marginal
    G   = round((gov_pct or 20) / 100 * 100, 1)       # gasto governo normalizado
    I0  = round((invest_pct or 20) / 100 * 100, 1)    # investimento autonomo
    Y   = 100.0                                         # produto normalizado = 100
    T   = round(G * 0.8, 1)                            # impostos estimados
    c0  = round(Y * (consumo_pct or 60) / 100 - c1 * (Y - T), 1)
    r   = round((juros_val or 5) / 100, 4)
    b   = round(I0 / max(r, 0.01) * 0.1, 1)           # sensibilidade I a r

    return {
        "pais":    pais,
        "periodo": f"{ano_ini}-{ano_fim}",
        "dados_resumo": {
            "pib_medio_usd":   pib_val,
            "consumo_pct_pib": consumo_pct,
            "invest_pct_pib":  invest_pct,
            "gov_pct_pib":     gov_pct,
            "inflacao_media":  inflacao_val,
            "desemprego_medio":desempr_val,
            "juros_real_medio":juros_val,
            "exportacoes_pct": export_pct,
            "importacoes_pct": import_pct,
        },
        "parametros_calibrados": {
            "c0": c0,
            "c1": c1,
            "I0": I0,
            "G":  G,
            "T":  T,
            "b":  b,
            "r_estimado": r,
            "aberta": True,
            "x0": round((export_pct or 15) / 100 * 100, 1),
            "m0": round((import_pct or 15) / 100 * 100, 1),
            "m1": round((import_pct or 15) / 100 * 0.2, 3),
        },
        "series_historicas": dados,
    }
