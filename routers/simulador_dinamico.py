from fastapi import APIRouter
from pydantic import BaseModel
import numpy as np

router = APIRouter()

# =============================================================
#  SIMULADOR DINAMICO — Modelo Novo-Keynesiano de 3 Equacoes
#  (Carlin & Soskice / Gali)
#
#  Bloco 1 — IS dinamica:
#     y_gap(t) = a*y_gap(t-1) - alpha*(r(t-1) - r_n) + eps_demanda
#
#  Bloco 2 — Curva de Phillips (aceleracionista, c/ expectativas):
#     pi(t) = pi_e(t) + beta*y_gap(t) + eps_oferta
#
#  Bloco 3 — Regra de Taylor (Banco Central):
#     r(t) = r_n + phi_pi*(pi(t) - pi_meta) + phi_y*y_gap(t)
#
#  Lei de Okun (mapeia hiato -> desemprego):
#     u(t) = u_n - okun*y_gap(t)
#
#  As "escolas" sao PARAMETRIZACOES deste mesmo modelo.
# =============================================================


class ConfigEconomia(BaseModel):
    # Tipo e escola
    tipo:   str = "emergente"
    escola: str = "keynesiana"
    aberta: bool = True

    # Metas e equilibrio de longo prazo
    pi_meta:    float = 2.0    # meta de inflacao (% a.a.)
    r_natural:  float = 2.0    # juro real natural / neutro (% a.a.)
    u_natural:  float = 6.0    # taxa natural de desemprego (%)

    # Parametros estruturais (entram na calibragem do modelo)
    salario_minimo:     float = 100.0   # nivel do salario minimo
    informalidade:      float = 0.30    # % da economia informal (0-1)
    tamanho_setor_pub:  float = 0.20    # % do PIB no setor publico
    abertura_comercial: float = 0.25    # (X+M)/PIB
    nivel_tecnologico:  float = 0.50    # indice 0-1
    carga_tributaria:   float = 0.30    # % do PIB em impostos
    desigualdade:       float = 0.45    # indice Gini 0-1
    credito_privado:    float = 0.50    # credito/PIB

    # Condicao inicial (em desvios do equilibrio)
    y_gap_inicial: float = 0.0
    pi_inicial:    float = 2.0


class Choque(BaseModel):
    tipo:       str
    nome:       str
    magnitude:  float = 1.0
    ano_inicio: int   = 1
    duracao:    int   = 1
    # Choques mapeados para o modelo de 3 equacoes
    eps_demanda: float = 0.0   # choque na IS (% do produto potencial)
    eps_oferta:  float = 0.0   # choque na Phillips (pontos de inflacao)
    d_r_natural: float = 0.0   # choque no juro natural
    d_pi_meta:   float = 0.0   # mudanca na meta de inflacao
    # Compatibilidade com choques antigos (sao convertidos)
    dG:         float = 0
    dT:         float = 0
    dM:         float = 0
    dYn:        float = 0
    dPe:        float = 0
    d_salario:  float = 0
    d_credito:  float = 0
    descricao:  str   = ""


class SimulacaoInput(BaseModel):
    economia: ConfigEconomia
    choques:  list[Choque]
    periodos: int = 20
    comparar_escolas: bool = False   # se True, roda todas as escolas


# -------------------------------------------------------------
#  PARAMETRIZACOES POR ESCOLA (o coracao pedagogico)
# -------------------------------------------------------------
def _params_escola(escola: str) -> dict:
    """
    Cada escola e uma parametrizacao do modelo de 3 equacoes.

    a        : persistencia do hiato (inercia da IS)
    alpha    : sensibilidade do hiato ao juro real (eficacia da pol. monetaria)
    beta     : inclinacao da Phillips (sacrificio: alto = Phillips ingreme)
    phi_pi   : peso do BC na inflacao (regra de Taylor)
    phi_y    : peso do BC no hiato (regra de Taylor)
    theta    : peso das expectativas forward-looking (0=adaptativa, 1=racional)
    histerese: o juro/desemprego natural se move com o hiato? (pos-keynesiano)
    """
    configs = {
        # Novo-classica: expectativas racionais, Phillips ingreme, BC duro
        "classica": {
            "a": 0.30, "alpha": 0.90, "beta": 0.80,
            "phi_pi": 1.80, "phi_y": 0.25, "theta": 1.0, "histerese": 0.0,
            "nome": "Novo-Classica",
        },
        # Keynesiana: rigidez alta, Phillips plana, expectativas adaptativas
        "keynesiana": {
            "a": 0.75, "alpha": 0.40, "beta": 0.25,
            "phi_pi": 1.20, "phi_y": 0.80, "theta": 0.0, "histerese": 0.0,
            "nome": "Keynesiana",
        },
        # Monetarista: BC muito duro com inflacao, expectativas adaptativas
        "monetarista": {
            "a": 0.50, "alpha": 0.70, "beta": 0.55,
            "phi_pi": 2.00, "phi_y": 0.10, "theta": 0.2, "histerese": 0.0,
            "nome": "Monetarista",
        },
        # Pos-keynesiana: histerese, sem convergencia automatica
        "pos_keynesiana": {
            "a": 0.85, "alpha": 0.30, "beta": 0.18,
            "phi_pi": 1.10, "phi_y": 0.90, "theta": 0.0, "histerese": 0.04,
            "nome": "Pos-Keynesiana",
        },
    }
    return configs.get(escola, configs["keynesiana"])


