# Agentes de IA (MCP)

> 🌐 [English](../AGENTS.md) · [Français](../fr/AGENTS.md) · [Deutsch](../de/AGENTS.md) · [Italiano](../it/AGENTS.md) · [Español](../es/AGENTS.md) · **Português** · [简体中文](../zh/AGENTS.md)

O Facet pode atuar como servidor [Model Context Protocol](https://modelcontextprotocol.io/) (MCP), para que um assistente de IA como o Claude Code possa pesquisar e inspecionar a sua biblioteca com os mesmos filtros da galeria. Expõe nove ferramentas de leitura que não alteram nada na sua biblioteca, mais nove ferramentas `ui_*` que movem o separador do navegador que já tem aberto (página, filtros, seleção) e nunca escrevem dados da biblioteca.

## Ativá-lo

O endpoint está **desativado por predefinição**. Defina `viewer.mcp.enabled` como `true` em `scoring_config.json` (ver [Endpoint de agentes (MCP)](CONFIGURATION.md#endpoint-de-agentes-mcp)) e reinicie o visualizador, ou recarregue a configuração. Enquanto estiver desativado, `/mcp` e todas as rotas `/api/mcp/*` respondem 404.

O endpoint é `POST /mcp` na porta do visualizador: Streamable HTTP, sem estado, respostas JSON simples. `GET` responde 405. Só a ponte do separador, `/api/mcp/bridge`, é um WebSocket; veja [Controlar o separador aberto](#controlar-o-separador-aberto).

## Criar um token

O mais simples é o navegador. Com `viewer.mcp.enabled` ativo, abra o menu da conta e escolha **Ligar um assistente**. Em **Criar um token**, introduza um **Nome** e escolha **O que o assistente pode fazer**: **Apenas ler e controlar**, mais **Agir como eu** ou **Edição completa** se a sua sessão tiver esse nível (um token não pode superar a sessão que o cria). Clique em **Criar token**: o token aparece uma única vez em **O seu novo token**, por isso copie-o já. **Tokens de acesso** lista os seus tokens com a última utilização e permite revogar um. **Adicionar ao Claude Code** mostra o comando do Claude Code pronto a colar (ver abaixo), e **Este separador** indica se este separador está ligado e, portanto, controlável pelos assistentes. A lista de níveis limita-se ao que o servidor concederá: uma instalação aberta oferece apenas **Apenas ler e controlar**, **Agir como eu** só aparece em instalações multiutilizador e **Edição completa** só numa sessão de edição. Depois de criar, a caixa indica o nível efetivamente concedido ("Acesso concedido: {level}").

Alternativa por script (curl):

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

As nove ferramentas de dados são só de leitura:

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

## Controlar o separador aberto

Ao lado das ferramentas de dados, o servidor lista sempre nove ferramentas `ui_*` que atuam sobre o separador do Facet que tem aberto num navegador: mudam de página, alteram os filtros ou a seleção e voltam a ler o que vê. Nunca escrevem dados da biblioteca, por isso basta um token `readonly`.

| Ferramenta | O que faz |
|------------|-----------|
| `ui_navigate` | Ir para uma página (galeria, pessoas, álbuns, estatísticas, ...) |
| `ui_set_gallery_filters` | Juntar uma alteração aos filtros e à ordenação da galeria (`null` remove um filtro, `replace: true` parte do zero) |
| `ui_get_gallery_view` | Rota, filtros ativos, total de resultados, os primeiros caminhos de fotos visíveis e o número de fotos selecionadas |
| `ui_open_photo` | Abrir uma foto |
| `ui_select_photos` | Selecionar `paths` explícitos, ou toda a vista filtrada com `select_view: true`, em modo `replace`, `add` ou `remove` |
| `ui_clear_selection` | Limpar a seleção |
| `ui_get_selection` | O `scope` (`paths` ou `view`) e o `count`, com os `paths` ou, numa vista, os `filters` e os `excluded_paths` |
| `ui_next_page` | Carregar a página seguinte da galeria |
| `ui_show_culling_group` | Abrir a câmara escura num grupo, identificado por `(type, group_id)` (contas de edição) |

Como funciona:

- Enquanto tiver sessão iniciada e `viewer.mcp.enabled` e `viewer.mcp.bridge` forem `true`, cada separador do Facet abre um WebSocket da mesma origem para `/api/mcp/bridge` e autentica-se com a sua sessão na primeira mensagem. A ponte vem ativa por omissão; ponha `viewer.mcp.bridge` a `false` para a desativar e as ferramentas `ui_*` passam a responder com um erro claro.
- Uma ferramenta só chega aos separadores do dono do token. Com uma única palavra-passe todas as sessões são o mesmo utilizador; numa instalação aberta cada separador pertence ao utilizador partilhado `_anonymous`.
- Com vários separadores abertos usa-se o que teve o foco mais recentemente e o campo `tab` do resultado di-lo. Passe `tab_id` (listado por `status`) para escolher outro.
- Um separador recusa o que a sua conta não pode fazer (por exemplo `/culling` para uma conta sem edição) e a ferramenta devolve essa recusa.
- O que um separador devolve não é de confiança: a profundidade e o comprimento de cadeias e listas são limitados, e tudo fica contido por `max_bytes`.
- Erros: `no_tab` (nenhum separador ligado, ou ponte desativada), `tab_timeout` (sem resposta em `call_timeout_s`) e `tab_outdated` (o separador aberto não conhece a ferramenta; recarregue a página depois de atualizar o Facet).
- Um proxy reverso tem de reencaminhar a atualização para WebSocket em `/api/mcp/bridge`; veja [Implantação](DEPLOYMENT.md). Se reescrever o cabeçalho `Host`, indique a origem pública em `viewer.mcp.allowed_origins` (por exemplo `["https://photos.example.com"]`), porque a origem da página tem de coincidir com o host ou constar da lista.
- O registo de separadores é por processo, por isso a ponte exige um único worker (o valor por omissão).

Em complemento:

- `ui_set_gallery_filters` leva primeiro à galeria se estiver aberta outra página e depois aplica o patch. Recusa o patch inteiro (`invalid_input`) se nomear um filtro que o separador não sabe controlar; para esses use `search_photos`.
- `ui_get_gallery_view`, `ui_next_page` e `ui_select_photos` com `select_view` precisam que a galeria (ou um álbum) seja a página aberta; caso contrário respondem `no_active_view`; chame antes `ui_navigate` para `/`. Dê a `ui_select_photos` exatamente um de `paths` e `select_view`.
- `no_tab` também significa que não há nenhum separador do Facet aberto: abra o Facet num navegador e inicie sessão. **Este separador** na caixa **Ligar um assistente** mostra o estado da ligação, com o id do separador.
- Um separador deixa de se religar quando a sua sessão é recusada (inicie sessão de novo) e espera que volte a ele se outro dos seus separadores tomou o seu lugar.
- A ponte do separador só se liga se o servidor a declarar disponível (o endpoint está ativo e `viewer.mcp.bridge` é true); com a ponte desativada, os separadores não se ligam de todo.
- `ui_set_gallery_filters` recusa um nome de filtro desconhecido com `invalid_input`, e também um patch que indique em simultâneo `category` e `type`, ou `person` e `person_id`. Só oferece os filtros que a galeria sabe mostrar; para os outros use `search_photos`.
- `ui_navigate` abre apenas as páginas estáticas da aplicação: a página de início de sessão, as páginas partilhadas, os URL externos e os caminhos desconhecidos são recusados (`invalid_input`), e as páginas só de edição são recusadas a uma sessão sem edição.
- `ui_select_photos` em modo `remove` com uma seleção de toda a vista ignora os caminhos fora da vista carregada e lista-os como `not_in_view` no resultado.

## WebMCP na página (agentes do navegador)

À parte do endpoint `/mcp`, um separador com sessão iniciada oferece também as mesmas ferramentas `ui_*` aos agentes que vivem no próprio navegador, através da API W3C [WebMCP](https://webmachinelearning.github.io/webmcp/) (`navigator.modelContext`). Um assistente nativo do navegador vê assim exatamente as ferramentas listadas acima, executa-as no separador que está a ver e não precisa de token.

- **Apenas em contexto seguro.** O Facet só regista as ferramentas em HTTPS ou em `localhost`. Em HTTP simples não são oferecidas e a caixa **Ligar um assistente** indica-o; a ligação por token acima continua a funcionar.
- Registadas quando `viewer.mcp.enabled` é true e tem a sessão iniciada, e removidas ao terminar a sessão.
- As ferramentas fazem o mesmo, limitadas pelo mesmo nível de conta, que na tabela acima.

## Resultados, limites e erros

Cada resultado é um envelope JSON: `{"ok": true, "data": ...}` ou `{"ok": false, "error": "<code>", "message": "..."}`. As listagens devolvem `data.rows` (um conjunto compacto e fixo de campos por foto) mais `total`.

- **Limites máximos:** no máximo `max_rows` linhas e `max_bytes` bytes serializados. As últimas linhas são descartadas e `truncated: true` é definido. Um resultado sem linhas que exceda `max_bytes` torna-se um erro `too_large`.
- **Limite de frequência:** `rate_per_min` chamadas por minuto e por token (existe um orçamento separado, `write_rate_per_min`, para as chamadas de escrita). Excedido: `rate_limited` com `retry_after_s`. Dez tentativas bearer falhadas por minuto a partir de um endereço dão 429.
- **Códigos de erro:** `forbidden_level` (endpoint desativado, token inválido ou nível insuficiente), `invalid_input`, `not_found`, `rate_limited`, `library_busy`, `upstream_error`, `outcome_unknown`, `too_large`, `no_tab`, `tab_timeout`, `tab_outdated`.
- **Códigos HTTP à entrada:** 401 para token em falta ou desconhecido, 403 para um pedido de navegador de outra origem, 404 quando está desativado.

## Notas de segurança

- Legendas, etiquetas, nomes de ficheiros, caminhos e nomes de álbuns e pessoas vêm da sua biblioteca e podem conter texto escrito para manipular um assistente (injeção de prompts). Cada ferramenta está marcada com `facet/untrusted_content` e diz ao modelo para os tratar como dados. Não dê a um assistente que também lê conteúdo não fiável uma forma de agir sobre o que encontra aqui.
- Os tokens nunca expiram. Revogue os que já não usa.
- Os registos guardam o id do token, a ferramenta, o resultado e o número de linhas, nunca os argumentos nem o token.

## Limitações conhecidas

- Numa instalação aberta (sem palavra-passe), qualquer pessoa que alcance o visualizador pode criar e revogar os tokens `_anonymous` partilhados. Defina uma palavra-passe antes de ativar o endpoint numa rede. A ponte de separador amplia este risco: um cliente que não seja um navegador pode enviar um `Origin` inventado e um token nulo, registar um separador `_anonymous` com o foco, responder às chamadas `ui_*` com os dados que quiser e expulsar separadores reais através do limite de 8 separadores.
- Os limites de frequência e os contadores de autenticações falhadas vivem em memória em cada processo; com `viewer.py --workers N` cada worker conta em separado.
- O registo de separadores vive em memória num só processo. Use um único worker (`viewer.py --workers 1`, o valor por omissão) se depender das ferramentas `ui_*`; com vários workers uma chamada pode chegar a um processo que não conhece o seu separador e responder `no_tab`.
- Um utilizador pode ter no máximo 8 separadores ligados; abrir um nono fecha o mais antigo.
