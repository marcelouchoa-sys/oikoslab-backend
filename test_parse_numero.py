"""
Testes de services/parse_numero.py -- parsing de número em formato
brasileiro (ponto = milhar, vírgula = decimal).

Bug real que motivou este arquivo: população de Seropédica (Censo 2022)
= 80.596 habitantes (formato BR, ponto = milhar). `float("80.596")`
puro dá 80.596 (~80) em vez de 80596 -- usado num cálculo de PIB per
capita = PIB*1000/Pop, isso infla o resultado em ~1000x.
"""
import pytest

from services.parse_numero import parse_numero_br


# ── caso real que motivou o fix ──────────────────────────────────────

def test_populacao_seropedica_formato_br_thousands():
    """O caso exato do bug reportado: "80.596" tem que virar 80596.0,
    não 80.596."""
    assert parse_numero_br("80.596") == 80596.0


def test_pib_seropedica_formato_br_thousands():
    assert parse_numero_br("3.760.076") == 3760076.0


# ── decimais legítimos NÃO podem virar milhar (regressão crítica) ────
# Essas são casos de uso reais e frequentes no resto do app -- "0.75" é
# literalmente o valor padrão de propensão marginal a consumir usado em
# quase todo teste do projeto.

def test_propensao_marginal_a_consumir_continua_decimal():
    assert parse_numero_br("0.75") == 0.75


def test_taxa_desemprego_sidra_continua_decimal():
    """Valor real que já vem do SIDRA (tabela 6381) -- não pode virar
    5400 por engano."""
    assert parse_numero_br("5.4") == 5.4


def test_decimal_com_duas_casas_continua_decimal():
    assert parse_numero_br("100.5") == 100.5


# ── formato BR completo (milhar + decimal) ───────────────────────────

def test_formato_br_completo_milhar_e_decimal():
    assert parse_numero_br("1.234,56") == 1234.56


def test_decimal_br_com_virgula_sem_milhar():
    assert parse_numero_br("5,4") == 5.4


# ── outros formatos e edge cases ─────────────────────────────────────

def test_numero_puro_sem_separador():
    assert parse_numero_br("80596") == 80596.0


def test_negativo_com_milhar():
    assert parse_numero_br("-80.596") == -80596.0


def test_multiplos_grupos_de_milhar():
    assert parse_numero_br("1.234.567") == 1234567.0


def test_int_e_float_passam_direto_sem_ambiguidade():
    assert parse_numero_br(80596) == 80596.0
    assert parse_numero_br(0.75) == 0.75


def test_none_e_string_vazia_viram_none():
    assert parse_numero_br(None) is None
    assert parse_numero_br("") is None
    assert parse_numero_br("   ") is None


def test_texto_invalido_levanta_value_error():
    with pytest.raises(ValueError):
        parse_numero_br("abc")