def _ajuste_estrutural(e: ConfigEconomia, p: dict) -> dict:
    """
    Parametros estruturais MODIFICAM os coeficientes do modelo.
    Aqui a teoria encontra a realidade do pais.
    """
    p = p.copy()

    # Informalidade reduz a eficacia da politica monetaria (menos gente no
    # mercado de credito formal sente o juro) -> alpha menor.
    p["alpha"] *= (1 - e.informalidade * 0.5)

    # Credito privado amplifica a transmissao do juro -> alpha maior.
    p["alpha"] *= (1 + (e.credito_privado - 0.5) * 0.3)

    # Desigualdade e informalidade achatam a Phillips (mais folga, salarios
    # menos responsivos) -> beta menor.
    p["beta"] *= (1 - e.desigualdade * 0.2 - e.informalidade * 0.2)

    # Setor publico grande adiciona inercia/estabilizador automatico -> a maior.
    p["a"] = min(0.95, p["a"] * (1 + e.tamanho_setor_pub * 0.2))

    # Nivel tecnologico melhora ancoragem (BC mais critico) -> theta sobe um pouco.
    p["theta"] = min(1.0, p["theta"] + e.nivel_tecnologico * 0.1)

    # garante limites sensatos
    p["alpha"] = max(0.05, p["alpha"])
    p["beta"]  = max(0.05, p["beta"])
    return p


def _calibrar_naturais(e: ConfigEconomia) -> dict:
    """Ajusta valores de equilibrio (naturais) conforme tipo de economia."""
    base_u = {
        "desenvolvida": 4.0, "emergente": 8.0,
        "em_desenvolvimento": 10.0, "subdesenvolvida": 15.0,
    }.get(e.tipo, 8.0)
    # desigualdade eleva o desemprego natural
    u_n = base_u * (1 + e.desigualdade * 0.3)
    return {
        "u_natural": e.u_natural if e.u_natural else u_n,
        "r_natural": e.r_natural,
        "pi_meta":   e.pi_meta,
    }


