# Agentes de IA (MCP)

> 🌐 [English](../AGENTS.md) · [Français](../fr/AGENTS.md) · [Deutsch](../de/AGENTS.md) · [Italiano](../it/AGENTS.md) · [Español](../es/AGENTS.md) · **Português** · [简体中文](../zh/AGENTS.md)

O Facet pode atuar como servidor [Model Context Protocol](https://modelcontextprotocol.io/) (MCP), para que um assistente de IA como o Claude Code possa pesquisar e inspecionar a sua biblioteca com os mesmos filtros da galeria. O endpoint é só de leitura: expõe nove ferramentas de leitura e não altera nada na sua biblioteca.

## Ativá-lo

O endpoint está **desativado por predefinição**. Defina `viewer.mcp.enabled` como `true` em `scoring_config.json` (ver [Endpoint de agentes (MCP)](CONFIGURATION.md#endpoint-de-agentes-mcp)) e reinicie o visualizador, ou recarregue a configuração. Enquanto estiver desativado, `/mcp` e todas as rotas `/api/mcp/*` respondem 404.

O endpoint é `POST /mcp` na porta do visualizador: Streamable HTTP, sem estado, respostas JSON simples. `GET` responde 405. Num proxy reverso não são precisos cabeçalhos WebSocket.

## Criar um token

Um assistente autentica-se com um token pessoal que começa por `fct_`. Crie um com um pedido autenticado (o token é devolvido **uma única vez**; o Facet guarda apenas o seu hash SHA-256):

```bash
TOKEN=$(curl -s -X POST http://localhost:5000/api/auth/login -H 'Content-Type: application/json' -d '{"password": "YOUR_VIEWER_PASSWORD"}' | jq -r .access_token)
curl -s -X POST http://localhost:5000/api/mcp/tokens -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"name": "claude-code", "level": "readonly"}'
```

A resposta traz o texto simples em `token`. `GET /api/mcp/tokens` lista os seus tokens (nunca o segredo) e `DELETE /api/mcp/tokens/{id}` revoga um. Um superadmin pode listar os tokens de todos os proprietários com `?all=1` e revogar qualquer um. Cada proprietário pode ter no máximo 20 tokens ativos (acima disso, 412). Estas rotas recusam as credenciais de um agente, por isso um assistente nunca pode criar, listar nem revogar tokens.

## Ligar o Claude Code

```bash
claude mcp add --transport http facet http://localhost:5000/mcp --header "Authorization: Bearer fct_YOUR_TOKEN"
```

As ferramentas aparecem depois como `mcp__facet__search_photos` e assim por diante. Use HTTPS quando o visualizador for acessível para além da sua própria máquina, pois o token viaja num cabeçalho em cada chamada.

## Níveis de permissão

Um token é criado com um nível concedido: `readonly`, `user` ou `edition`. O nível **efetivo** é recalculado em cada chamada como o menor entre o do token e o atual do seu proprietário:

- Instalações com palavra-passe única: `user` é limitado a `readonly` na criação, porque esse modo não tem nível intermédio. Um token `edition` exige uma sessão de edição e só funciona enquanto a palavra-passe de edição não mudar.
- Instalações multiutilizador: o token `edition` de um utilizador entretanto despromovido desce para `user`; uma promoção nunca eleva um token acima do nível concedido.
- Instalações abertas (sem palavra-passe): os tokens são sempre `readonly` e pertencem a um proprietário partilhado `_anonymous`.

Um token deixa de valer automaticamente quando as credenciais do seu proprietário mudam: a palavra-passe do visualizador ou de edição no modo de palavra-passe única, a palavra-passe do proprietário no modo multiutilizador, ou a eliminação da sua conta. Recebe então um 401 à entrada.

## Ferramentas

As nove ferramentas registadas são todas só de leitura:

| Ferramenta | O que faz |
|------|--------------|
| `search_photos` | Filtra e ordena a biblioteca como a galeria, aplicando as ocultações predefinidas do visualizador, a não ser que o filtro as defina (indica `hidden_summary`) |
| `semantic_search` | Encontra fotos pelo significado, ou por palavras das legendas com `scope: "text"` |
| `get_photo` | Detalhe completo de uma foto a partir do seu caminho (sem o histograma) |
| `similar_photos` | Fotos semelhantes a uma foto, por embedding visual ou por cor |
| `filter_options` | O vocabulário que um filtro aceita: câmaras, objetivas, etiquetas, pessoas, padrões, categorias, momentos narrativos, tipos de lixo, intervalos de métricas |
| `list_persons` | Pessoas reconhecidas, filtráveis por nome |
| `list_albums` | Álbuns que o proprietário do token pode ver |
| `library_stats` | Tamanho da biblioteca, contagens por tipo e resumo das pontuações |
| `status` | Quem é o token, o seu nível efetivo e as sinalizações do servidor |

## Resultados, limites e erros

Cada resultado é um envelope JSON: `{"ok": true, "data": ...}` ou `{"ok": false, "error": "<code>", "message": "..."}`. As listagens devolvem `data.rows` (um conjunto compacto e fixo de campos por foto) mais `total`.

- **Limites máximos:** no máximo `max_rows` linhas e `max_bytes` bytes serializados. As últimas linhas são descartadas e `truncated: true` é definido. Um resultado sem linhas que exceda `max_bytes` torna-se um erro `too_large`.
- **Limite de frequência:** `rate_per_min` chamadas por minuto e por token (existe um orçamento separado, `write_rate_per_min`, para as chamadas de escrita). Excedido: `rate_limited` com `retry_after_s`. Dez tentativas bearer falhadas por minuto a partir de um endereço dão 429.
- **Códigos de erro:** `forbidden_level` (endpoint desativado, token inválido ou nível insuficiente), `invalid_input`, `not_found`, `rate_limited`, `library_busy`, `upstream_error`, `outcome_unknown`, `too_large`.
- **Códigos HTTP à entrada:** 401 para token em falta ou desconhecido, 403 para um pedido de navegador de outra origem, 404 quando está desativado.

## Notas de segurança

- Legendas, etiquetas, nomes de ficheiros, caminhos e nomes de álbuns e pessoas vêm da sua biblioteca e podem conter texto escrito para manipular um assistente (injeção de prompts). Cada ferramenta está marcada com `facet/untrusted_content` e diz ao modelo para os tratar como dados. Não dê a um assistente que também lê conteúdo não fiável uma forma de agir sobre o que encontra aqui.
- Os tokens nunca expiram. Revogue os que já não usa.
- Os registos guardam o id do token, a ferramenta, o resultado e o número de linhas, nunca os argumentos nem o token.

## Limitações conhecidas

- Numa instalação aberta (sem palavra-passe), qualquer pessoa que alcance o visualizador pode criar e revogar os tokens `_anonymous` partilhados. Defina uma palavra-passe antes de ativar o endpoint numa rede.
- Os limites de frequência e os contadores de autenticações falhadas vivem em memória em cada processo; com `viewer.py --workers N` cada worker conta em separado.
- `viewer.mcp.bridge` é lido pela ferramenta `status`, mas por agora nada mais o usa.
