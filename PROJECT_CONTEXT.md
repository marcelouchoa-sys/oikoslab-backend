# PROJECT_CONTEXT.md — OikosLab Platform

> Documento de referência técnica da plataforma. Gerado em 2026-07-02.
> Cobre: `oikoslab-platform/frontend/` e `oikoslab-platform/backend/`.

---

## 1. Visão Geral

OikosLab é uma plataforma de simulação macroeconômica, projeto de graduação de Marcelo de Salles Cunha Uchôa (Economia, UFRRJ). É composta por **duas camadas independentes**:

| Camada | Tecnologia | Deploy | Propósito |
|--------|-----------|--------|-----------|
| Laboratório Didático | Streamlit (Python) | Streamlit Cloud | Simuladores abertos, sem login |
| Plataforma Econômica | Next.js + FastAPI | Vercel + Railway | Ambiente autenticado com projetos salvos |

Este documento cobre **exclusivamente a Plataforma Econômica**.

---

## 2. Arquitetura Geral

```
Browser
  │
  ├── Next.js (Vercel)          ← frontend
  │     ├── App Router
  │     ├── Supabase Client     ← auth + dados de projetos
  │     └── lib/api.ts          ← cliente HTTP para o backend
  │
  └── FastAPI (Railway)         ← backend econômico
        ├── EconomyEngine       ← orquestrador central (único entry point)
        ├── SymPy Solver        ← álgebra simbólica
        └── World Bank API      ← dados externos (httpx)
```

Os **dois repositórios são git repos separados** dentro do diretório monorepo `OIKOSLABOFICIAL/`. Cada um tem seu próprio remote no GitHub e pipeline de deploy independente.

---

## 3. Arquitetura do Backend

### 3.1 Estrutura

```
oikoslab-platform/backend/
├── main.py                        # FastAPI app + CORS + routers
├── requirements.txt
├── runtime.txt                    # Python version para Railway
├── routers/
│   ├── modelo_proprio.py          # Laboratório de modelos (principal)
│   ├── simulador_dinamico.py      # Modelo NK de 3 equações
│   ├── economia_real.py           # Integração World Bank
│   ├── islmbp.py                  # IS-LM-BP (legado)
│   └── funcoes.py                 # Funções simples (legado)
├── services/
│   ├── economy_engine.py          # Orquestrador central (EconomyEngine)
│   ├── motor_sistemas.py          # Resolver SymPy (núcleo do solver)
│   ├── validador.py               # Validação econômica + cenários
│   └── config.py                  # Configurações
└── test_engine.py
```

### 3.2 Roteamento

| Prefixo | Router | Status |
|---------|--------|--------|
| `/modelo` | `modelo_proprio.py` | **Ativo (principal)** |
| `/simulador-dinamico` | `simulador_dinamico.py` | **Ativo** |
| `/economia-real` | `economia_real.py` | **Ativo (em evolução)** |
| `/islmbp` | `islmbp.py` | Legado — mantido por compatibilidade |
| `/funcoes` | `funcoes.py` | Legado — mantido por compatibilidade |

### 3.3 Camada de Serviços

#### `EconomyEngine` (orquestrador central)
**Único ponto de entrada** para toda resolução de modelos. Nenhum router chama o solver diretamente. Pipeline sequencial e obrigatório em 11 etapas:

```
1.  Parse + Dedup      → canonicalização simbólica, elimina equações duplicadas
2.  Classify           → classifica variáveis (endógenas vs parâmetros)
3.  LaTeX              → gera representação LaTeX das equações de entrada
4.  Detect             → detecta endógenas (LHS) e parâmetros (RHS sem LHS)
5.  Solve              → resolve sistema com SymPy (numérico + simbólico)
6.  ConsistênciaPorEq  → verifica se cada equação é satisfeita pela solução
7.  ConsistênciaEstru  → verifica identidades macroeconômicas (Y=C+I+G, Qd=Qs)
8.  EconomicHardGate   → rejeita soluções economicamente inviáveis (Y<0, C<0, etc.)
9.  Elasticidades      → derivadas analíticas ∂endógena/∂parâmetro via SymPy
10. Series             → séries numéricas para análise de sensibilidade
11. ResultGate+Format  → monta o contrato de resposta JSON
```

