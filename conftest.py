"""
Fixtures compartilhadas entre os testes do backend. Criado na segunda vez
que precisei mockar `httpx.AsyncClient` sem bater em rede de verdade
(primeira vez foi ad-hoc em test_economia_real_sidra.py, que continua
com seu próprio mock local — não mexido, já funcionava).
"""
import pytest


class _RespostaHttpFake:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class _ClientHttpFake:
    """Simula httpx.AsyncClient — sempre devolve o mesmo payload/status,
    não importa a URL chamada. Suficiente pra rotas que fazem N chamadas
    em sequência (ex: /economia-real/dados, um GET por indicador) quando
    o teste não precisa diferenciar uma chamada da outra."""

    def __init__(self, payload, status_code=200):
        self._payload = payload
        self._status_code = status_code

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url):
        return _RespostaHttpFake(self._payload, self._status_code)


@pytest.fixture
def mockar_httpx(monkeypatch):
    """`mockar_httpx(modulo, payload, status_code=200)` — substitui
    `modulo.httpx.AsyncClient` por um fake determinístico, sem rede real."""

    def usar(modulo, payload, status_code=200):
        monkeypatch.setattr(
            modulo.httpx, "AsyncClient", lambda timeout=None: _ClientHttpFake(payload, status_code)
        )

    return usar
