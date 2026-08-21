"""
Casos de borda de services/economy_engine.py que os testes existentes
(test_engine.py — casos canônicos felizes; test_economy_engine_grafo.py —
integração com funcoes_grafo) não cobriam: entrada vazia, parâmetro
faltando, sistema sem solução, expressão inválida, nome reservado do
SymPy, e os pontos de entrada IS-LM-BP (run_islm/run_islm_curvas/
_build_islm_equations), que estavam em 0% de cobertura.
"""
from types import SimpleNamespace

import pytest

from services.economy_engine import EconomyEngine
import services.config as cfg


def eq(variavel="", expressao="", nome=""):
    return SimpleNamespace(variavel=variavel, expressao=expressao, nome=nome)


def vl(nome, min_=0, max_=10, pontos=5, mostrar=None):
    return SimpleNamespace(nome=nome, min=min_, max=max_, pontos=pontos, mostrar=mostrar or [])


@pytest.fixture(autouse=True)
def _reset_config():
    enabled_original = cfg.ECONOMIC_VALIDATION_ENABLED
    modo_original = cfg.ECONOMIC_VALIDATION_MODE
    yield
    cfg.ECONOMIC_VALIDATION_ENABLED = enabled_original
    cfg.ECONOMIC_VALIDATION_MODE = modo_original


# ── Entrada vazia / degenerada ────────────────────────────────────────

def test_run_lista_de_equacoes_vazia():
    r = EconomyEngine.run([], {})
    assert r["valores"] == {}
    assert r["erros"]  # "Nenhuma equação válida."


def test_run_equacao_com_lhs_e_rhs_vazios_e_ignorada():
    """_split_equacao('') com variavel='' e expressao='' -> lhs/rhs vazios,
    _parse/_detect pulam a equação (linhas 201/245) sem quebrar o pipeline."""
    r = EconomyEngine.run([eq(variavel="", expressao=""), eq("Y", "100")], {})
    assert r["valores"].get("Y") == 100.0


def test_run_parametro_nao_declarado_vira_endogena_faltando():
    """Símbolo usado na expressão mas ausente de `parametros` é tratado
    como endógena adicional — sistema fica subdeterminado (2 incógnitas,
    1 equação), sem erro de 'parâmetro faltando'."""
    r = EconomyEngine.run([eq("Y", "C + 100")], {})
    assert "C" in r["parametros_detectados"] or "C" in r["endogenas"]


def test_run_sistema_sem_solucao_nao_quebra():
    """Y=1 e Y=2 simultaneamente: sistema contraditório. sp.solve retorna
    lista vazia (não é exceção) — sol_num/sol_sym ficam {} sem erro
    registrado; o pipeline formata normalmente em vez de estourar."""
    r = EconomyEngine.run([eq("Y", "1"), eq("Y", "2")], {})
    assert r["valores"] == {}
    assert r["elasticidades"] == {}  # _compute_elasticidades linha 275: sol_sym vazio


def test_run_expressao_com_sintaxe_invalida():
    r = EconomyEngine.run([eq("Y", "))) sintaxe quebrada (((")], {})
    assert any("Erro ao interpretar" in e for e in r["erros"])


def test_detect_direto_ignora_equacao_vazia():
    """EconomyEngine._detect nunca recebe equação com lhs/rhs vazios via
    run() -- _parse já filtra isso ANTES de chamar _detect (mesma
    equação nunca chega duas vezes no pipeline). Chamando _detect direto
    (bypassando _parse) pra cobrir esse `continue` que só existiria se
    _detect fosse usado isolado no futuro."""
    endogenas, parametros, ordenadas = EconomyEngine._detect(
        [eq(variavel="", expressao=""), eq("Y", "100")], {}
    )
    assert endogenas == {"Y"}
    assert ordenadas == ["Y"]


# ── Bug conhecido: 'Q' é nome reservado do SymPy (sympy.assumptions.Q) ──

def test_sympify_bruto_de_Q_sem_locals_falha():
    """Prova isolada da causa raiz, fora do pipeline: sp.sympify('Q + 1')
    SEM locals resolve 'Q' pro objeto de assumptions do SymPy (sympy.Q),
    não um Symbol — operação aritmética com ele estoura TypeError. Isso é
    o que acontece dentro de EconomyEngine._detect ao escanear os
    símbolos livres do lado direito de uma expressão (services/
    economy_engine.py:250, sem locals=)."""
    import sympy as sp
    with pytest.raises(TypeError):
        sp.sympify("Q + 1")