O **EconomicHardGate** (etapa 8) é **não bypassável**: soluções com Y<0, C<0, I<0 são bloqueadas com `status: "invalid_solution"`, sem retornar valores numéricos.

#### `validador.py`
- Matriz de regras econômicas com gravidade (bloqueante/warning por variável)
- `simular_cenario()` — executa cenário base + variações
- `classificar_variaveis()` — endógenas vs exógenas
- `aplicar_validacao_economica()` — aplica o hard gate
- `validar_consistencia_estrutural()` — identidades (Y=C+I+G, Qd=Qs, Md=Ms)

#### `motor_sistemas.py`
- Núcleo do solver SymPy
- `_resolve_sistema()` — resolve sistemas simultâneos
- `_split_equacao()` — parser de equações aceita string ou objeto Pydantic

### 3.4 Modelos Econômicos

#### Construtor de Funções (`/modelo`)
- Detecção automática de endógenas: variável no LHS → endógena; símbolo sem LHS → parâmetro
- Resolve sistemas simultâneos (Cruz Keynesiana, IS-LM, Solow, Economia Aberta...)
- Solução simbólica → derivadas analíticas ∂Y/∂G, ∂Y/∂T, etc.
- Biblioteca de blocos pré-configurados (8 blocos) e modelos prontos (2)
- Análise de sensibilidade: varia parâmetro, plota efeito nas endógenas

**Blocos disponíveis:** `consumo_keynesiano`, `investimento`, `investimento_juro`, `governo`, `exportacoes_liquidas`, `produto`, `produto_aberto`, `demanda_moeda`, `solow_ss`

**Modelos prontos:** `cruz_keynesiana`, `economia_aberta`

#### Simulador Dinâmico (`/simulador-dinamico`)
Modelo Novo-Keynesiano de 3 equações (Carlin-Soskice / Galí):

```
IS dinâmica:    y_gap(t) = a·y_gap(t-1) − α·(r(t-1)−r_n) + ε_demanda
Phillips:       π(t)     = π_e(t) + β·y_gap(t) + ε_oferta
Taylor:         r(t)     = r_n + φ_π·(π−π_meta) + φ_y·y_gap(t)
Okun:           u(t)     = u_n − okun·y_gap(t)
```

As **escolas** são parametrizações do mesmo modelo:

| Escola | a | α | β | φ_π | φ_y | θ | Histerese |
|--------|---|---|---|-----|-----|---|-----------|
| Novo-Clássica | 0.30 | 0.90 | 0.80 | 1.80 | 0.25 | 1.0 | 0 |
| Keynesiana | 0.75 | 0.40 | 0.25 | 1.20 | 0.80 | 0.0 | 0 |
| Monetarista | 0.50 | 0.70 | 0.55 | 2.00 | 0.10 | 0.2 | 0 |
| Pós-Keynesiana | 0.85 | 0.30 | 0.18 | 1.10 | 0.90 | 0.0 | 0.04 |

Parâmetros estruturais (informalidade, crédito, desigualdade, setor público, tecnologia) modificam os coeficientes com justificativa teórica.

#### Economia Real (`/economia-real`)
- Integração com World Bank API (httpx assíncrono)
- 12 indicadores: PIB, inflação, desemprego, consumo, investimento, câmbio, juros, etc.
- Busca por país e intervalo de anos
- Calibração do modelo de 3 equações com dados reais — **em evolução**

---

## 4. Arquitetura do Frontend

### 4.1 Estrutura

