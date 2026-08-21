@AGENTS.md
@AGENTS.md

# OIKOS

## Projeto

A Oikos é uma plataforma SaaS para gestão de escritórios de arquitetura.

O objetivo é centralizar:

- Projetos
- Clientes
- Equipes
- Documentos
- Indicadores

## Stack

- Next.js
- TypeScript
- Supabase
- Tailwind CSS

## Estrutura

/app
- Rotas da aplicação

/components
- Componentes reutilizáveis

/lib
- Integrações, utilitários e tipos

/public
- Arquivos estáticos

## Regras

- Nunca remover funcionalidades existentes sem autorização.
- Antes de implementar mudanças grandes, explicar o plano.
- Evitar criar arquivos duplicados.
- Reutilizar componentes existentes sempre que possível.
- Preservar a identidade visual atual.
- Manter TypeScript fortemente tipado.

## Banco de Dados

- Utiliza Supabase.
- Considerar impacto em tabelas e autenticação antes de alterar modelos.

## Performance

Ignorar completamente:

- node_modules
- .next
- .vercel
- package-lock.json

Esses arquivos não devem ser analisados para entender a arquitetura.

## Fluxo de Trabalho

Antes de escrever código:

1. Explicar o que foi entendido.
2. Explicar quais arquivos serão alterados.
3. Implementar apenas o solicitado.
4. Não modificar funcionalidades fora do escopo.