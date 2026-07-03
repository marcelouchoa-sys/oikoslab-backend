# Graph Report - C:\Users\PICHAU\Documents\OIKOSLABOFICIAL  (2026-06-15)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 304 nodes · 362 edges · 35 communities (21 shown, 14 thin omitted)
- Extraction: 100% EXTRACTED · 0% INFERRED · 0% AMBIGUOUS
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `7799e2c5`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]
- [[_COMMUNITY_Community 10|Community 10]]
- [[_COMMUNITY_Community 11|Community 11]]
- [[_COMMUNITY_Community 12|Community 12]]
- [[_COMMUNITY_Community 13|Community 13]]
- [[_COMMUNITY_Community 14|Community 14]]
- [[_COMMUNITY_Community 15|Community 15]]
- [[_COMMUNITY_Community 16|Community 16]]
- [[_COMMUNITY_Community 17|Community 17]]
- [[_COMMUNITY_Community 19|Community 19]]
- [[_COMMUNITY_Community 20|Community 20]]
- [[_COMMUNITY_Community 21|Community 21]]
- [[_COMMUNITY_Community 22|Community 22]]
- [[_COMMUNITY_Community 24|Community 24]]
- [[_COMMUNITY_Community 26|Community 26]]
- [[_COMMUNITY_Community 27|Community 27]]
- [[_COMMUNITY_Community 28|Community 28]]
- [[_COMMUNITY_Community 33|Community 33]]
- [[_COMMUNITY_Community 34|Community 34]]

## God Nodes (most connected - your core abstractions)
1. `createClient()` - 19 edges
2. `compilerOptions` - 16 edges
3. `Python 3.11.9` - 10 edges
4. `_simular_trajetoria()` - 8 edges
5. `cn()` - 8 edges
6. `createServerSupabaseClient()` - 7 edges
7. `_split_equacao()` - 6 edges
8. `_params_escola()` - 6 edges
9. `simular()` - 6 edges
10. `ParametrosISLM` - 5 edges

## Surprising Connections (you probably didn't know these)
- `POST()` --calls--> `createServerSupabaseClient()`  [EXTRACTED]
  oikoslab-platform/frontend/app/auth/logout/route.ts → oikoslab-platform/frontend/lib/supabase-server.ts
- `DashboardPage()` --calls--> `createServerSupabaseClient()`  [EXTRACTED]
  oikoslab-platform/frontend/app/dashboard/page.tsx → oikoslab-platform/frontend/lib/supabase-server.ts
- `LoginPage()` --calls--> `createClient()`  [EXTRACTED]
  oikoslab-platform/frontend/app/login/page.tsx → oikoslab-platform/frontend/lib/supabase.ts
- `PerfilPage()` --calls--> `createClient()`  [EXTRACTED]
  oikoslab-platform/frontend/app/perfil/page.tsx → oikoslab-platform/frontend/lib/supabase.ts
- `ConstrutorPage()` --calls--> `createClient()`  [EXTRACTED]
  oikoslab-platform/frontend/app/projetos/[id]/construtor/page.tsx → oikoslab-platform/frontend/lib/supabase.ts

## Import Cycles
- None detected.

## Communities (35 total, 14 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.05
Nodes (41): dependencies, class-variance-authority, clsx, html2canvas, jspdf, katex, lucide-react, mathlive (+33 more)

### Community 1 - "Community 1"
Cohesion: 0.08
Nodes (22): WebGLShader, cn(), AccordionContent, AccordionItem, AccordionTrigger, Button, ButtonProps, buttonVariants (+14 more)

### Community 2 - "Community 2"
Cohesion: 0.08
Nodes (22): ConstrutorPage(), Equacao, Parametro, Plot, Referencia, Secao, Sensibilidade, uid() (+14 more)

### Community 3 - "Community 3"
Cohesion: 0.10
Nodes (18): DadoSerie, EconomiaRealPage(), Pais, Plot, ProjetoRedirect(), createClient(), LoginPage(), NovoProjeto() (+10 more)

### Community 4 - "Community 4"
Cohesion: 0.15
Nodes (16): BaseModel, calcular_consumo(), calcular_investimento(), ParamsConsumo, ParamsInvestimento, _detectar(), Equacao, ModeloInput (+8 more)

### Community 5 - "Community 5"
Cohesion: 0.09
Nodes (21): devDependencies, eslint, eslint-config-next, tailwindcss, @tailwindcss/postcss, @types/katex, @types/node, @types/react (+13 more)

### Community 6 - "Community 6"
Cohesion: 0.10
Nodes (19): compilerOptions, allowJs, esModuleInterop, incremental, isolatedModules, jsx, lib, module (+11 more)

### Community 7 - "Community 7"
Cohesion: 0.24
Nodes (16): _ajuste_estrutural(), _calibrar_naturais(), Choque, ConfigEconomia, _descricao(), funcao_resposta_impulso(), _media(), _montar_analise() (+8 more)

### Community 8 - "Community 8"
Cohesion: 0.18
Nodes (12): DashboardPage(), TIPO_COR, TIPO_LABEL, createServerSupabaseClient(), Compartilhamento, Profile, Projeto, POST() (+4 more)

### Community 9 - "Community 9"
Cohesion: 0.18
Nodes (11): @AGENTS.md, FastAPI, NumPy, Pydantic, python-dotenv, SciPy, Supabase, SymPy (+3 more)

### Community 11 - "Community 11"
Cohesion: 0.40
Nodes (3): buscar_dados(), calibrar_modelo(), Busca dados reais e calibra automaticamente os parametros     do modelo IS-LM pa

### Community 12 - "Community 12"
Cohesion: 0.40
Nodes (3): geistMono, geistSans, metadata

### Community 13 - "Community 13"
Cohesion: 0.90
Nodes (4): calcular_curvas(), calcular_equilibrio(), ParametrosISLM, _resolver()

### Community 14 - "Community 14"
Cohesion: 0.67
Nodes (4): Backend Python Simulators, Architecture Decision Record, Current State of the Project, Next.js Project

## Knowledge Gaps
- **153 isolated node(s):** `ARTIGOS`, `TIPO_LABEL`, `TIPO_COR`, `geistSans`, `geistMono` (+148 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **14 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `dependencies` connect `Community 0` to `Community 5`?**
  _High betweenness centrality (0.036) - this node is a cross-community bridge._
- **Why does `createClient()` connect `Community 3` to `Community 2`?**
  _High betweenness centrality (0.019) - this node is a cross-community bridge._
- **What connects `Busca dados reais e calibra automaticamente os parametros     do modelo IS-LM pa`, `Normaliza uma equacao em (lhs_str, rhs_str).     Aceita 'C = a + c*Y' OU variav`, `OBJETIVO 1: separa endogenas de parametros.     Endogena = qualquer simbolo que` to the rest of the system?**
  _161 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Community 0` be split into smaller, more focused modules?**
  _Cohesion score 0.04878048780487805 - nodes in this community are weakly interconnected._
- **Should `Community 1` be split into smaller, more focused modules?**
  _Cohesion score 0.07954545454545454 - nodes in this community are weakly interconnected._
- **Should `Community 2` be split into smaller, more focused modules?**
  _Cohesion score 0.08045977011494253 - nodes in this community are weakly interconnected._
- **Should `Community 3` be split into smaller, more focused modules?**
  _Cohesion score 0.09885057471264368 - nodes in this community are weakly interconnected._