```
oikoslab-platform/frontend/
├── app/                           # Next.js App Router
│   ├── layout.tsx                 # Root layout (fontes, KaTeX CSS, ReactFlow CSS)
│   ├── globals.css                # Estilos globais + Tailwind v4
│   ├── page.tsx                   # Rota raiz (redirect)
│   ├── home/page.tsx              # Landing page institucional
│   ├── login/page.tsx             # Login/cadastro (Supabase Auth)
│   ├── sobre/page.tsx             # Página institucional
│   ├── contato/page.tsx           # Página institucional
│   ├── blog/page.tsx              # Blog econômico (MOCKADO)
│   ├── dashboard/page.tsx         # Dashboard com KPIs do Supabase
│   ├── perfil/page.tsx            # Perfil do usuário
│   ├── projetos/
│   │   ├── page.tsx               # Listagem de projetos
│   │   ├── novo/page.tsx          # Criação (2 etapas)
│   │   └── [id]/
│   │       ├── page.tsx           # Página individual do projeto
│   │       ├── construtor/        # Construtor de Funções (Laboratório principal)
│   │       ├── simulador-dinamico/# Simulador Dinâmico NK
│   │       ├── economia-real/     # Cenários Pré-calibrados (World Bank)
│   │       └── editor/            # Editor visual (em desenvolvimento)
│   └── auth/logout/route.ts       # API Route de logout
├── components/
│   ├── lab/                       # Componentes do Laboratório
│   │   ├── ProjectSidebar.tsx     # Sidebar colapsável (14 seções)
│   │   ├── MetricCard.tsx         # Card de métrica clicável
│   │   ├── SectionCard.tsx        # Container de seção com header
│   │   ├── ActivityFeed.tsx       # Feed de atividades
│   │   └── CanvasContainer.tsx    # Canvas ReactFlow (visual)
│   ├── projetos/
│   │   └── ProjectDashboard.tsx   # Dashboard de projetos
│   └── ui/
│       ├── oikos-math.tsx         # Wrapper KaTeX (InlineMath/BlockMath)
│       ├── math-editor.tsx        # Editor de equações (Mathlive)
│       ├── rich-editor.tsx        # Editor rich text (TipTap)
│       ├── oikos-navbar.tsx       # Navbar principal
│       ├── button.tsx             # Botão base (CVA + Radix)
│       ├── accordion.tsx          # Radix Accordion
│       ├── web-gl-shader.tsx      # Shader WebGL decorativo
│       └── ...                    # Outros primitivos Radix/shadcn
├── lib/
│   ├── api.ts                     # Cliente HTTP para o backend FastAPI
│   ├── supabase.ts                # Cliente Supabase (browser)
│   ├── supabase-server.ts         # Cliente Supabase (server/SSR)
│   ├── types.ts                   # TypeScript types globais
│   └── utils.ts                   # Utilitários (cn, etc.)
├── public/                        # Arquivos estáticos
├── docs/                          # Documentação interna do projeto
│   ├── changelog.md
│   ├── decisoes.md
│   ├── estado-atual.md
│   ├── roadmap.md
│   └── visao-geral.md
└── CLAUDE.md                      # Contexto para o Claude Code
```

### 4.2 Padrão de Roteamento

O App Router do Next.js 16 é usado com:
- **Server Components** por padrão (sem estado)
- **`'use client'`** em componentes com estado, eventos ou APIs browser
- **`dynamic(..., { ssr: false })`** para libs que acessam `window`/DOM: `react-plotly.js`, `@xyflow/react`

### 4.3 Design System

| Token | Valor |
|-------|-------|
| Background base | `#0B0F19` |
| Superfícies | `#111827` |
| Cards (glassmorphism) | `bg-white/5 border border-white/10 rounded-2xl` |
| Primário | `#3b82f6` (blue-600) |
| Roxo | `#a78bfa` |
| Verde | `#34d399` |
| Ciano | `#06b6d4` |
| Laranja | `#fb923c` |
| Vermelho | `#f87171` |
| Texto destaque | `text-white` |
| Texto secundário | `text-gray-400` / `text-gray-500` |
| Fonte | Geist + Geist Mono (Next.js fonts) |

Plotly sempre com `paper_bgcolor`/`plot_bgcolor: 'transparent'`, grids `rgba(255,255,255,0.06)`.

---

## 5. Tecnologias Utilizadas

### Backend

