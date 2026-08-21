"""
Teste do ponto de integração mínimo entre o grafo de dependências
versionado e o EconomyEngine (item 3 da Fase 3 — bloquear o solve quando
há ciclo entre `Funcao`, antes de deixar sp.solve() tentar e falhar de
forma menos clara; e o passo de resolução funcao_id -> funcao_versao_id
que precede a detecção de ciclo — ver services/dependency_graph.py).
"""
from types import SimpleNamespace

from services.economy_engine import EconomyEngine


def eq(variavel, expressao, nome=""):
    return SimpleNamespace(variavel=variavel, expressao=expressao, nome=nome)


def funcao(funcao_id, funcao_versao_id=None, nome="", depende_de=None):
    """`depende_de` referencia `funcao_id` de outras funções (nunca
    funcao_versao_id — ver FuncaoVersionada em dependency_graph.py).
    `funcao_versao_id` default facilita os testes que não se importam com
    o valor exato da versão, só com a resolução acontecer."""
    return SimpleNamespace(
        funcao_id=funcao_id,
        funcao_versao_id=funcao_versao_id or f"{funcao_id}-v1",
        nome=nome,
        depende_de=depende_de or [],
    )


def test_sem_funcoes_grafo_comportamento_inalterado():
    """Nenhum call site atual passa funcoes_grafo — precisa continuar
    funcionando exatamente como antes quando o parâmetro não é usado."""
    r = EconomyEngine.run(
        [eq("C", "a + c*(Y-T)"), eq("Y", "C + I0 + G0")],
        {"a": 100, "c": 0.75, "T": 200, "I0": 200, "G0": 300},
    )
    assert r["status"] == "ok"


def test_funcoes_grafo_sem_ciclo_nao_bloqueia():
    r = EconomyEngine.run(
        [eq("C", "a + c*(Y-T)"), eq("Y", "C + I0 + G0")],
        {"a": 100, "c": 0.75, "T": 200, "I0": 200, "G0": 300},
        funcoes_grafo=[
            funcao("f1", "vf1", "Consumo"),
            funcao("f2", "vf2", "Produto", depende_de=["f1"]),
        ],
    )
    assert r["status"] == "ok"


def test_funcoes_grafo_com_ciclo_bloqueia_antes_do_solve():
    r = EconomyEngine.run(
        [eq("C", "a + c*(Y-T)"), eq("Y", "C + I0 + G0")],
        {"a": 100, "c": 0.75, "T": 200, "I0": 200, "G0": 300},
        funcoes_grafo=[
            funcao("f1", "vf1", "Receita", depende_de=["f2"]),
            funcao("f2", "vf2", "Preco", depende_de=["f1"]),
        ],
    )
    assert r["status"] == "invalid_solution"
    assert r["economia"]["valid"] is False
    assert len(r["ciclos"]) == 1
    # ciclos contêm funcao_versao_id (nó do grafo versionado), não funcao_id
    assert set(r["ciclos"][0]) == {"vf1", "vf2"}
    assert "Receita" in r["errors"][0] and "Preco" in r["errors"][0]
    # nenhum valor numerico da solucao deve vazar
    assert "valores" not in r


def test_funcoes_grafo_dependencia_nao_resolvida_bloqueia_antes_do_solve():
    """`depende_de` referenciando um funcao_id ausente do funcoes_grafo é
    um snapshot de modelo_versao incompleto — bloqueia antes do solve com
    o mesmo formato estruturado de erro, sem deixar a exceção vazar pra
    quem chama run()."""
    r = EconomyEngine.run(
        [eq("C", "a + c*(Y-T)"), eq("Y", "C + I0 + G0")],
        {"a": 100, "c": 0.75, "T": 200, "I0": 200, "G0": 300},
        funcoes_grafo=[
            funcao("f1", "vf1", "Receita", depende_de=["f2"]),  # f2 nao esta na lista
        ],
    )
    assert r["status"] == "invalid_solution"
    assert r["economia"]["valid"] is False
    assert r["economia"]["errors"][0]["tipo"] == "dependencia_nao_resolvida"
    assert "f1" in r["errors"][0] and "f2" in r["errors"][0]
    assert "valores" not in r