@pytest.mark.xfail(
    reason=(
        "BUG CONHECIDO, não corrigido (decisão pendente do usuário): "
        "'Q' como símbolo livre no lado direito de uma expressão (ex: "
        "'Y = Q + 1', Q pretendido como parâmetro/quantidade) nunca é "
        "detectado — EconomyEngine._detect escaneia o RHS com "
        "sp.sympify(rhs) SEM locals=, que resolve 'Q' pro objeto global "
        "sympy.assumptions.Q em vez de um Symbol, estoura TypeError, e o "
        "except Exception: pass silencia isso — 'Q' nunca entra em "
        "`todos`/`endogenas`. O motor_sistemas._resolve_sistema então "
        "tenta sympify(rhs, locals=simbolos) sem 'Q' nos locals (porque "
        "nunca foi detectado), estoura de novo, e a equação inteira é "
        "descartada com um erro de 'AssumptionKeys' que não faz sentido "
        "nenhum pra quem está montando um modelo econômico com Q de "
        "'quantidade' (notação extremamente comum). Ver "
        "test_sympify_bruto_de_Q_sem_locals_falha para a causa isolada. "
        "Fix nesta suíte foi propositalmente NÃO aplicado — pendente de "
        "decisão do usuário."
    ),
    strict=True,
)
def test_variavel_Q_como_parametro_livre_deveria_resolver_mas_nao_resolve():
    r = EconomyEngine.run([eq("Y", "Q + 1")], {"Q": 10})
    assert r["valores"].get("Y") == pytest.approx(11.0)


@pytest.mark.xfail(
    reason=(
        "Mesma causa raiz do teste acima, verificada agora sem 'Q' "
        "aparecer em `parametros` — o objetivo é confirmar que 'Q' pelo "
        "menos seria auto-detectado como endógena faltando (mesmo "
        "comportamento de qualquer outro símbolo livre não declarado, "
        "ver test_run_parametro_nao_declarado_vira_endogena_faltando). "
        "Hoje 'Q' simplesmente desaparece do sistema."
    ),
    strict=True,
)
def test_variavel_Q_deveria_ser_detectada_como_endogena_faltando():
    r = EconomyEngine.run([eq("Y", "Q + 100")], {})
    assert "Q" in r["parametros_detectados"] or "Q" in r["endogenas"]


def test_variavel_Q_como_lado_esquerdo_funciona_normalmente():
    """Contraste importante: 'Q' funciona perfeitamente quando aparece
    como LHS (endógena resolvida) — _detect adiciona 'Q' a endogenas_lhs
    via string pura (lhs.isidentifier()), sem passar por sympify. O bug
    só existe quando 'Q' aparece livre num RHS, nunca como LHS de
    nenhuma equação do sistema."""
    r = EconomyEngine.run([eq("Q", "100 - 2*P")], {"P": 10})
    assert r["valores"].get("Q") == pytest.approx(80.0)


# ── resolve_single (simulação de cenários) ────────────────────────────

def test_resolve_single_fail_fast_com_violacao_retorna_valores_vazios():
    cfg.ECONOMIC_VALIDATION_MODE = "fail_fast"
    r = EconomyEngine.resolve_single([eq("Y", "-100")], {})
    assert r["valores"] == {}
    assert r["valid"] is False
    assert r["violations"]


def test_resolve_single_caso_valido():
    r = EconomyEngine.resolve_single([eq("Y", "100")], {})
    assert r["valores"]["Y"] == 100.0
    assert r["valid"] is True


# ── _compute_series edge cases ─────────────────────────────────────────

def test_series_mostrar_variavel_inexistente_e_ignorada():
    r = EconomyEngine.run(
        [eq("Y", "G0")],
        {"G0": 100},
        sensibilidades=[vl("G0", 0, 10, 5, mostrar=["NaoExiste"])],
    )
    assert r["series"] is not None
    assert "NaoExiste_vs_G0" not in r["series"]
    assert "G0" in r["series"]  # a grade em si sempre entra


