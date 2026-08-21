"""
Casos de borda de services/motor_sistemas.py (_resolve_sistema, núcleo
SymPy) não cobertos pelos testes existentes — chamado direto, sem passar
por EconomyEngine._parse (que já filtra equação vazia antes de chegar
aqui, então o `continue` de _resolve_sistema nunca era exercitado via o
pipeline completo).
"""
from types import SimpleNamespace

from services.motor_sistemas import _resolve_sistema, _split_equacao


def eq(variavel="", expressao=""):
    return SimpleNamespace(variavel=variavel, expressao=expressao)


# ── _split_equacao ──────────────────────────────────────────────────

def test_split_equacao_com_igual_na_expressao():
    lhs, rhs = _split_equacao(eq("", "Y = C + I"))
    assert lhs == "Y" and rhs == "C + I"


def test_split_equacao_sem_igual_usa_variavel():
    lhs, rhs = _split_equacao(eq("Y", "C + I"))
    assert lhs == "Y" and rhs == "C + I"


# ── _resolve_sistema — entrada malformada ──────────────────────────────

def test_resolve_sistema_ignora_equacao_com_lhs_e_rhs_vazios():
    """Chamada direta (fora do EconomyEngine, que já filtra isso em
    _parse) — _resolve_sistema também precisa lidar com entrada malformada
    sem quebrar, resolvendo só as equações válidas do sistema."""
    sol_num, sol_sym, erros = _resolve_sistema(
        [eq(variavel="", expressao=""), eq("Y", "100")],
        {},
        ["Y"],
    )
    assert sol_num == {"Y": 100.0}
    assert erros == []


def test_resolve_sistema_todas_equacoes_vazias():
    sol_num, sol_sym, erros = _resolve_sistema(
        [eq(variavel="", expressao="")],
        {},
        [],
    )
    assert sol_num == {}
    assert erros == ["Nenhuma equação válida."]


# ── _resolve_sistema — falha de solve simbólico E numérico (transcendental) ─

def test_resolve_sistema_transcendental_falha_simbolico_e_numerico():
    """Y = a*sin(Y) não tem solução fechada pro sympy.solve — nem
    simbolicamente (com 'a' livre) nem numericamente (a=2). Os dois
    try/except (solução simbólica, solução numérica) capturam
    NotImplementedError e reportam como erro em vez de propagar."""
    sol_num, sol_sym, erros = _resolve_sistema(
        [eq("", "Y = a*sin(Y)")],
        {"a": 2},
        ["Y"],
    )
    assert sol_num == {}
    assert sol_sym == {}
    assert any("simbólica falhou" in e for e in erros)
    assert any("numérica falhou" in e for e in erros)


# ── _resolve_sistema — múltiplas soluções (sistema subdeterminado) ────

def test_resolve_sistema_subdeterminado_retorna_parametrico():
    """Uma equação, duas incógnitas -- sympy resolve uma em função da
    outra (livre); sol_numerica guarda a expressão como string quando não
    dá pra avaliar pra float (variável livre sem valor)."""
    sol_num, sol_sym, erros = _resolve_sistema(
        [eq("", "Y = C + 100")],
        {},
        ["Y", "C"],
    )
    nomes_sol_sym = {str(k) for k in sol_sym}
    assert "Y" in nomes_sol_sym or "C" in nomes_sol_sym
    # pelo menos uma das incognitas fica simbolica (string) por falta de
    # segunda equação que a determine
    assert any(isinstance(v, str) for v in sol_num.values())
