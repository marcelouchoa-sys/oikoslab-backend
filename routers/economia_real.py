from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from urllib.parse import quote
import httpx

from services.parse_numero import parse_numero_br

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


# ── SIDRA (IBGE) — Data Hub v1 ────────────────────────────────────────
# API totalmente aberta, sem autenticação (verificado ao vivo contra
# apisidra.ibge.gov.br em 2026-08). Formato: array JSON onde o PRIMEIRO
# elemento é um dicionário de descritores de coluna (não é dado), os
# demais são as observações reais.

_MARCADORES_SUPRIMIDOS = {"-", "..", "...", "X"}

def _parse_valor_sidra(valor_bruto: str) -> float | None:
    """
    O SIDRA usa marcadores de texto pra dado suprimido/indisponível
    ('-', '..', '...', 'X') em vez de omitir o ponto. Nesses casos (ou em
    qualquer valor que não parseie) retorna None — quem chama preserva o
    valor_bruto original separadamente pra auditoria.

    Delega o parse pra `parse_numero_br` (formato brasileiro: ponto pode
    ser milhar, vírgula é decimal) em vez de `float()` puro — o "V" bruto
    do SIDRA nunca traz separador de milhar nos casos testados (PIB,
    população: sempre dígitos corridos), mas essa função é o ponto único
    de conversão texto->número pra dado importado, então blindada aqui
    também por precaução, não só nos pontos que o bug original afetou.
    """
    texto = (valor_bruto or "").strip()
    if not texto or texto in _MARCADORES_SUPRIMIDOS:
        return None
    try:
        return parse_numero_br(texto)
    except ValueError:
        return None


async def buscar_sidra(
    tabela: str, variavel: str, localidade: str = "1", periodos: str = "last 6", nivel: str = "1"
) -> dict:
    """
    Busca uma série do SIDRA (IBGE) — tabela/variável/localidade seguem
    os códigos do próprio SIDRA (ex: tabela '6381', variável '4099' =
    Taxa de desocupação PNAD Contínua trimestral, localidade '1' = Brasil).

    `nivel` é o nível territorial do SIDRA (n1=Brasil, n3=Estado, n6=
    Município — códigos do próprio SIDRA). Default '1' preserva o
    comportamento original (Brasil) pra todo chamador que não passar
    `nivel` explicitamente. v1 do Data Hub só expõe Brasil e Município
    pelo endpoint HTTP (ver `sidra_serie` abaixo) — Estado fica de fora
    por não ter caso de uso ainda, não é limitação técnica desta função.

    LIMITAÇÃO CONHECIDA (Data Hub v1): esta função devolve a série
    inteira dos períodos pedidos, mas o mapeamento de variável
    (variavel_mapeamentos) sempre usa o ÚLTIMO ponto — não há seletor de
    período nem uso da série completa num parâmetro ainda. Série
    histórica completa (Canvas dinâmico, estimação) é v2+.
    """
    url = (
        f"https://apisidra.ibge.gov.br/values/t/{tabela}/n{nivel}/{localidade}"
        f"/v/{variavel}/p/{quote(periodos)}"
    )
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url)
        if resp.status_code != 200:
            raise HTTPException(
                502, f"SIDRA respondeu {resp.status_code} para tabela {tabela}, variável {variavel}."
            )
        data = resp.json()

    if not isinstance(data, list) or len(data) < 2:
        raise HTTPException(404, f"Nenhum dado encontrado para tabela {tabela}, variável {variavel}.")

    linhas = data[1:]  # primeiro elemento é o descritor de colunas, não dado

    pontos = [
        {
            "periodo_codigo": linha.get("D3C", ""),
            "periodo_label":  linha.get("D3N", ""),
            "valor":          _parse_valor_sidra(linha.get("V", "")),
            "valor_bruto":    linha.get("V", ""),
        }
        for linha in linhas
    ]

    primeira = linhas[0]
    return {
        "tabela":        tabela,
        "variavel":      variavel,
        "localidade":    localidade,
        "nivel":         nivel,
        "unidade":       primeira.get("MN"),
        "nome_variavel": primeira.get("D2N"),
        "fonte_url":     url,
        "pontos":        pontos,
    }


@router.get("/sidra/{tabela}/{variavel}")
async def sidra_serie(
    tabela: str,
    variavel: str,
    localidade: str = "1",
    periodos: str = "last 6",
    municipio: str | None = None,
):
    """
    Preview de uma série SIDRA antes de importar — ver buscar_sidra().

    Por padrão busca nível Brasil (n1, localidade='1') — comportamento
    inalterado, os atalhos existentes (Taxa de Desemprego, PIB
    Trimestral) continuam batendo aqui exatamente como antes. Se
    `municipio` vier preenchido (código IBGE de 7 dígitos, ex: 3305109 =
    Seropédica-RJ), busca nível Município (n6) com esse código em vez de
    Brasil. v1 do Data Hub não expõe Estado (n3) nem um seletor de nível
    territorial completo — decisão explícita: o caso de uso real hoje é
    só Brasil ou Município, um seletor genérico seria over-engineering.
    """
    if municipio:
        return await buscar_sidra(tabela, variavel, localidade=municipio, periodos=periodos, nivel="6")
    return await buscar_sidra(tabela, variavel, localidade=localidade, periodos=periodos)