| Tecnologia | Versão | Uso |
|------------|--------|-----|
| Python | 3.11+ | Runtime |
| FastAPI | latest | Framework HTTP |
| Pydantic | v2 | Validação de contratos |
| SymPy | latest | Solver simbólico + LaTeX |
| NumPy | latest | Arrays numéricos (séries) |
| SciPy | latest | Funções matemáticas |
| httpx | latest | Requisições HTTP assíncronas (World Bank) |
| Uvicorn | latest | ASGI server |

### Frontend

| Tecnologia | Versão | Uso |
|------------|--------|-----|
| Next.js | 16.2.7 | Framework React (App Router) |
| React | 19.2.4 | UI |
| TypeScript | ^5 | Tipagem |
| Tailwind CSS | ^4 | Estilização |
| `@supabase/supabase-js` | ^2.107 | Client Supabase (auth + DB) |
| `@supabase/ssr` | ^0.10 | SSR Supabase |
| `react-plotly.js` / `plotly.js` | ^2.6 / ^3.6 | Gráficos de sensibilidade |
| `react-katex` + `katex` | ^3.1 / ^0.17 | Renderização LaTeX |
| `@xyflow/react` | ^12.11 | Canvas de nós (ReactFlow) |
| `@tiptap/*` | ^3.26 | Editor rich text |
| `mathlive` | ^0.110 | Editor de equações matemáticas |
| `lucide-react` | ^1.17 | Ícones |
| `html2canvas` + `jspdf` | ^1.4 / ^4.2 | Exportar PDF |
| `three` | ^0.184 | Shader WebGL decorativo |
| `@radix-ui/*` | latest | Primitivos UI (accordion, dialog, etc.) |
| `class-variance-authority` | ^0.7 | Variantes de componentes |

### Infraestrutura

| Serviço | Uso |
|---------|-----|
| **Vercel** | Deploy do frontend (auto-deploy via push na branch `main`) |
| **Railway** | Deploy do backend FastAPI |
| **Supabase** | PostgreSQL + Auth + Storage (bucket `avatars`) |
| **GitHub** | Dois repos separados: `oikoslab-platform` (frontend) e `oikoslab-backend` |

---

## 6. Árvore de Pastas (resumida)

```
OIKOSLABOFICIAL/                    ← diretório raiz (não é git repo único)
├── oikoslab-platform/
│   ├── frontend/                   ← git repo: oikoslab-platform (branch main)
│   │   ├── app/                    # 15 páginas (App Router)
│   │   ├── components/lab/         # 5 componentes do Laboratório
│   │   ├── components/projetos/    # 1 componente
│   │   ├── components/ui/          # ~12 componentes UI
│   │   ├── lib/                    # api.ts, supabase.ts, types.ts, utils.ts
│   │   └── docs/                   # Documentação interna
│   └── backend/                    ← git repo: oikoslab-backend (branch main)
│       ├── main.py                 # Entry point FastAPI
│       ├── routers/                # 5 routers (3 ativos + 2 legados)
│       └── services/               # 4 serviços (EconomyEngine, solver, validador, config)
└── graphify-out/                   ← saída de análise Graphify (não é código)
```

---

## 7. Banco de Dados (Supabase)

### Tabelas

| Tabela | Colunas principais | Notas |
|--------|-------------------|-------|
| `profiles` | `id`, `nome`, `instituicao`, `bio`, `lattes`, `linkedin`, `github`, `avatar_url`, `curriculo` | 1:1 com `auth.users` |
| `projetos` | `id`, `user_id`, `titulo`, `descricao`, `tipo`, `configuracao` (JSONB), `publico`, `is_favorite`, `folder_id`, `is_shared`, `shared_with`, `visibility` | RLS ativo |
| `simulacoes` | — | Tabela de simulações (uso não documentado) |
| `compartilhamentos` | `id`, `projeto_id`, `owner_id`, `shared_with_id`, `permissao` | UI não implementada |

> **Atenção:** As colunas `is_favorite`, `folder_id`, `is_shared`, `shared_with`, `visibility` e a tabela `pastas` **ainda precisam de migração SQL** no Supabase Dashboard. O código TypeScript já espera essas colunas, mas podem não existir em produção.