# -------------------------------------------------------------
#  MOTOR DE SIMULACAO (resolve o sistema dinamico)
# -------------------------------------------------------------
def _simular_trajetoria(e: ConfigEconomia, choques: list[Choque],
                        periodos: int, escola: str) -> list[dict]:
    p = _ajuste_estrutural(e, _params_escola(escola))
    nat = _calibrar_naturais(e)

    okun = 0.5  # coeficiente de Okun

    # Estado inicial (em equilibrio, salvo condicao inicial)
    y_gap = e.y_gap_inicial
    pi    = e.pi_inicial
    pi_e  = nat["pi_meta"]
    r     = nat["r_natural"]
    r_nat = nat["r_natural"]
    pi_meta = nat["pi_meta"]
    u_nat = nat["u_natural"]

    resultado = []

    for ano in range(1, periodos + 1):
        # ---- coletar choques ativos neste ano ----
        eps_d = eps_s = d_rn = d_meta = 0.0
        ativos = []
        for c in choques:
            if c.ano_inicio <= ano < c.ano_inicio + c.duracao:
                ativos.append(c.nome)
                # choques nativos do modelo
                eps_d  += c.eps_demanda * c.magnitude
                eps_s  += c.eps_oferta  * c.magnitude
                d_rn   += c.d_r_natural * c.magnitude
                d_meta += c.d_pi_meta   * c.magnitude
                # conversao dos choques antigos para o novo modelo
                eps_d  += (c.dG - c.dT) * 0.02 * c.magnitude     # fiscal -> demanda
                eps_d  += c.dM * 0.01 * c.magnitude              # monetario -> demanda
                eps_s  += c.dPe * 10 * c.magnitude               # choque de preco -> oferta
                eps_s  += (-c.dYn) * 0.02 * c.magnitude          # choque de produtividade
                eps_d  += c.d_salario * 0.05 * c.magnitude       # salario -> demanda
                eps_d  += c.d_credito * 5 * c.magnitude          # credito -> demanda

        r_nat   += d_rn
        pi_meta += d_meta

        # ---- guardar estado defasado ----
        y_gap_lag = y_gap
        r_lag     = r

        # ---- BLOCO 1: IS dinamica ----
        y_gap = p["a"] * y_gap_lag - p["alpha"] * (r_lag - r_nat) + eps_d

        # ---- expectativas (mistura forward/backward) ----
        # theta=1 racional (ancora na meta); theta=0 adaptativa (olha passado)
        pi_e = p["theta"] * pi_meta + (1 - p["theta"]) * pi

        # ---- BLOCO 2: Curva de Phillips ----
        pi = pi_e + p["beta"] * y_gap + eps_s

        # ---- BLOCO 3: Regra de Taylor ----
        r = r_nat + p["phi_pi"] * (pi - pi_meta) + p["phi_y"] * y_gap

        # ---- Okun: hiato -> desemprego ----
        u = u_nat - okun * y_gap

        # ---- histerese (pos-keynesiano): desemprego natural sobe ----
        if p["histerese"] > 0 and y_gap < 0:
            u_nat += p["histerese"] * (-y_gap)
            r_nat += p["histerese"] * 0.5 * (-y_gap)

        resultado.append({
            "ano":            ano,
            "y_gap":          round(y_gap, 3),
            "pi":             round(pi, 3),
            "pi_e":           round(pi_e, 3),
            "r":              round(r, 3),
            "r_real":         round(r - pi, 3),
            "u":              round(max(0, u), 2),
            "r_natural":      round(r_nat, 3),
            "u_natural":      round(u_nat, 2),
            "pi_meta":        round(pi_meta, 2),
            "choques_ativos": ativos,
        })

    return resultado


# -------------------------------------------------------------
#  ANALISE CP / MP / LP
# -------------------------------------------------------------
def _media(lista, var):
    vals = [p[var] for p in lista]
    return round(sum(vals) / len(vals), 2) if vals else 0


def _descricao(prazo: str, lista: list, escola: str) -> str:
    if not lista:
        return ""
    yg = _media(lista, "y_gap")
    pi = _media(lista, "pi")
    u  = _media(lista, "u")
    nome = _params_escola(escola)["nome"]

    sinal_hiato = "expansionista (hiato positivo)" if yg > 0.1 else \
                  "recessivo (hiato negativo)" if yg < -0.1 else "proximo do equilibrio"

    base = {
        "curto": f"[{nome}] No curto prazo a economia esta {sinal_hiato}. "
                 f"Hiato medio {yg:.2f}%, inflacao {pi:.2f}%, desemprego {u:.1f}%.",
        "medio": f"[{nome}] No medio prazo o Banco Central reage via regra de Taylor. "
                 f"Hiato {yg:.2f}%, inflacao convergindo ({pi:.2f}%), desemprego {u:.1f}%.",
        "longo": f"[{nome}] No longo prazo, hiato {yg:.2f}% e inflacao {pi:.2f}%. "
                 f"Desemprego {u:.1f}%.",
    }
    return base.get(prazo, "")


def _montar_analise(traj: list, escola: str) -> dict:
    cp = traj[:2]
    mp = traj[2:5]
    lp = traj[9:] if len(traj) >= 10 else traj[-3:]
    return {
        "curto_prazo": {"y_gap": _media(cp, "y_gap"), "pi": _media(cp, "pi"),
                        "u": _media(cp, "u"), "descricao": _descricao("curto", cp, escola)},
        "medio_prazo": {"y_gap": _media(mp, "y_gap"), "pi": _media(mp, "pi"),
                        "u": _media(mp, "u"), "descricao": _descricao("medio", mp, escola)},
        "longo_prazo": {"y_gap": _media(lp, "y_gap"), "pi": _media(lp, "pi"),
                        "u": _media(lp, "u"), "descricao": _descricao("longo", lp, escola)},
    }


