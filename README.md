# OikosLab — Backend (FastAPI)

API do simulador de modelos econômicos (Camada 2 do OikosLab). Deploy em produção: **Railway**.

> `CLAUDE.md` nesta pasta está com conteúdo de outro projeto (uma SaaS de
> arquitetura) — não reflete este backend. Use este README como referência
> real até isso ser corrigido.

## Rodar localmente

```powershell
cd oikoslab-platform\backend
.\venv\Scripts\activate
uvicorn main:app --reload --port 8000
```

Confirma que subiu vendo `Application startup complete` — API fica em `http://localhost:8000`.

## CORS

`main.py` define as origins permitidas no `CORSMiddleware`. Hoje:
`http://localhost:3000`, `http://127.0.0.1:3000` (dev local) e
`https://oikoslab-platform.vercel.app` (produção). Se o frontend rodar em
outra porta/host, adicione aqui — nunca use `"*"` em produção.

## Deploy (produção)

Repositório GitHub separado: `oikoslab-backend`, branch `main`, deploy no **Railway**.

```powershell
cd oikoslab-platform\backend
git add caminho\do\arquivo
git commit -m "mensagem"
git push origin main
```

⚠️ **Nunca rode comandos `git` a partir da pasta raiz `OIKOSLABOFICIAL\`.**
Essa pasta é, ela mesma, um repositório git com o **mesmo remote**
(`oikoslab-backend.git`), mas com uma história completamente divergente
(commits de frontend — login, dashboard — sem nenhuma relação com o
backend real). Um push feito de lá seria rejeitado (non-fast-forward) ou,
se forçado, sobrescreveria a história real do backend no GitHub. Sempre
`cd oikoslab-platform\backend` antes de qualquer `git add/commit/push`.

## Testes

```powershell
.\venv\Scripts\python.exe -m pytest
.\venv\Scripts\python.exe test_engine.py
```
