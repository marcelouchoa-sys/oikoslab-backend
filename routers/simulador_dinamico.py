from fastapi import APIRouter
from pydantic import BaseModel
import numpy as np

router = APIRouter()

class ConfigEconomia(BaseModel):
    # Tipo e escola
    tipo:    str = "emergente"
    escola:  str = "keynesiana"
    aberta:  bool = True

    # Parametros IS-LM base
    c0:     float = 100
    c1:     float = 0.75
    I0:     float = 200
    b:      float = 50
    G:      float = 300
    T:      float = 200
    M:      float = 1000
    Yn:     float = 1200
    Pe:     float = 1.0
    r_star: float = 0.03
    kf:     float = 200

    # Parametros estruturais
    salario_minimo:      float = 100.0   # nivel do salario minimo
    informalidade:       float = 0.30    # % da economia informal (0-1)
    tamanho_setor_pub:   float = 0.20    # % do PIB no setor publico
    abertura_comercial:  float = 0.25    # (X+M)/PIB
    nivel_tecnologico:   float = 0.50    # indice 0-1
    carga_tributaria:    float = 0.30    # % do PIB em impostos
    desigualdade:        float = 0.45    # indice Gini 0-1
    credito_privado:     float = 0.50    # credito/PIB
    u_natural:           float = 0.06    # taxa natural de desemprego

class Choque(BaseModel):
    tipo:       str
    nome:       str
    magnitude:  float = 1.0
    ano_inicio: int   = 1
    duracao:    int   = 1
    dG:         float = 0
    dT:         float = 0
    dM:         float = 0
    dYn:        float = 0
    dPe:        float = 0
    d_salario:  float = 0    # choque no salario minimo
    d_informal: float = 0    # choque na informalidade
    d_credito:  float = 0    # choque no credito
    descricao:  str   = ""

class SimulacaoInput(BaseModel):
    economia: ConfigEconomia
    choques:  list[Choque]
    periodos: int = 20

def _calibrar_por_tipo(tipo: str, e: ConfigEconomia) -> dict:
    """Ajusta parametros base conforme tipo de economia."""
    ajustes = {
        "desenvolvida":    {"mult_c1": 1.0,  "mult_b": 1.2,  "u_nat": 0.04, "alpha": 150},
        "emergente":       {"mult_c1": 0.95, "mult_b": 0.9,  "u_nat": 0.08, "alpha": 80},
        "subdesenvolvida": {"mult_c1": 0.85, "mult_b": 0.6,  "u_nat": 0.15, "alpha": 50},
        "em_desenvolvimento": {"mult_c1": 0.90, "mult_b": 0.75, "u_nat": 0.10, "alpha": 65},
    }
    aj = ajustes.get(tipo, ajustes["emergente"])

    # Efeito do salario minimo no consumo autonomo
    efeito_salario = e.salario_minimo * (1 - e.informalidade) * e.c1 * 0.1

    # Efeito da informalidade no multiplicador
    c1_ef = e.c1 * aj["mult_c1"] * (1 - e.informalidade * 0.3)

    # Efeito do credito no investimento
    I0_ef = e.I0 * (1 + e.credito_privado * 0.5)

    # Efeito da abertura comercial
    m1_ef = e.abertura_comercial * 0.3

    return {
        "c0":      e.c0 + efeito_salario,
        "c1":      round(c1_ef, 3),
        "I0":      round(I0_ef, 1),
        "b":       e.b * aj["mult_b"],
        "G":       e.G * (1 + e.tamanho_setor_pub),
        "T":       e.T * (1 + e.carga_tributaria),
        "M":       e.M,
        "P":       e.Pe,
        "Yn":      e.Yn * (1 + e.nivel_tecnologico * 0.2),
        "Pe":      e.Pe,
        "alpha_oa": aj["alpha"],
        "u_natural": aj["u_nat"] * (1 + e.desigualdade * 0.3),
        "m1":      m1_ef,
        "salario_minimo":    e.salario_minimo,
        "informalidade":     e.informalidade,
        "credito_privado":   e.credito_privado,
    }

def _ajuste_escola(escola: str) -> dict:
    configs = {
        "classica":       {"velocidade": 0.9, "rigidez": 0.1, "expect": "racional"},
        "keynesiana":     {"velocidade": 0.3, "rigidez": 0.8, "expect": "adaptativa"},
        "monetarista":    {"velocidade": 0.5, "rigidez": 0.5, "expect": "adaptativa"},
        "pos_keynesiana": {"velocidade": 0.2, "rigidez": 0.9, "expect": "incerteza"},
    }
    return configs.get(escola, configs["keynesiana"])