# -------------------------------------------------------------
#  ENDPOINTS
# -------------------------------------------------------------
@router.post("/simular")
def simular(inp: SimulacaoInput) -> dict:
    e = inp.economia

    if inp.comparar_escolas:
        escolas = ["classica", "keynesiana", "monetarista", "pos_keynesiana"]
        comparacao = {}
        for esc in escolas:
            traj = _simular_trajetoria(e, inp.choques, inp.periodos, esc)
            comparacao[esc] = {
                "nome":     _params_escola(esc)["nome"],
                "periodos": traj,
                "analise":  _montar_analise(traj, esc),
            }
        return {
            "status": "ok",
            "modo": "comparacao",
            "comparacao": comparacao,
            "tipo": e.tipo,
        }

    traj = _simular_trajetoria(e, inp.choques, inp.periodos, e.escola)
    return {
        "status":   "ok",
        "modo":     "simples",
        "periodos": traj,
        "analise":  _montar_analise(traj, e.escola),
        "parametros_modelo": _ajuste_estrutural(e, _params_escola(e.escola)),
        "escola":   e.escola,
        "escola_nome": _params_escola(e.escola)["nome"],
        "tipo":     e.tipo,
    }


@router.post("/irf")
def funcao_resposta_impulso(inp: SimulacaoInput) -> dict:
    """
    Funcao de Resposta a Impulso (IRF): aplica UM choque unitario no ano 1
    e mostra como cada variavel responde ao longo do tempo, ja em desvios
    do equilibrio. E o grafico padrao de bancos centrais e papers.
    """
    e = inp.economia
    # baseline sem choque
    base = _simular_trajetoria(e, [], inp.periodos, e.escola)
    # com choque
    com = _simular_trajetoria(e, inp.choques, inp.periodos, e.escola)

    irf = []
    for b, c in zip(base, com):
        irf.append({
            "ano":   b["ano"],
            "y_gap": round(c["y_gap"] - b["y_gap"], 4),
            "pi":    round(c["pi"]    - b["pi"], 4),
            "r":     round(c["r"]     - b["r"], 4),
            "u":     round(c["u"]     - b["u"], 4),
        })
    return {"status": "ok", "irf": irf, "escola": e.escola,
            "escola_nome": _params_escola(e.escola)["nome"]}


@router.get("/choques-predefinidos")
def choques_predefinidos():
    return [
        {"id": "exp_fiscal",     "nome": "Expansao Fiscal",      "eps_demanda": 2.0,
         "descricao": "Aumento de gastos publicos: desloca a IS para a direita"},
        {"id": "cont_fiscal",    "nome": "Austeridade Fiscal",   "eps_demanda": -2.0,
         "descricao": "Corte de gastos e aumento de impostos: contrai a demanda"},
        {"id": "exp_monetaria",  "nome": "Expansao Monetaria",   "d_r_natural": -1.0,
         "descricao": "Reducao do juro neutro: estimulo monetario"},
        {"id": "choque_petroleo","nome": "Choque do Petroleo",   "eps_oferta": 3.0,
         "descricao": "Choque de oferta adverso: empurra a Phillips para cima"},
        {"id": "choque_demanda", "nome": "Boom de Demanda",      "eps_demanda": 3.0,
         "descricao": "Otimismo/credito: forte expansao da demanda agregada"},
        {"id": "crise_financ",   "nome": "Crise Financeira",     "eps_demanda": -4.0,
         "descricao": "Contracao de credito e colapso da demanda"},
        {"id": "desinflacao",    "nome": "Reducao da Meta",      "d_pi_meta": -2.0,
         "descricao": "BC reduz a meta de inflacao: desinflacao deliberada"},
        {"id": "salario_minimo", "nome": "Aumento Salario Min.", "eps_demanda": 1.0, "eps_oferta": 0.5,
         "descricao": "Eleva demanda (consumo) e custos (oferta) simultaneamente"},
        {"id": "inovacao_tecno", "nome": "Choque Tecnologico",   "eps_oferta": -2.0, "d_r_natural": 0.5,
         "descricao": "Ganho de produtividade: reduz inflacao e eleva juro natural"},
    ]