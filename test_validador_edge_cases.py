"""
Casos de borda de services/validador.py não cobertos por test_engine.py
(que só exercita os casos canônicos felizes via EconomyEngine) nem por
test_modelo_proprio_routes.py: as identidades estruturais Qd=Qs e Md=Ms
(só Y=C+I+G tinha teste), validar_solucao (camada de consistência por
equação) e normalizar_sistema (função exportada, real, mas não chamada
por nenhum código de produção hoje — verificado via grep; testada aqui
mesmo assim porque é lógica pública e documentada).
"""
from types import SimpleNamespace

from services.validador import (
    validar_consistencia_estrutural,
    validar_solucao,
    normalizar_sistema,
    validar_restricoes_economicas,
)


def eq(variavel="", expressao=""):
    return SimpleNamespace(variavel=variavel, expressao=expressao)


# ── validar_consistencia_estrutural — Qd=Qs, Md=Ms ────────────────────

def test_consistencia_qd_qs_bate():
    erros = validar_consistencia_estrutural({"Qd": 50.0, "Qs": 50.0})
    assert erros == []


def test_consistencia_qd_qs_nao_bate():
    erros = validar_consistencia_estrutural({"Qd": 50.0, "Qs": 45.0})
    assert len(erros) == 1
    assert erros[0]["identidade"] == "Qd = Qs"
    assert erros[0]["diff"] == 5.0


def test_consistencia_md_ms_bate():
    erros = validar_consistencia_estrutural({"Md": 1000.0, "Ms": 1000.0})
    assert erros == []


def test_consistencia_md_ms_nao_bate():
    erros = validar_consistencia_estrutural({"Md": 1000.0, "Ms": 950.0})
    assert len(erros) == 1
    assert erros[0]["identidade"] == "Md = Ms"


def test_consistencia_multiplas_identidades_simultaneas():
    """Y!=C+I+G E Qd!=Qs ao mesmo tempo -- as duas verificações são
    independentes, ambas aparecem na lista de erros."""
    erros = validar_consistencia_estrutural({
        "Y": 1000.0, "C": 500.0, "I": 200.0, "G": 200.0,  # 1000 != 900
        "Qd": 10.0, "Qs": 20.0,
    })
    identidades = {e["identidade"] for e in erros}
    assert identidades == {"Y = C + I + G", "Qd = Qs"}


def test_consistencia_sem_variaveis_suficientes_nao_verifica():
    """Só Qd presente (sem Qs) -- identidade não é verificada, sem erro
    nem exceção."""
    assert validar_consistencia_estrutural({"Qd": 50.0}) == []


# ── validar_solucao — consistência por equação ─────────────────────────

def test_validar_solucao_sem_solucao_numerica_retorna_vazio():
    assert validar_solucao([eq("Y", "100")], {}) == []


def test_validar_solucao_equacao_malformada_e_ignorada():
    """Equação sem variavel nem '=' na expressão -- lhs/rhs vazios, pulada
    sem quebrar a verificação das demais."""
    erros = validar_solucao(
        [eq(variavel="", expressao=""), eq("Y", "100")],
        {"Y": 100.0},
    )
    assert erros == []


def test_validar_solucao_detecta_inconsistencia():
    """Equação Y=100 mas a 'solução' fornecida diz Y=999 -- recalcular a
    equação com a solução não bate, deve aparecer em erros."""
    erros = validar_solucao([eq("Y", "100")], {"Y": 999.0})
    assert len(erros) == 1
    assert "Y = 100" in erros[0]
    assert "999" in erros[0]


def test_validar_solucao_equacao_com_simbolo_livre_e_pulada():
    """Equação envolvendo uma variável que não está na solução fornecida
    (símbolo livre após substituição) -- sympify/evalf falha, capturado
    por `except Exception: pass`, sem entrar em erros."""
    erros = validar_solucao([eq("Y", "C + 100")], {"Y": 100.0})  # falta 'C'
    assert erros == []


# ── normalizar_sistema — dedup simbólico (não chamada em produção hoje) ─

def test_normalizar_sistema_remove_duplicata_simbolica():
    normalizadas = normalizar_sistema([
        eq("Y", "C + I"),
        eq("", "Y - C - I = 0"),  # mesma equação, forma diferente
    ])
    assert len(normalizadas) == 1


def test_normalizar_sistema_ignora_equacao_vazia():
    normalizadas = normalizar_sistema([eq(variavel="", expressao=""), eq("Y", "100")])
    assert len(normalizadas) == 1
    assert normalizadas[0] == "Y = 100"


def test_normalizar_sistema_expressao_invalida_usa_fallback_textual():
    """sympify falha (sintaxe inválida) -- cai no fallback 'lhs=rhs' cru
    em vez de propagar a exceção, e ainda assim entra na lista (uma vez)."""
    normalizadas = normalizar_sistema([eq("Y", "))) invalido (((")])
    assert len(normalizadas) == 1


# ── validar_restricoes_economicas — ignora valores não numéricos ──────

def test_restricoes_ignora_valor_nao_numerico():
    """Solução pode ter valores simbólicos (string) quando o sistema é
    subdeterminado -- essas entradas são puladas na checagem de
    restrições em vez de comparar string com número."""
    resultado = validar_restricoes_economicas({"Y": "C + 100"}, modo="warning")
    assert resultado["valid"] is True
    assert resultado["violations"] == []