def _resolver_periodo(estado: dict, escola: str) -> dict:
    c0, c1, I0, b = estado["c0"], estado["c1"], estado["I0"], estado["b"]
    G,  T,  M,  P = estado["G"],  estado["T"],  estado["M"],  estado["P"]
    k, h = 0.5, 100

    # Efeito do salario minimo no consumo
    sal_ef = estado.get("salario_minimo", 0) * (1 - estado.get("informalidade", 0)) * 0.05
    c0_ef  = c0 + sal_ef

    A     = c0_ef - c1*T + I0 + G
    denom = (1 - c1) + (b * k / h)
    if denom <= 0: denom = 0.01
    Y = (A + b * M / (P * h)) / denom
    r = (k * Y - M / P) / h
    C = c0_ef + c1 * (Y - T)
    I_val = max(0, I0 - b * r)

    Yn    = estado.get("Yn", Y)
    gap   = (Y - Yn) / Yn if Yn > 0 else 0
    u_nat = estado.get("u_natural", 0.06)
    u     = max(0, u_nat - 0.5 * gap)

    Pe    = estado.get("Pe", 1.0)
    alpha = estado.get("alpha_oa", 100)
    P_new = max(0.1, Pe + (Y - Yn) / alpha)

    NX = 0.0
    if estado.get("aberta", False):
        m1  = estado.get("m1", 0.15)
        x0  = estado.get("x0", 100)
        NX  = x0 - m1 * Y

    return {"Y": Y, "r": r, "C": C, "I": I_val, "u": u, "P": P_new, "NX": NX}

@router.post("/simular")
def simular(inp: SimulacaoInput) -> dict:
    e      = inp.economia
    estado = _calibrar_por_tipo(e.tipo, e)
    estado["aberta"] = e.aberta
    estado["x0"]     = e.Yn * e.abertura_comercial * 0.5

    adj = _ajuste_escola(e.escola)
    periodos_resultado = []

    for ano in range(1, inp.periodos + 1):
        choques_ativos = []
        ep = estado.copy()

        for choque in inp.choques:
            if choque.ano_inicio <= ano < choque.ano_inicio + choque.duracao:
                choques_ativos.append(choque.nome)
                ep["G"]              += choque.dG  * choque.magnitude
                ep["T"]              += choque.dT  * choque.magnitude
                ep["M"]              += choque.dM  * choque.magnitude
                ep["Yn"]             += choque.dYn * choque.magnitude
                ep["Pe"]             += choque.dPe * choque.magnitude
                ep["salario_minimo"] += choque.d_salario * choque.magnitude
                ep["informalidade"]   = max(0, min(1, ep.get("informalidade", 0.3) + choque.d_informal * choque.magnitude))
                ep["credito_privado"] = max(0, ep.get("credito_privado", 0.5) + choque.d_credito * choque.magnitude)

        res = _resolver_periodo(ep, e.escola)

        # Ajuste dinamico das expectativas
        vel = adj["velocidade"]
        estado["Pe"] = estado["Pe"] + vel * (res["P"] - estado["Pe"])
        estado["P"]  = res["P"]

        # Efeito de histerese no desemprego (pos-keynesiano e keynesiano)
        if e.escola in ["keynesiana", "pos_keynesiana"]:
            if res["u"] > estado.get("u_natural", 0.06):
                estado["u_natural"] = estado.get("u_natural", 0.06) + 0.001

        periodos_resultado.append({
            "ano":            ano,
            "Y":              round(res["Y"], 2),
            "r":              round(res["r"] * 100, 3),
            "P":              round(res["P"], 4),
            "u":              round(res["u"] * 100, 2),
            "C":              round(res["C"], 2),
            "I":              round(res["I"], 2),
            "G":              round(ep["G"], 2),
            "NX":             round(res["NX"], 2),
            "choques_ativos": choques_ativos,
        })

    cp = periodos_resultado[:2]
    mp = periodos_resultado[2:5]
    lp = periodos_resultado[9:] if len(periodos_resultado) >= 10 else periodos_resultado[-3:]

    def media(lista, var):
        vals = [p[var] for p in lista]
        return round(sum(vals)/len(vals), 2) if vals else 0

    def descricao(prazo, lista):
        if not lista: return ""
        Y_m = media(lista, "Y")
        u_m = media(lista, "u")
        P_m = media(lista, "P")
        escola = e.escola
        if escola == "classica":
            msgs = {
                "curto":  f"Ajuste rapido dos mercados. Y = {Y_m:.0f}, desemprego converge para natural ({u_m:.1f}%).",
                "medio":  f"Equilibrio consolidado. Precos em {P_m:.3f}. Politicas de demanda perderam efeito.",
                "longo":  f"Y = Yn. Neutralidade da moeda confirmada. Oferta determina o produto.",
            }
        elif escola == "keynesiana":
            msgs = {
                "curto":  f"Rigidez de precos mantem desemprego em {u_m:.1f}%. Demanda efetiva Y = {Y_m:.0f}.",
                "medio":  f"Ajuste gradual. Multiplicador ainda opera. Politica fiscal relevante.",
                "longo":  f"Convergencia lenta. Desemprego estrutural possivel. Y = {Y_m:.0f}.",
            }
        elif escola == "monetarista":
            msgs = {
                "curto":  f"Efeito temporario dos choques. Y = {Y_m:.0f}. Expectativas se ajustam.",
                "medio":  f"Curva de Phillips acelerada. Inflacao em {P_m:.3f}. Regra monetaria importa.",
                "longo":  f"Neutralidade no LP. u = u_natural. Politica monetaria so afeta precos.",
            }
        else:
            msgs = {
                "curto":  f"Demanda efetiva domina. Y = {Y_m:.0f}. Markup determina precos ({P_m:.3f}).",
                "medio":  f"Instabilidade financeira pode amplificar. Desemprego em {u_m:.1f}%.",
                "longo":  f"Sem convergencia automatica. Estado deve sustentar demanda. Y = {Y_m:.0f}.",
            }
        return msgs.get(prazo, "")

    return {
        "status":   "ok",
        "periodos": periodos_resultado,
        "analise": {
            "curto_prazo":  {"Y": media(cp,"Y"), "u": media(cp,"u"), "P": media(cp,"P"), "descricao": descricao("curto", cp)},
            "medio_prazo":  {"Y": media(mp,"Y"), "u": media(mp,"u"), "P": media(mp,"P"), "descricao": descricao("medio", mp)},
            "longo_prazo":  {"Y": media(lp,"Y"), "u": media(lp,"u"), "P": media(lp,"P"), "descricao": descricao("longo", lp)},
        },
        "parametros_efetivos": estado,
        "escola": e.escola,
        "tipo":   e.tipo,
    }

