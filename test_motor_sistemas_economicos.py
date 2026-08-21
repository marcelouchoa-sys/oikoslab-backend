"""
Testes de routers/motor_sistemas_economicos.py — 0% de cobertura porque
o módulo NÃO está registrado em main.py (nenhum `app.include_router`
correspondente, confirmado por grep). Não é um router HTTP de verdade
apesar do nome/pasta — é um conjunto de funções puras (resolve_sistema,
_to_equacao, _detectar_variaveis) só exercitadas hoje via
`python -m routers.motor_sistemas_economicos` (bloco __main__). Testado
aqui mesmo assim: é lógica real, só não está conectada a nenhuma rota.
"""
import pytest
import sympy as sp

from routers.motor_sistemas_economicos import resolve_sistema, _to_equacao, _detectar_variaveis


# ── _to_equacao ────────────────────────────────────────────────────────

def test_to_equacao_com_eq_sympy():
    Y, C = sp.symbols("Y C")
    resultado = _to_equacao(sp.Eq(Y, C + 100))
    assert resultado.expressao == "Y = C + 100"


def test_to_equacao_sem_eq_interpreta_como_igual_a_zero():
    Y = sp.Symbol("Y")
    resultado = _to_equacao(Y - 100)
    assert resultado.expressao == "0 = Y - 100"


# ── _detectar_variaveis ─────────────────────────────────────────────────

def test_detectar_variaveis_sem_variaveis_explicitas_usa_contexto():
    Y, C, T = sp.symbols("Y C T")
    equacoes = [sp.Eq(Y, C + T)]
    endogenas, exogenas = _detectar_variaveis(equacoes, None, {"T": 200})
    assert [str(s) for s in endogenas] == ["C", "Y"]
    assert [str(s) for s in exogenas] == ["T"]


def test_detectar_variaveis_explicitas_tem_prioridade():
    Y, C = sp.symbols("Y C")
    endogenas, exogenas = _detectar_variaveis([sp.Eq(Y, C)], [Y], {"C": 10})
    assert endogenas == [Y]
    assert exogenas == [C]


# ── resolve_sistema — delega pro EconomyEngine ─────────────────────────

def test_resolve_sistema_lista_vazia():
    r = resolve_sistema([])
    assert r["solucao"] == {}
    assert r["erros"] == ["Lista de equações vazia."]


def test_resolve_sistema_oferta_demanda():
    P, Qd, Qs = sp.symbols("P Qd Qs")
    r = resolve_sistema([
        sp.Eq(Qd, 100 - 2 * P),
        sp.Eq(Qs, 20 + 3 * P),
        sp.Eq(Qd, Qs),
    ])
    assert r["tipo"] == "sistema"
    assert r["solucao"]["P"] == 16.0
    assert r["solucao"]["Qd"] == 68.0


def test_resolve_sistema_equacao_unica_com_contexto():
    Y, c, Inv, G, T = sp.symbols("Y c Inv G T")
    r = resolve_sistema(
        [sp.Eq(Y, c * (Y - T) + Inv + G)],
        contexto={"c": 0.75, "Inv": 200, "G": 300, "T": 200},
    )
    assert r["tipo"] == "equacao_unica"
    assert r["solucao"]["Y"] == pytest.approx(1400.0, rel=1e-2)


def test_resolve_sistema_islm_simplificado():
    # 800 - 40r = 400 + 20r  =>  60r = 400  =>  r = 6.667, Y = 533.33
    r2, Y2 = sp.symbols("r Y")
    r = resolve_sistema([
        sp.Eq(Y2, 800 - 40 * r2),
        sp.Eq(Y2, 400 + 20 * r2),
    ])
    assert r["solucao"]["Y"] == pytest.approx(533.33, rel=1e-2)
    assert r["solucao"]["r"] == pytest.approx(6.667, rel=1e-2)


def test_resolve_sistema_bloqueio_economico_propaga():
    """Y negativo -- o hard gate do EconomyEngine bloqueia mesmo passando
    por este adaptador, resultado vem sem 'solucao' numérica."""
    Y = sp.Symbol("Y")
    r = resolve_sistema([sp.Eq(Y, -5000)])
    assert r["economia"]["valid"] is False
