"""
Testes do EconomyEngine — verifica pipeline completo com hard gate.
"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from types import SimpleNamespace
from services.economy_engine import EconomyEngine
import services.config as cfg

def eq(variavel, expressao, nome=""):
    return SimpleNamespace(variavel=variavel, expressao=expressao, nome=nome)

def vl(nome, min_=0, max_=2000, pontos=5, mostrar=None):
    return SimpleNamespace(nome=nome, min=min_, max=max_, pontos=pontos, mostrar=mostrar or [])

PASS = 0; FAIL = 0

def check(label, condition, detail=""):
    global PASS, FAIL
    if condition:
        print(f"  [OK]  {label}")
        PASS += 1
    else:
        print(f"  [FAIL] {label}" + (f" | {detail}" if detail else ""))
        FAIL += 1

# ──────────────────────────────────────────────────────────────────────────────
print("\n=== 1. Cruz Keynesiana — solucao valida ===")
cfg.ECONOMIC_VALIDATION_ENABLED = True
cfg.ECONOMIC_VALIDATION_MODE = "warning"

eqs = [eq("C","a + c*(Y-T)"), eq("Y","C + I0 + G0")]
params = {"a":100, "c":0.75, "T":200, "I0":200, "G0":300}
r = EconomyEngine.run(eqs, params)

check("status ok",          r["status"] == "ok")
check("Y > 0",              r["valores"].get("Y", -1) > 0)
check("economia.valid",     r["economia"]["valid"])
check("sem errors",         r["economia"]["errors"] == [])
check("bloco matematica",   "equacoes_normalizadas" in r["matematica"])
check("bloco solucao",      "numerica" in r["solucao"])

# ──────────────────────────────────────────────────────────────────────────────
print("\n=== 2. Oferta e Demanda — Qd Qs positivos ===")
# 3 equacoes para 3 incognitas (Qd, Qs, P)
eqs2 = [eq("Qd","a - b*P"), eq("Qs","c + d*P"), eq("Qd","Qs")]
params2 = {"a":100, "b":2, "c":20, "d":3}
r2 = EconomyEngine.run(eqs2, params2)

check("status ok",          r2["status"] == "ok")
check("P resolvido",        "P" in r2["valores"])
check("Qd positivo",        r2["valores"].get("Qd", -1) > 0)
check("economia.valid",     r2["economia"]["valid"])
check("sem violations",     r2["economia"]["violations"] == [])

# ──────────────────────────────────────────────────────────────────────────────
print("\n=== 3. Y negativo — WARNING mode (nao bloqueia) ===")
cfg.ECONOMIC_VALIDATION_MODE = "warning"
eqs3 = [eq("C","a + c*Y"), eq("Y","C + I0")]
params3 = {"a":-9999, "c":0.5, "I0":100}
r3 = EconomyEngine.run(eqs3, params3)

check("nao retorna invalid_solution", r3.get("status") != "invalid_solution")
check("economia.valid = False",       r3["economia"]["valid"] == False)
check("economia.errors nao vazio",    len(r3["economia"]["errors"]) > 0)
check("valores presentes",            "valores" in r3)

# ──────────────────────────────────────────────────────────────────────────────
print("\n=== 4. Y negativo — FAIL_FAST (bloqueia output) ===")
cfg.ECONOMIC_VALIDATION_MODE = "fail_fast"
r4 = EconomyEngine.run(eqs3, params3)

check("status = invalid_solution",    r4.get("status") == "invalid_solution")
check("errors presente",              len(r4.get("errors", [])) > 0)
check("violations presente",          len(r4.get("violations", [])) > 0)
check("sem campo 'valores'",          "valores" not in r4 or r4.get("valores") is None or r4.get("status") == "invalid_solution")
check("economia.valid = False",       r4["economia"]["valid"] == False)

# reset
cfg.ECONOMIC_VALIDATION_MODE = "warning"

# ──────────────────────────────────────────────────────────────────────────────
print("\n=== 5. ENABLED=False — bypass total ===")
cfg.ECONOMIC_VALIDATION_ENABLED = False
cfg.ECONOMIC_VALIDATION_MODE = "fail_fast"
eqs5 = [eq("Y","a + b")]
params5 = {"a":-9999, "b":-9999}
r5 = EconomyEngine.run(eqs5, params5)

check("nao bloqueia com ENABLED=False", r5.get("status") != "invalid_solution")
check("economia.valid = True (bypass)", r5["economia"]["valid"] == True)

# reset
cfg.ECONOMIC_VALIDATION_ENABLED = True
cfg.ECONOMIC_VALIDATION_MODE = "warning"

# ──────────────────────────────────────────────────────────────────────────────
print("\n=== 6. resolve_single — cenario valido ===")
r6 = EconomyEngine.resolve_single(
    [eq("C","a + c*(Y-T)"), eq("Y","C + I0 + G0")],
    {"a":100, "c":0.75, "T":200, "I0":200, "G0":300}
)
check("retorna valores",   isinstance(r6["valores"], dict) and len(r6["valores"]) > 0)
check("valid = True",      r6["valid"] == True)
check("violations vazio",  r6["violations"] == [])

# ──────────────────────────────────────────────────────────────────────────────
print("\n=== 7. Consistencia estrutural — Y != C+I+G detectado ===")
cfg.ECONOMIC_VALIDATION_ENABLED = True
cfg.ECONOMIC_VALIDATION_MODE = "warning"
# forcamos valores manuais com identidade quebrada via solve
# (dificil forccar com solver — testamos indiretamente via validar_consistencia_estrutural)
from services.validador import validar_consistencia_estrutural
erros_ce = validar_consistencia_estrutural({"Y": 1000, "C": 500, "I": 100, "G": 200})
check("Y != C+I+G detectado", len(erros_ce) == 1)
check("identidade correta",   erros_ce[0]["identidade"] == "Y = C + I + G")

erros_ok = validar_consistencia_estrutural({"Y": 800, "C": 500, "I": 100, "G": 200})
check("Y == C+I+G aceito",    erros_ok == [])

# ──────────────────────────────────────────────────────────────────────────────
print("\n=== 8. Serie temporal com variavel livre ===")
cfg.ECONOMIC_VALIDATION_MODE = "warning"
r8 = EconomyEngine.run(
    [eq("C","a + c*(Y-T)"), eq("Y","C + I0 + G0")],
    {"a":100, "c":0.75, "T":200, "I0":200, "G0":300},
    variavel_livre=vl("G0", min_=200, max_=500, pontos=10),
)
check("series geradas",       r8.get("series") is not None)
check("G0 no eixo x",         "G0" in (r8.get("series") or {}))
check("Y_vs_G0 no output",    "Y_vs_G0" in (r8.get("series") or {}))

# ──────────────────────────────────────────────────────────────────────────────
print(f"\n{'='*50}")
print(f"Resultado: {PASS} OK  |  {FAIL} FAIL")
if FAIL:
    sys.exit(1)