def test_series_com_divisao_por_zero_na_grade_vira_none():
    """Grade de sensibilidade que passa por G0=0 numa expressão 100/G0:
    sympy retorna zoo (infinito complexo), float(zoo) estoura TypeError
    — capturado e vira None na série, sem derrubar o cálculo inteiro."""
    r = EconomyEngine.run(
        [eq("Y", "100/G0")],
        {"G0": 5},
        sensibilidades=[vl("G0", -10, 10, 5)],  # linspace(-10,10,5) inclui 0.0
    )
    assert r["series"] is not None
    serie_y = r["series"]["Y_vs_G0"]
    assert None in serie_y


# ── IS-LM-BP (services/economy_engine.py:476-585, 0% de cobertura) ────

def test_run_islm_economia_fechada_equilibrio():
    config = {
        "aberta": False,
        "c0": 100, "c1": 0.75, "T": 200, "I0": 200, "b": 50,
        "G": 300, "M": 1000, "P": 1.0, "k": 0.5, "h": 100,
    }
    r = EconomyEngine.run_islm(config)
    assert r["status"] in ("ok", "parcial")
    assert "equilibrio" in r
    assert r["equilibrio"]["Y"] is not None
    assert r["equilibrio"]["r"] is not None


def test_run_islm_mobilidade_perfeita_mundell_fleming():
    """kf >= 1e5 -> ramo de mobilidade perfeita (r = r_star fixo)."""
    config = {
        "aberta": True, "kf": 1e6,
        "c0": 100, "c1": 0.7, "T": 100, "I0": 150, "b": 40,
        "G": 200, "r_star": 0.05, "x0": 50, "x1": 0.1, "e": 1.0,
        "m0": 30, "m1": 0.05,
    }
    r = EconomyEngine.run_islm(config)
    assert r["status"] in ("ok", "parcial")
    assert r["equilibrio"]["r"] == pytest.approx(0.05)


def test_run_islm_mobilidade_imperfeita_balanco_pagamentos():
    """kf finito (< 1e5) -> ramo de mobilidade imperfeita, BP explícito."""
    config = {
        "aberta": True, "kf": 500,
        "c0": 100, "c1": 0.7, "T": 100, "I0": 150, "b": 40,
        "G": 200, "r_star": 0.05, "x0": 50, "x1": 0.1, "e": 1.0,
        "m0": 30, "m1": 0.05,
    }
    r = EconomyEngine.run_islm(config)
    assert r["status"] in ("ok", "parcial")
    assert "NX" in r["equilibrio"]


def test_run_islm_invalid_solution_propaga_sem_montar_equilibrio():
    """Config que produz Y<0 (bloqueante) -> run_islm devolve o
    invalid_solution direto, sem tentar montar o bloco 'equilibrio'
    (que dependeria de 'valores', ausente nesse status)."""
    cfg.ECONOMIC_VALIDATION_MODE = "fail_fast"
    config = {
        "aberta": False,
        "c0": -100000, "c1": 0.5, "T": 0, "I0": 0, "b": 50,
        "G": 0, "M": 1000, "P": 1.0, "k": 0.5, "h": 100,
    }
    r = EconomyEngine.run_islm(config)
    assert r["status"] == "invalid_solution"
    assert "equilibrio" not in r


def test_run_islm_curvas_gera_grades_IS_e_LM():
    config = {
        "aberta": False,
        "c0": 100, "c1": 0.75, "T": 200, "I0": 200, "b": 50,
        "G": 300, "M": 1000, "P": 1.0, "k": 0.5, "h": 100,
    }
    r = EconomyEngine.run_islm_curvas(config)
    assert len(r["Y_grid"]) == 200
    assert len(r["r_IS"]) == 200
    assert len(r["r_LM"]) == 200


def test_run_islm_curvas_propaga_invalid_solution_sem_gerar_grade():
    cfg.ECONOMIC_VALIDATION_MODE = "fail_fast"
    config = {
        "aberta": False,
        "c0": -100000, "c1": 0.5, "T": 0, "I0": 0, "b": 50,
        "G": 0, "M": 1000, "P": 1.0, "k": 0.5, "h": 100,
    }
    r = EconomyEngine.run_islm_curvas(config)
    assert r["status"] == "invalid_solution"
    assert "Y_grid" not in r