### Coluna `configuracao` (JSONB)
Toda a configuração do laboratório é serializada neste campo. Estrutura atual para projetos do tipo `construtor_funcoes`:

```json
{
  "parametros":     [...],
  "equacoes":       [...],
  "sensibilidades": [...],
  "secoes":         [...],
  "referencias":    [...],
  "funcoesSalvas":  [...],
  "calculosSalvos": [...],
  "versoes":        [...]
}
```

---

## 8. APIs

### Backend — Endpoints Ativos

#### `/modelo` (Construtor de Funções)

| Método | Path | Descrição |
|--------|------|-----------|
| `GET` | `/modelo/blocos` | Lista todos os blocos e modelos prontos |
| `GET` | `/modelo/blocos/{id}` | Retorna bloco específico (equação + parâmetros) |
| `GET` | `/modelo/modelos/{id}` | Retorna modelo completo montado |
| `POST` | `/modelo/resolver` | **Pipeline completo:** resolve sistema + LaTeX + elasticidades + series |
| `POST` | `/modelo/simular-cenario` | Resolve base + variações, retorna comparativo |
| `POST` | `/modelo/validar` | Valida sintaxe de expressão SymPy |

**Contrato `/modelo/resolver` (request):**
```json
{
  "parametros": [{"nome": "c", "valor": 0.75, "descricao": "..."}],
  "equacoes":   [{"variavel": "C", "expressao": "a + c*(Y-T)", "nome": "Consumo"}],
  "sensibilidades": [{"nome": "G0", "min": 0, "max": 500, "pontos": 200, "mostrar": ["Y"]}]
}
```

**Contrato `/modelo/resolver` (response):**
```json
{
  "status": "ok",
  "valores": {"Y": 1200.0, "C": 800.0, ...},
  "latex": {"C": "C = a + c(Y - T)", "sol_Y": "Y = ..."},
  "elasticidades": {"Y": {"G0": 4.0, "T": -3.0}},
  "dependencias": ["↑ G0 -> ↑ Y", ...],
  "series": {"G0": [...], "Y_vs_G0": [...]},
  "erros": [],
  "economia": {"valid": true, "warnings": [], "violations": []}
}
```

#### `/simulador-dinamico`

| Método | Path | Descrição |
|--------|------|-----------|
| `POST` | `/simulador-dinamico/simular` | Simula trajetória dinâmica (1 escola ou comparação de 4) |
| `POST` | `/simulador-dinamico/irf` | Função de Resposta a Impulso |
| `GET` | `/simulador-dinamico/choques-predefinidos` | Lista 9 choques econômicos padrão |

#### `/economia-real`

| Método | Path | Descrição |
|--------|------|-----------|
| `GET` | `/economia-real/paises` | Lista países do World Bank |
| `GET` | `/economia-real/dados/{pais}/{ano_ini}/{ano_fim}` | Busca 12 indicadores para o país |

### Frontend — `lib/api.ts`

```typescript
api.modelo.resolver(params)   // → POST /modelo/resolver
api.modelo.validar(params)    // → POST /modelo/validar
api.islmbp.equilibrio(params) // → POST /islmbp/equilibrio (legado)
api.islmbp.curvas(params)     // → POST /islmbp/curvas (legado)
api.funcoes.consumo(params)   // → POST /funcoes/consumo (legado)
```

---

## 9. Principais Componentes

### Laboratório (`/projetos/[id]/construtor`)

| Componente | Arquivo | Função |
|-----------|---------|--------|
| `ConstrutorPage` | `app/projetos/[id]/construtor/page.tsx` | Página principal do Lab (927+ linhas) |
| `ProjectSidebar` | `components/lab/ProjectSidebar.tsx` | Sidebar colapsável com 14 seções de navegação |
| `CanvasContainer` | `components/lab/CanvasContainer.tsx` | Canvas ReactFlow com nós econômicos (visual) |
| `MetricCard` | `components/lab/MetricCard.tsx` | Card de métrica clicável com ícone e valor |
| `SectionCard` | `components/lab/SectionCard.tsx` | Container de seção com header + action slot |
| `ActivityFeed` | `components/lab/ActivityFeed.tsx` | Feed de atividades recentes |
| `OikosMath` | `components/ui/oikos-math.tsx` | Wrapper KaTeX com fallback em erro |
| `MathEditor` | `components/ui/math-editor.tsx` | Editor de equações (Mathlive) |
| `RichEditor` | `components/ui/rich-editor.tsx` | Editor rich text (TipTap) |

