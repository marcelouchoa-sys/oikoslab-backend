"""
Parsing de número em formato brasileiro (ponto = separador de milhar,
vírgula = separador decimal) — ponto único de conversão texto->número
pra qualquer valor numérico de parâmetro que possa chegar como string.

Motivado por um bug real: população de Seropédica (Censo 2022) digitada/
armazenada como "80.596" sendo parseada por `float()` puro como 80.596
(~80) em vez de 80596 -- inflava em ~1000x qualquer cálculo que usasse
esse parâmetro (ex: PIB per capita = PIB*1000/Pop).
"""
import re

_GRUPOS_MILHAR = re.compile(r"^-?\d{1,3}(\.\d{3})+$")


def parse_numero_br(valor: str | int | float | None) -> float | None:
    """
    Converte um valor numérico (possivelmente em formato BR) pra float.

    - `int`/`float` passam direto (já são números, sem ambiguidade).
    - `None` ou string vazia -> None.
    - Contém vírgula -> formato BR completo: ponto é milhar (removido),
      vírgula é decimal (vira ponto). "1.234,56" -> 1234.56.
    - Sem vírgula, mas os pontos dividem o texto em grupos de EXATAMENTE
      3 dígitos (padrão de agrupamento de milhar, ex: "80.596",
      "1.234.567") -> pontos são milhar, removidos. "80.596" -> 80596.0.
    - Sem vírgula e sem esse padrão de agrupamento (ex: "5.4", "0.75") ->
      é decimal comum, ponto mantido como está.
    - Qualquer outro texto -> deixa `float()` levantar ValueError (mesmo
      comportamento de antes pra entradas realmente inválidas).
    """
    if valor is None:
        return None
    if isinstance(valor, (int, float)):
        return float(valor)

    texto = valor.strip()
    if not texto:
        return None

    if "," in texto:
        return float(texto.replace(".", "").replace(",", "."))

    if _GRUPOS_MILHAR.match(texto):
        return float(texto.replace(".", ""))

    return float(texto)