@router.get("/choques-predefinidos")
def choques_predefinidos():
    return [
        {"id": "teto_gastos",    "nome": "Teto de Gastos",       "dG": -50,  "dT": 0,    "dM": 0,   "descricao": "Limite constitucional ao crescimento do gasto publico"},
        {"id": "bolsa_familia",  "nome": "Bolsa Familia",        "dG": 30,   "dT": 0,    "dM": 0,   "descricao": "Programa de transferencia de renda para familias pobres"},
        {"id": "salario_minimo", "nome": "Aumento Salario Min.", "dG": 0,    "dT": 0,    "dM": 0,   "d_salario": 20, "descricao": "Aumento real do salario minimo"},
        {"id": "exp_fiscal",     "nome": "Expansao Fiscal",      "dG": 100,  "dT": 0,    "dM": 0,   "descricao": "Aumento dos gastos publicos"},
        {"id": "cont_fiscal",    "nome": "Austeridade Fiscal",   "dG": -100, "dT": 50,   "dM": 0,   "descricao": "Corte de gastos e aumento de impostos"},
        {"id": "exp_monetaria",  "nome": "Expansao Monetaria",   "dG": 0,    "dT": 0,    "dM": 200, "descricao": "Aumento da oferta de moeda pelo BC"},
        {"id": "choque_petroleo","nome": "Choque do Petroleo",   "dG": 0,    "dT": 0,    "dM": 0,   "dYn": -50, "dPe": 0.1, "descricao": "Choque negativo de oferta via petroleo"},
        {"id": "crise_financ",   "nome": "Crise Financeira",     "dG": 0,    "dT": 0,    "dM": 0,   "d_credito": -0.2, "descricao": "Contracao do credito privado"},
        {"id": "abertura_comerc","nome": "Abertura Comercial",   "dG": 0,    "dT": -20,  "dM": 0,   "descricao": "Reducao de tarifas e abertura ao comercio"},
        {"id": "inovacao_tecno", "nome": "Choque Tecnologico",   "dG": 0,    "dT": 0,    "dM": 0,   "dYn": 100, "descricao": "Aumento da produtividade total dos fatores"},
    ]
