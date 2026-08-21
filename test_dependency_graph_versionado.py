"""
Testes do grafo de dependências versionado (services/dependency_graph.py:
resolver_grafo_versionado) — a peça que falta em relação a
test_dependency_graph.py: aqui `depende_de` referencia `funcao_id`
(identidade estável), mas o nó do grafo é `funcao_versao_id` (a versão
exata pinada por uma modelo_versao). Cobre especificamente o passo de
resolução funcao_id -> funcao_versao_id, incluindo o caso de erro quando
o funcao_id referenciado não está presente no payload.
"""
from types import SimpleNamespace

import pytest

from services.dependency_graph import (
    resolver_grafo_versionado,
    ordenar_topologicamente,
    DependenciaNaoResolvidaError,
)


def f(funcao_id: str, funcao_versao_id: str, depende_de: list[str] | None = None):
    return SimpleNamespace(
        funcao_id=funcao_id,
        funcao_versao_id=funcao_versao_id,
        depende_de=depende_de or [],
    )


def test_resolve_depende_de_funcao_id_para_funcao_versao_id_certo():
    # b (versao vb) depende de a (funcao_id "a") -> aresta deve virar "va", nao "a"
    grafo = resolver_grafo_versionado([
        f("a", "va"),
        f("b", "vb", depende_de=["a"]),
    ])
    assert set(grafo.keys()) == {"va", "vb"}
    assert grafo["vb"].depends_on == ["va"]
    assert grafo["va"].depends_on == []


def test_ordem_topologica_usa_funcao_versao_id_como_no():
    grafo = resolver_grafo_versionado([
        f("a", "va"),
        f("b", "vb", depende_de=["a"]),
        f("c", "vc", depende_de=["b"]),
    ])
    ordem, ciclos = ordenar_topologicamente(grafo)
    assert ciclos == []
    assert ordem.index("va") < ordem.index("vb") < ordem.index("vc")


def test_ciclo_entre_funcao_id_vira_ciclo_entre_funcao_versao_id():
    grafo = resolver_grafo_versionado([
        f("a", "va", depende_de=["b"]),
        f("b", "vb", depende_de=["a"]),
    ])
    ordem, ciclos = ordenar_topologicamente(grafo)
    assert ordem == []
    assert len(ciclos) == 1
    assert set(ciclos[0]) == {"va", "vb"}


def test_auto_referencia_por_funcao_id_e_ignorada():
    grafo = resolver_grafo_versionado([f("a", "va", depende_de=["a"])])
    assert grafo["va"].depends_on == []
    ordem, ciclos = ordenar_topologicamente(grafo)
    assert ordem == ["va"]
    assert ciclos == []


def test_dependencia_para_funcao_id_ausente_levanta_erro():
    """Snapshot incompleto: depende_de referencia um funcao_id que não
    está entre as funções deste payload (não é o mesmo caso de
    construir_grafo, que ignora id inexistente silenciosamente — aqui o
    payload é fechado por construção e a referência sem par é um erro,
    não "sem dependência")."""
    with pytest.raises(DependenciaNaoResolvidaError) as exc_info:
        resolver_grafo_versionado([
            f("a", "va", depende_de=["fantasma"]),
        ])
    assert exc_info.value.funcao_id_origem == "a"
    assert exc_info.value.funcao_id_ausente == "fantasma"
    assert "a" in str(exc_info.value) and "fantasma" in str(exc_info.value)


def test_dependencia_ausente_e_detectada_mesmo_com_outras_funcoes_validas():
    # garante que o erro nao depende de ser o unico item da lista
    with pytest.raises(DependenciaNaoResolvidaError):
        resolver_grafo_versionado([
            f("a", "va"),
            f("b", "vb", depende_de=["a", "fantasma"]),
        ])