### Seções do Laboratório (`LabSection` type)

| Seção | Status |
|-------|--------|
| `visao-geral` | Implementada — métricas, ações rápidas, atividade |
| `canvas` | Implementada — ReactFlow visual (nós placeholder) |
| `modelos` | Implementada — editor de equações e parâmetros |
| `funcoes` | Parcialmente implementada — Sidebar atualizado, seção em progresso |
| `calculos` | Parcialmente implementada — Sidebar atualizado, seção em progresso |
| `dados` | Placeholder — visual apenas |
| `cenarios` | Placeholder — visual apenas |
| `resultados` | Implementada — valores, LaTeX, elasticidades, gráficos Plotly |
| `graficos` | Em progresso — Lab. Gráficos com sliders |
| `comparacao` | Em progresso — comparação de cálculos salvos |
| `versoes` | Em progresso — histórico de versões |
| `notas` | Implementada — TipTap + referências bibliográficas |
| `equipe` | Placeholder — visual apenas |
| `configuracoes` | Implementada — renomear, exportar PDF, excluir |

---

## 10. Fluxo de Execução

### Fluxo Principal — Resolver Modelo

```
Usuário configura equações e parâmetros na aba "Modelos"
        │
        ▼
[Frontend] ConstrutorPage.calcular()
  ├── Filtra equações com enabled !== false (toggle novo)
  ├── Filtra equações com variavel e expressão não-vazias
  └── Chama api.modelo.resolver({ parametros, equacoes, sensibilidades })
        │
        ▼
[Backend] POST /modelo/resolver
  └── EconomyEngine.run()
        ├── 1. Parse + Dedup (SymPy canonicalize)
        ├── 2. Classify (endógenas vs parâmetros)
        ├── 3. LaTeX das equações
        ├── 4. Detect (LHS → endógenas; sem LHS + sem param → endógenas extras)
        ├── 5. Solve (_resolve_sistema via SymPy)
        │     ├── Solução numérica (float)
        │     └── Solução simbólica (expressões)
        ├── 6. Consistência por equação
        ├── 7. Consistência estrutural (Y=C+I+G?)
        ├── 8. EconomicHardGate ← BLOQUEANTE se Y<0, C<0, I<0
        ├── 9. Elasticidades (∂endógena/∂parâmetro, SymPy diff)
        ├── 10. Series (linspace do parâmetro, substitui na expressão simbólica)
        └── 11. Formata resposta JSON
        │
        ▼
[Frontend] setResultado(res) → setSecao('resultados')
  └── Renderiza: valores, LaTeX (OikosMath), elasticidades, gráficos Plotly
```

### Fluxo — Autenticação

```
/login → Supabase Auth (email/senha)
  └── Sessão persistida via @supabase/ssr (cookies HTTP-only)
        └── Middleware / createClient() em server components
```

### Fluxo — Persistência de Projetos

```
salvar() → supabase.from('projetos').update({ configuracao: {...} })
  └── Todos os estados (equações, parâmetros, notas, etc.) serializam para JSONB

carregar() → supabase.from('projetos').select('*').eq('id', params.id)
  └── Hidrata estado local via useState a partir do campo configuracao
```

---

## 11. Pontos Críticos

### 1. Dois repositórios git separados
`frontend/` e `backend/` têm remotes distintos. Commitar na raiz não publica nada. Sempre executar dentro do subdiretório correto.

### 2. EconomyEngine como único entry point
Toda lógica econômica passa por `EconomyEngine.run()`. Bypassar o engine quebra o hard gate econômico. O gate é **não opcional** — soluções com Y<0 são rejeitadas e o frontend recebe `status: "invalid_solution"`.

