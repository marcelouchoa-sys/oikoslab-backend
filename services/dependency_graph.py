"""
Grafo de dependências entre `Funcao` do Construtor de Funções.

Porte de frontend/lib/dependency-graph.ts (Kahn + DFS branco/cinza/preto)
para o backend. Opera sobre os mesmos campos que já existem em
`funcoes`/`funcao_versoes`: cada nó é o `id` de uma Funcao, e as arestas
vêm de `depende_de` (lista de ids de OUTRAS Funcao — nunca de nomes de
variável, essa resolução já acontece antes, no frontend, em
lib/parse-expressao.ts).

Camada de serviço pura — sem FastAPI/Pydantic, sem acesso a banco.
"""
from __future__ import annotations

from collections import deque
from typing import Protocol


class TemDependencias(Protocol):
    """Qualquer objeto com `.id` e `.depende_de` serve de entrada — não
    precisa ser um tipo específico (Pydantic model, SimpleNamespace, dict
    via atributo, etc.), mesma flexibilidade que motor_sistemas.py já usa
    para equações."""
    id: str
    depende_de: list[str]


class GraphNode:
    __slots__ = ("id", "depends_on")

    def __init__(self, id: str, depends_on: list[str]) -> None:
        self.id = id
        self.depends_on = depends_on


def construir_grafo(funcoes: list) -> dict[str, GraphNode]:
    """
    Monta o grafo de adjacência a partir de `.id` e `.depende_de` de cada
    função. Auto-referência é ignorada (mesma regra de
    dependency-graph.ts: buildGraph filtra `id !== f.id`).
    """
    grafo: dict[str, GraphNode] = {}
    for f in funcoes:
        depende_de = [d for d in (f.depende_de or []) if d != f.id]
        grafo[f.id] = GraphNode(f.id, depende_de)
    return grafo


class FuncaoVersionada(Protocol):
    """Nó do grafo para uma modelo_versao específica: identidade estável
    (`funcao_id`) + a versão EXATA pinada nesta modelo_versao
    (`funcao_versao_id` — ver modelo_versao_funcoes em
    0002_modelos_versionamento.sql). `depende_de` continua em `funcao_id`,
    nunca em funcao_versao_id — é assim que a expressão referencia outro
    bloco; a versão exata só é fixada pelo snapshot do modelo, não pela
    Funcao em si."""
    funcao_id: str
    funcao_versao_id: str
    depende_de: list[str]


class DependenciaNaoResolvidaError(Exception):
    """`depende_de` de uma Funcao referencia um `funcao_id` que não está
    presente nesta mesma lista.

    Diferente de um id inexistente em `construir_grafo` (que é
    silenciosamente ignorado): uma modelo_versao_funcoes é um snapshot
    fechado por construção (PK (modelo_versao_id, funcao_id)), então uma
    referência sem par correspondente no payload é sinal de snapshot
    incompleto — ignorá-la esconderia dependências (e possivelmente
    ciclos) reais em vez de só "não ter dependência".
    """

    def __init__(self, funcao_id_origem: str, funcao_id_ausente: str) -> None:
        self.funcao_id_origem = funcao_id_origem
        self.funcao_id_ausente = funcao_id_ausente
        super().__init__(
            f"depende_de de '{funcao_id_origem}' referencia funcao_id "
            f"'{funcao_id_ausente}', que não está presente nesta versão do modelo."
        )


def resolver_grafo_versionado(funcoes: list) -> dict[str, GraphNode]:
    """
    Monta o grafo de adjacência de uma modelo_versao: o nó é o
    `funcao_versao_id` (a versão exata pinada), a aresta é resolvida a
    partir de `depende_de` (lista de `funcao_id`) usando o mapa
    funcao_id -> funcao_versao_id do PRÓPRIO payload — nunca ambíguo,
    porque modelo_versao_funcoes garante no máximo uma versão por
    funcao_id dentro de uma mesma modelo_versao.

    Levanta DependenciaNaoResolvidaError se `depende_de` apontar pra um
    funcao_id ausente da lista. Auto-referência (funcao_id == seu próprio
    funcao_id) é ignorada, mesma regra de construir_grafo.
    """
    versao_por_funcao_id = {f.funcao_id: f.funcao_versao_id for f in funcoes}

    grafo: dict[str, GraphNode] = {}
    for f in funcoes:
        arestas: list[str] = []
        for dep_funcao_id in (f.depende_de or []):
            if dep_funcao_id == f.funcao_id:
                continue
            dep_versao_id = versao_por_funcao_id.get(dep_funcao_id)
            if dep_versao_id is None:
                raise DependenciaNaoResolvidaError(f.funcao_id, dep_funcao_id)
            arestas.append(dep_versao_id)
        grafo[f.funcao_versao_id] = GraphNode(f.funcao_versao_id, arestas)
    return grafo


def ordenar_topologicamente(grafo: dict[str, GraphNode]) -> tuple[list[str], list[list[str]]]:
    """
    Algoritmo de Kahn — mesma lógica de dependency-graph.ts:topologicalSort.

    Retorna (ordem, ciclos). `ordem` só inclui nós sem ciclo; o que sobra
    (nós presos em dependência circular) é devolvido em `ciclos` e NÃO
    entra na ordem de cálculo.
    """
    in_degree: dict[str, int] = {node_id: 0 for node_id in grafo}
    dependentes: dict[str, list[str]] = {node_id: [] for node_id in grafo}

    for node in grafo.values():
        for dep in node.depends_on:
            if dep not in grafo:
                continue
            in_degree[node.id] += 1
            dependentes[dep].append(node.id)

    fila: deque[str] = deque(
        node_id for node_id, grau in in_degree.items() if grau == 0
    )
    ordem: list[str] = []
    while fila:
        node_id = fila.popleft()
        ordem.append(node_id)
        for dependente in dependentes.get(node_id, []):
            in_degree[dependente] -= 1
            if in_degree[dependente] == 0:
                fila.append(dependente)

    resolvidos = set(ordem)
    restantes = [node_id for node_id in grafo if node_id not in resolvidos]
    ciclos = detectar_ciclos(grafo) if restantes else []
    return ordem, ciclos


def detectar_ciclos(grafo: dict[str, GraphNode]) -> list[list[str]]:
    """
    DFS com coloração branco/cinza/preto — mesma lógica de
    dependency-graph.ts:detectCycles. Cada ciclo encontrado é devolvido
    como lista de ids na ordem em que aparecem na pilha de recursão.
    """
    BRANCO, CINZA, PRETO = 0, 1, 2
    cor: dict[str, int] = {}
    ciclos: list[list[str]] = []
    pilha: list[str] = []

    def visitar(node_id: str) -> None:
        cor[node_id] = CINZA
        pilha.append(node_id)
        for dep in grafo[node_id].depends_on:
            if dep not in grafo:
                continue
            c = cor.get(dep, BRANCO)
            if c == BRANCO:
                visitar(dep)
            elif c == CINZA:
                idx = pilha.index(dep)
                ciclos.append(list(pilha[idx:]))
        pilha.pop()
        cor[node_id] = PRETO

    for node_id in grafo:
        if cor.get(node_id, BRANCO) == BRANCO:
            visitar(node_id)

    return ciclos
