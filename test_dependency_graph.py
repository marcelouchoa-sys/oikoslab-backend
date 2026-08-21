"""
Testes do grafo de dependências (services/dependency_graph.py).

Espelha os casos que fariam sentido testar em
frontend/lib/dependency-graph.ts (não havia testes automatizados do lado
TypeScript no repo — nenhum arquivo *.test.ts para dependency-graph.ts foi
encontrado; estes cobrem os mesmos casos que o algoritmo precisa suportar).
"""
from types import SimpleNamespace

from services.dependency_graph import (
    construir_grafo,
    ordenar_topologicamente,
    detectar_ciclos,
)


def f(id: str, depende_de: list[str] | None = None):
    return SimpleNamespace(id=id, depende_de=depende_de or [])


def test_grafo_vazio():
    grafo = construir_grafo([])
    ordem, ciclos = ordenar_topologicamente(grafo)
    assert ordem == []
    assert ciclos == []


def test_nos_desconectados():
    grafo = construir_grafo([f("a"), f("b"), f("c")])
    ordem, ciclos = ordenar_topologicamente(grafo)
    assert set(ordem) == {"a", "b", "c"}
    assert ciclos == []


def test_grafo_linear_simples():
    # c depende de b, b depende de a -> ordem deve resolver a antes de b antes de c
    grafo = construir_grafo([
        f("a"),
        f("b", ["a"]),
        f("c", ["b"]),
    ])
    ordem, ciclos = ordenar_topologicamente(grafo)
    assert ciclos == []
    assert ordem.index("a") < ordem.index("b") < ordem.index("c")


def test_auto_referencia_e_ignorada():
    grafo = construir_grafo([f("a", ["a"])])
    ordem, ciclos = ordenar_topologicamente(grafo)
    assert ordem == ["a"]
    assert ciclos == []


def test_dependencia_para_id_inexistente_e_ignorada():
    grafo = construir_grafo([f("a", ["fantasma"])])
    ordem, ciclos = ordenar_topologicamente(grafo)
    assert ordem == ["a"]
    assert ciclos == []


def test_ciclo_de_2_nos():
    grafo = construir_grafo([
        f("a", ["b"]),
        f("b", ["a"]),
    ])
    ordem, ciclos = ordenar_topologicamente(grafo)
    assert ordem == []  # nenhum nó do ciclo entra na ordem de cálculo
    assert len(ciclos) == 1
    assert set(ciclos[0]) == {"a", "b"}


def test_ciclo_de_3_ou_mais_nos():
    grafo = construir_grafo([
        f("a", ["c"]),
        f("b", ["a"]),
        f("c", ["b"]),
    ])
    ordem, ciclos = ordenar_topologicamente(grafo)
    assert ordem == []
    assert len(ciclos) == 1
    assert set(ciclos[0]) == {"a", "b", "c"}


def test_ciclo_parcial_nao_bloqueia_nos_independentes():
    # d nao participa do ciclo a<->b e deve entrar na ordem normalmente
    grafo = construir_grafo([
        f("a", ["b"]),
        f("b", ["a"]),
        f("d"),
    ])
    ordem, ciclos = ordenar_topologicamente(grafo)
    assert ordem == ["d"]
    assert len(ciclos) == 1
    assert set(ciclos[0]) == {"a", "b"}


def test_detectar_ciclos_direto_sem_ciclo():
    grafo = construir_grafo([f("a"), f("b", ["a"])])
    assert detectar_ciclos(grafo) == []


def test_detectar_ciclos_ignora_dependencia_dangling_dentro_do_ciclo():
    """Nó em ciclo que TAMBÉM tem uma dependência pra um id inexistente —
    cobre o `continue` de detectar_ciclos quando o dangling aparece
    justamente no caminho de DFS que já está detectando o ciclo real
    (diferente de test_dependencia_para_id_inexistente_e_ignorada, que não
    tem ciclo nenhum — lá ordenar_topologicamente nunca chega a chamar
    detectar_ciclos, porque Kahn já resolve tudo sem sobra)."""
    grafo = construir_grafo([
        f("a", ["b", "fantasma"]),
        f("b", ["a"]),
    ])
    ciclos = detectar_ciclos(grafo)
    assert len(ciclos) == 1
    assert set(ciclos[0]) == {"a", "b"}


def test_tres_funcoes_reais_sem_ciclo_regressao():
    """
    Regressão: Consumo depende de nada externo à sua expressão (a, c, T sao
    parametros, nao Funcao), Investimento e Governo idem — nenhuma Funcao
    referencia outra Funcao. Espera-se grafo totalmente desconectado, sem
    ciclos. Ver relatório de validação manual para os dados reais do banco.
    """
    grafo = construir_grafo([
        f("consumo"),
        f("investimento"),
        f("governo"),
    ])
    ordem, ciclos = ordenar_topologicamente(grafo)
    assert set(ordem) == {"consumo", "investimento", "governo"}
    assert ciclos == []