### 3. Campo `configuracao` como blob JSONB
Todo o estado do laboratório vive em um único campo JSON no banco. Mudanças no schema interno desse campo exigem retrocompatibilidade (campos opcionais com `?.`). Não há migração de schema automática — projetos existentes têm a estrutura antiga.

### 4. Migração SQL pendente
As colunas `is_favorite`, `folder_id`, `is_shared`, `shared_with`, `visibility` na tabela `projetos` e a tabela `pastas` podem não existir em produção. O TypeScript já as declara em `lib/types.ts`, mas queries sem essas colunas falham silenciosamente ou com erro Supabase.

### 5. Componente principal monolítico
`app/projetos/[id]/construtor/page.tsx` tem 900+ linhas e concentra estado, lógica e UI. À medida que novas seções são adicionadas (funcoes, calculos, versoes, comparacao, graficos), o arquivo cresce. Candidato à extração de componentes.

### 6. Dependências SSR-incompatíveis
`react-plotly.js`, `@xyflow/react` e `mathlive` acessam `window`/DOM e precisam de `dynamic(..., { ssr: false })`. Esquecer o `ssr: false` causa falha silenciosa em SSR ou erro de hidratação.

### 7. CORS hardcoded
O backend só aceita requisições de `http://localhost:3000` e `https://oikoslab-platform.vercel.app`. Ao adicionar um domínio customizado ou preview deployments, é necessário atualizar `main.py`.

### 8. Backend sem autenticação própria
O backend FastAPI não valida tokens JWT. Qualquer caller dentro dos origins CORS pode chamar qualquer endpoint. A proteção de dados é feita inteiramente pelo Supabase RLS no frontend.

---

## 12. Limitações Atuais

| Área | Limitação |
|------|-----------|
| **Blog** | Mockado — sem backend real ou CMS |
| **Dados, Cenários, Equipe** | Seções visuais placeholder — sem funcionalidade |
| **Canvas** | ReactFlow com nós placeholder — sem conexão com modelos reais |
| **Colaboração** | Estrutura de compartilhamento existe no banco, mas UI não implementada |
| **Cenários Pré-calibrados** | World Bank busca dados, mas calibração do modelo de 3 equações + backtesting não está completa |
| **Blog** | Conteúdo estático — não há editor ou publicação real |
| **Pastas / Favoritos** | Frontend pronto, migração SQL pendente no Supabase |
| **World Bank** | Sem cache — cada acesso busca da API externa (latência variável) |
| **Gráficos** | Plotly sem wrapper unificado — migração futura para Graphify é manual |
| **Editor visual** | `app/projetos/[id]/editor/` existe mas não está documentado ou finalizado |
| **CI/CD** | Sem pipeline de testes — deploys via push direto na branch main |
| **Ambiente de preview** | Vercel Preview Deployments apontam para backend Railway de produção |
| **Streamlit Lab** | Repositório separado — não cobre a Camada 1 (simuladores educacionais abertos) |
| **Exportação PDF** | Usa `html2canvas + jsPDF` — qualidade limitada para fórmulas LaTeX |
| **Equações simultâneas grandes** | SymPy pode ser lento ou falhar para sistemas com 6+ variáveis com dependências circulares |

---

## 13. URLs de Produção

| Serviço | URL |
|---------|-----|
| Frontend | `https://oikoslab-platform.vercel.app` |
| Backend | `https://oikoslab-backend-production.up.railway.app` |
| Supabase | `https://vxtvjclprvmsanfciykl.supabase.co` |

---

## 14. Deploy

### Frontend (Vercel)
```powershell
cd oikoslab-platform\frontend
git add <arquivo>
git commit -m "mensagem"
git push origin main    # auto-deploy no Vercel
```

### Backend (Railway)
```powershell
cd oikoslab-platform\backend
git add routers\<arquivo>.py
git commit -m "mensagem"
git push origin main    # auto-deploy no Railway
```

### Forçar redeploy sem mudança
```powershell
git commit --allow-empty -m "chore: redeploy"
git push origin main
```
