# Agentes de IA (MCP)

> 🌐 [English](../AGENTS.md) · [Français](../fr/AGENTS.md) · [Deutsch](../de/AGENTS.md) · [Italiano](../it/AGENTS.md) · [Español](../es/AGENTS.md) · **Português** · [简体中文](../zh/AGENTS.md)

O Facet pode atuar como servidor [Model Context Protocol](https://modelcontextprotocol.io/) (MCP), de modo que um assistente de IA compatível com MCP possa pesquisar e inspecionar a sua biblioteca com os mesmos filtros da galeria. Expõe nove ferramentas de leitura que não alteram nada na biblioteca e nove ferramentas `ui_*` que movem o separador do navegador que já tem aberto (página, filtros, seleção) e nunca escrevem dados da biblioteca. Os tokens autorizados também podem [alterar a biblioteca](#alterar-a-biblioteca) (classificações, marcadores, etiquetas, álbuns, triagem e eliminação) e usar a [câmara escura](#câmara-escura-grupos-de-triagem).

## Ativá-lo

O endpoint está **desativado por predefinição**. Defina `viewer.mcp.enabled` como `true` em `scoring_config.json` (ver [Endpoint de agentes (MCP)](CONFIGURATION.md#endpoint-de-agentes-mcp)) e reinicie o visualizador, ou recarregue a configuração. Enquanto estiver desativado, `/mcp` e todas as rotas `/api/mcp/*` respondem 404. Sem `viewer.password` a instalação é considerada aberta, mesmo que `viewer.edition_password` esteja definida: os seus tokens só podem ser `readonly`.

O endpoint é `POST /mcp` na porta do visualizador: Streamable HTTP, sem estado, respostas JSON simples. `GET` responde 405. Só a ponte do separador, `/api/mcp/bridge`, é um WebSocket; veja [Controlar o separador aberto](#controlar-o-separador-aberto).

## Criar um token

O mais simples é o navegador. Com `viewer.mcp.enabled` ativo, abra o menu da conta e escolha **Ligar um assistente**. Introduza um **Nome**, escolha **O que o assistente pode fazer**: **Apenas ler e controlar**, mais **Agir como eu** ou **Edição completa** se a sua sessão tiver esse nível (um token não pode superar a sessão que o cria), e clique em **Criar token**. A caixa mostra então **Cole isto no seu assistente** com um prompt já pronto que contém o token. É mostrado uma única vez: clique em **Copiar prompt**, cole-o no seu assistente e clique em **Concluir**. **Gerir tokens (N)** lista os seus tokens com a última utilização e permite revogar um, e uma linha de estado indica se este separador está ligado e, portanto, controlável pelos assistentes. A lista de níveis limita-se ao que o servidor concederá: uma instalação aberta oferece apenas **Apenas ler e controlar**, **Agir como eu** só aparece em instalações multiutilizador e **Edição completa** só numa sessão de edição. O prompt indica o nível efetivamente concedido.

Alternativa por script (curl):

Um assistente autentica-se com um token pessoal que começa por `fct_`. Crie um com um pedido autenticado (o token é devolvido **uma única vez**; o Facet guarda apenas o seu hash SHA-256):

```bash
TOKEN=$(curl -s -X POST http://localhost:5000/api/auth/login -H 'Content-Type: application/json' -d '{"password": "YOUR_VIEWER_PASSWORD"}' | jq -r .access_token)
curl -s -X POST http://localhost:5000/api/mcp/tokens -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"name": "my-assistant", "level": "readonly"}'
```

A resposta traz o texto simples em `token`. `GET /api/mcp/tokens` lista os seus tokens (nunca o segredo) e `DELETE /api/mcp/tokens/{id}` revoga um. Um superadmin pode listar os tokens de todos os proprietários com `?all=1` e revogar qualquer um. Cada proprietário pode ter no máximo 20 tokens ativos (acima disso, 412). Estas rotas recusam (403) as credenciais de um agente, por isso um assistente nunca pode criar, listar nem revogar tokens.

## Ligar o seu assistente

O prompt gerado pela caixa contém tudo o que um assistente compatível com MCP precisa: o nome do servidor `facet`, o URL (`http://<host>/mcp`), o transporte (Streamable HTTP), o cabeçalho `Authorization: Bearer fct_...`, o nível de acesso concedido e uma chamada à ferramenta `status` para confirmar a ligação. Cole-o no seu assistente, ou adicione você mesmo esse servidor ao cliente MCP que utiliza. Use HTTPS quando o visualizador for acessível para além da sua própria máquina, pois o token viaja num cabeçalho em cada chamada.

## Níveis de permissão

Um token é criado com um nível concedido: `readonly`, `user` ou `edition`. O nível **efetivo** é recalculado em cada chamada como o menor entre o do token e o atual do seu proprietário:

- Instalações com palavra-passe única: `user` é limitado a `readonly` na criação, porque esse modo não tem nível intermédio. Um token `edition` exige uma sessão de edição e só funciona enquanto a palavra-passe de edição não mudar.
- Instalações multiutilizador: o token `edition` de um utilizador entretanto despromovido desce para `user`; uma promoção nunca eleva um token acima do nível concedido.
- Instalações abertas (sem `viewer.password`, mesmo que `viewer.edition_password` esteja definida): os tokens são sempre `readonly` e pertencem a um proprietário partilhado `_anonymous`.
- As instalações com palavra-passe única não têm o nível `user`: o nível efetivo é `edition` ou `readonly`, pelo que as ferramentas marcadas `user` em [Alterar a biblioteca](#alterar-a-biblioteca) também precisam aí de um token `edition`. Uma ferramenta `user` chamada com um token de nível inferior responde `forbidden_level`, indicando que precisa de `edition`.
- Cada ferramenta tem o seu próprio nível mínimo, verificado antes de ler ou escrever o que quer que seja; um token inferior recebe `forbidden_level`.

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
| `status` | Quem é o token, o seu nível efetivo e as sinalizações do servidor e os separadores abertos que pode controlar |

Em cada objeto de filtros, `show_rejected` é um booleano: `true` lista apenas as fotos rejeitadas, `false` ou omitido dá a listagem normal.

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
- Uma ferramenta só chega aos separadores do dono do token. Com uma única palavra-passe todas as sessões são o mesmo utilizador; numa instalação aberta cada separador pertence ao utilizador partilhado `_anonymous`, incluindo as sessões de edição.
- Cada separador tem o nível da sessão que o abriu, e um token só controla separadores de nível igual ou superior ao seu nível efetivo: um token `edition` nunca usa um separador com sessão apenas de consulta, enquanto um token `readonly` pode controlar um separador `edition`. Com uma palavra-passe única, um token também é limitado pela sessão que o criou: um token criado numa sessão apenas de consulta só alcança separadores de consulta, nunca o separador `edition` (um token anterior a esta regra é limitado ao seu próprio nível). Um separador só pode ser substituído por outro de nível igual ou superior: uma sessão apenas de consulta que reutilize o `tab_id` de um separador `edition` é recusada com 4409 e, acima do limite de separadores por utilizador, sai primeiro o de nível mais baixo. O `status` lista apenas os separadores que o token pode controlar. `status` também indica `out_of_reach_tabs`, o número de separadores abertos que este token não consegue controlar.
- Com vários separadores abertos usa-se o que teve o foco mais recentemente e o campo `tab` do resultado di-lo. Passe `tab_id` (listado por `status`) para escolher outro.
- Um separador recusa o que a sua conta não pode fazer (por exemplo `/culling` para uma conta sem edição) e a ferramenta devolve essa recusa.
- O que um separador devolve não é de confiança: a profundidade e o comprimento de cadeias e listas são limitados, e tudo fica contido por `max_bytes`.
- Erros: `no_tab` (nenhum separador ligado, ou ponte desativada), `tab_timeout` (sem resposta em `call_timeout_s`) e `tab_outdated` (o separador aberto não conhece a ferramenta; recarregue a página depois de atualizar o Facet).
- A ponte aceita primeiro o WebSocket e depois recusa-o com um código de fecho em vez de um estado HTTP: 4404 se o endpoint ou a ponte estiver desativado (o separador fica então desligado até a página ser recarregada), 4403 se faltar `Origin` ou não for permitido, 4401 para uma sessão em falta ou rejeitada.
- Um proxy reverso tem de reencaminhar a atualização para WebSocket em `/api/mcp/bridge`; veja [Implantação](DEPLOYMENT.md). Se reescrever o cabeçalho `Host`, indique a origem pública em `viewer.mcp.allowed_origins` (por exemplo `["https://photos.example.com"]`), porque a origem da página tem de coincidir com o host ou constar da lista.
- O registo de separadores é por processo, por isso a ponte exige um único worker (o valor por omissão).

Em complemento:

- `ui_set_gallery_filters` leva primeiro à galeria se estiver aberta outra página e depois aplica o patch. Recusa o patch inteiro (`invalid_input`) se nomear um filtro que o separador não sabe controlar; para esses use `search_photos`.
- `ui_get_gallery_view`, `ui_next_page` e `ui_select_photos` com `select_view` precisam que a galeria (ou um álbum) seja a página aberta; caso contrário respondem `no_active_view`; chame antes `ui_navigate` para `/`. Dê a `ui_select_photos` exatamente um de `paths` e `select_view`.
- `no_tab` também significa que não há nenhum separador do Facet aberto: abra o Facet num navegador e inicie sessão. A linha de estado da caixa **Ligar um assistente** mostra se este separador está ligado; a ferramenta `status` lista os separadores abertos e os respetivos id.
- Um separador deixa de se religar quando a sua sessão é recusada (inicie sessão de novo) e espera que volte a ele se outro dos seus separadores tomou o seu lugar.
- A ponte do separador só se liga se o servidor a declarar disponível (o endpoint está ativo e `viewer.mcp.bridge` é true); com a ponte desativada, os separadores não se ligam de todo.
- `ui_set_gallery_filters` recusa um nome de filtro desconhecido com `invalid_input`, e também um patch que indique em simultâneo `category` e `type`, ou `person` e `person_id`. Só oferece os filtros que a galeria sabe mostrar; para os outros use `search_photos`.
- `ui_navigate` abre apenas as páginas estáticas da aplicação: a página de início de sessão, as páginas partilhadas, os URL externos e os caminhos desconhecidos são recusados (`invalid_input`), e as páginas só de edição são recusadas a uma sessão sem edição.
- `ui_select_photos` em modo `remove` com uma seleção de toda a vista ignora os caminhos fora da vista carregada e lista-os como `not_in_view` no resultado.

## WebMCP na página (agentes do navegador)

À parte do endpoint `/mcp`, um separador com sessão iniciada oferece também as mesmas ferramentas `ui_*` aos agentes que vivem no próprio navegador, através da API W3C [WebMCP](https://webmachinelearning.github.io/webmcp/) (`document.modelContext`). Um assistente nativo do navegador vê assim exatamente as ferramentas listadas acima, executa-as no separador que está a ver e não precisa de token.

- **Apenas em contexto seguro.** O Facet só regista as ferramentas em HTTPS ou em `localhost`. Em HTTP simples as ferramentas na página não são oferecidas; a ligação por token acima continua a funcionar.
- Registadas quando `viewer.mcp.enabled` é true e tem a sessão iniciada, e removidas ao terminar a sessão.
- O objeto é `document.modelContext` (o alias obsoleto `navigator.modelContext` não é fornecido). É um polyfill, instalado apenas se o navegador não tiver um nativo, e não pode ser desinstalado: pode existir antes de iniciar sessão sem qualquer ferramenta do Facet e permanece depois de terminar a sessão com uma lista de ferramentas vazia.
- As ferramentas fazem o mesmo, limitadas pelo mesmo nível de conta, que na tabela acima.

## Alterar a biblioteca

As ferramentas de escrita estão ao lado das de leitura na mesma lista `/mcp`. Cada uma passa pelas rotas `/api` do visualizador, pelo que as proteções da rota continuam a aplicar-se, e cada uma conta para o orçamento `write_rate_per_min`. O nível é o mais baixo nível efetivo que pode chamar a ferramenta (veja [Níveis de permissão](#níveis-de-permissão)).

| Ferramenta | Nível | O que faz | Limites |
|------------|-------|-----------|---------|
| `set_rating` | `user` | Define a classificação em estrelas (0-5) de fotos | 50 caminhos |
| `set_favorite` | `user` | Marca ou desmarca fotos como favoritas (marcar retira a rejeição) | 50 caminhos |
| `set_rejected` | `user` | Rejeita ou anula a rejeição de fotos (rejeitar retira a classificação e o favorito) | 50 caminhos |
| `batch_set_rating` | `edition` | Define a classificação de muitas fotos | 1000 caminhos, ou `filters` |
| `batch_set_favorite` | `edition` | Marca muitas fotos como favoritas | 1000 caminhos, ou `filters` |
| `batch_set_rejected` | `edition` | Rejeita muitas fotos | 1000 caminhos, ou `filters` |
| `add_tags` | `edition` | Adiciona etiquetas manuais (separadas das etiquetas de IA) | 10 etiquetas; 1000 caminhos, ou `filters` |
| `remove_tags` | `edition` | Remove etiquetas manuais | 10 etiquetas; 1000 caminhos, ou `filters` |
| `create_album` | `edition` | Cria um álbum vazio (não idempotente: duas vezes cria dois álbuns) | |
| `album_add_photos` | `edition` | Adiciona fotos a um álbum (as já presentes são ignoradas) | 1000 caminhos |
| `album_remove_photos` | `edition` | Remove fotos de um álbum; as fotos não são tocadas | 1000 caminhos |
| `junk_list` | `readonly` | Lista os candidatos da limpeza de rejeitadas, opcionalmente de um só `kind` | 100 por página |
| `junk_reject` | `edition` | Rejeita candidatos da limpeza (igual a `batch_set_rejected`) | 1000 caminhos |
| `junk_clear` | `edition` | Mantém candidatos: marca-os como avaliados e limpos para saírem da fila | 50 caminhos |
| `cull_apply` | `edition` | Copia as fotos a manter, ou move ou envia para o lixo as rejeitadas ([pré-visualizar e confirmar](#ações-destrutivas-pré-visualizar-e-confirmar)) | 10000 caminhos, ou `filters` |
| `delete_photos` | `edition` | Envia os ficheiros para o lixo e elimina as suas linhas da biblioteca ([pré-visualizar e confirmar](#ações-destrutivas-pré-visualizar-e-confirmar)) | 1000 caminhos |

- **As ferramentas `user` precisam de um token de edição numa instalação com palavra-passe única**, que não tem nível intermédio (veja [Níveis de permissão](#níveis-de-permissão)).
- **Semântica de definição.** As ferramentas por foto leem o estado atual e só escrevem uma diferença, pelo que repetir uma chamada é inofensivo; cada caminho indica `changed` ou `already`. Processam um caminho de cada vez e param no primeiro `library_busy`, `outcome_unknown` ou `forbidden_level`, indicando `affected`, os `results` por caminho e `not_attempted`. As ferramentas em lote definem o mesmo estado.
- **Escolher as fotos.** As ferramentas em lote, de etiquetas e `cull_apply` aceitam OU `paths` OU `filters` (o objeto de filtros de `search_photos`), mais uma lista `exclude` opcional. Um alvo `filters` tem de trazer `expected_count`, o número de correspondências dos filtros antes de aplicar `exclude` (o `total` de `search_photos`). O Facet volta primeiro a contar os filtros e não escreve nada se os números diferirem (`invalid_input`, com `actual_count`).
- **De quem é o estado.** As classificações, favoritos e rejeições são os do proprietário do token.
- **Ficheiros ignorados.** Quando `cull_apply` ou `delete_photos` devolve uma lista `skipped` não vazia, o resultado traz também um `skipped_reason`: esses caminhos da biblioteca não têm nenhum ficheiro legível no disco (em falta, movido ou fora das pastas analisadas) e nada foi feito com eles.

### Ações destrutivas: pré-visualizar e confirmar

`cull_apply` (`copy_keeps`, `move_rejects`, `trash_rejects`) e `delete_photos` estão marcados com `destructiveHint` e correm como simulação, a menos que sejam chamados com `dry_run: false`.

1. A simulação não altera nada e lista os ficheiros que copiaria, moveria ou enviaria para o lixo (as listas longas são cortadas a `max_rows`, com um `<key>_count`). Para `move_rejects`, `trash_rejects` e `delete_photos` devolve também um valor `confirm`, válido durante `confirm_expires_in_s` (5 minutos) e para uma só utilização.
2. A chamada real (`dry_run: false`) tem de passar esse `confirm`. O Facet recalcula o conjunto de ficheiros e as opções e compara-os com aqueles para os quais o valor foi emitido. Se algo mudou, o valor fica anulado e a chamada responde `confirmation_required`: repita a simulação.
3. `copy_keeps` não precisa de `confirm`: só escreve cópias. Mesmo assim começa por uma simulação por predefinição.

O valor `confirm` está ligado ao token, à ação e ao conjunto exato de ficheiros mais as opções. Vive em memória num só processo, pelo que um reinício descarta todos os valores pendentes.

**Prática recomendada:** mostre sempre ao utilizador o resumo da simulação (contagens e lista de ficheiros) e obtenha a sua aprovação explícita antes da chamada `dry_run: false`. Nunca confirme por iniciativa própria.

- `move_rejects` e `trash_rejects` só atuam sobre as fotos que o proprietário rejeitou; as restantes são indicadas como `excluded_by_state`. Os ficheiros RAW e `.xmp` acompanhantes (`include_companions`) e os outros fotogramas de um bracketing ou panorama (`include_sequence_siblings`) não são tocados, a menos que o ative.
- `delete_photos` envia os ficheiros para o lixo do sistema e **elimina as suas linhas da biblioteca**: as pontuações, etiquetas e classificações não são recuperáveis, mesmo que os ficheiros o sejam.
- **Pré-requisitos.** `trash_rejects` e `delete_photos` exigem `viewer.cull.allow_trash` a `true` (por predefinição `false`; caso contrário a chamada é recusada). O `target_dir` de `copy_keeps` e `move_rejects` tem de estar numa localização de exportação permitida: `viewer.export.allowed_target_dirs` mais os seus diretórios de análise (veja [Destinos de exportação e seleção](CONFIGURATION.md#destinos-de-exportação-e-seleção)).

## Câmara escura (grupos de triagem)

As ferramentas da câmara escura espelham a página `/culling`. Todas exigem o nível `edition`, mesmo as que apenas listam.

| Ferramenta | O que faz |
|------------|-----------|
| `list_culling_groups` | Lista os grupos (`burst`, `similar`, `scene`, `bracket`, `panorama`, `hdr_panorama`) com as suas fotos e pontuações, ordenáveis e delimitáveis por álbum ou intervalo de datas |
| `culling_profiles` | As predefinições de triagem por género e a predefinida |
| `suggest_culling_profile` | Indica a predefinição adequada a um álbum ou intervalo de captura |
| `keeper_hints` | Dicas por foto «existe uma foto melhor nesta rajada» para até 100 caminhos (vazias se não houver cabeça de classificação treinada) |
| `auto_cull` | Triagem automática de um âmbito com um orçamento de fotos a manter: primeiro a pré-visualização, depois a aplicação com o valor `confirm` |
| `confirm_culling_groups` | Confirma até 20 grupos: mantém os seus `keep_paths` e rejeita o resto dos seus `paths` |

- **Um grupo é identificado pelo par `(type, group_id)`**, nunca só por `group_id`: os ids dos grupos semelhantes são deslocados ao serem fundidos com as rajadas.
- **O valor predefinido `group_by: "all"` devolve apenas rajadas e grupos semelhantes.** Peça explicitamente `scene`, `bracket`, `panorama` ou `hdr_panorama`.
- **Uma página é reduzida para caber em `max_bytes` encurtando a lista `photos` de cada grupo, nunca removendo grupos.** `photo_count` continua a ser o tamanho real, `photos_truncated` assinala um grupo cuja lista foi cortada e `has_more` indica se segue outra página.
- **Bracketings, panoramas e panoramas HDR são mantidos inteiros.** Em `confirm_culling_groups`, `keep_paths` tem de ser igual a `paths` para estes tipos (senão `invalid_input`), e `auto_cull` nunca os divide.
- **Um `keep_paths` vazio rejeita todos os fotogramas do grupo.** A primeira chamada responde então `confirmation_required` com um valor `confirm`; mostre-o ao utilizador e repita a chamada com esse valor. Se um lote parar em `forbidden_level`, `library_busy` ou `rate_limited`, os grupos já concluídos são indicados.
- **`auto_cull` faz uma pré-visualização por predefinição** e devolve a divisão manter/rejeitar por grupo mais um valor `confirm` (só se algo fosse rejeitado). A aplicação recalcula o plano e recusa-o com `confirmation_required` se mudou desde a pré-visualização ou se é demasiado grande para ser confirmado como um só conjunto (restrinja-o com `album_id`, `date_from` e `date_to`, ou `group_by`). Os fotogramas rejeitados alimentam o classificador pessoal como qualquer triagem manual.
- Chame `ui_show_culling_group` para mostrar um grupo ao utilizador no seu separador aberto (veja [Controlar o separador aberto](#controlar-o-separador-aberto)).

## Resultados, limites e erros

Cada resultado é um envelope JSON: `{"ok": true, "data": ...}` ou `{"ok": false, "error": "<code>", "message": "..."}`. As listagens devolvem `data.rows` (um conjunto compacto e fixo de campos por foto) mais `total`.

- **Limites máximos:** no máximo `max_rows` linhas e `max_bytes` bytes serializados. As últimas linhas são descartadas e `truncated: true` é definido. Um resultado sem linhas que exceda `max_bytes` torna-se um erro `too_large`.
- **Limite de taxa:** `rate_per_min` chamadas por minuto e por token para leitura. As ferramentas de escrita usam um orçamento separado, `write_rate_per_min` (30 por predefinição), para que as pesquisas não deixem as escritas sem quota nem o contrário; a simulação de `cull_apply` e `delete_photos` conta como escrita, a pré-visualização de `auto_cull` como leitura. Acima disso: `rate_limited` com `retry_after_s`. Dez tentativas bearer falhadas por minuto a partir do mesmo endereço recebem 429.
- **Códigos de erro:** `forbidden_level` (endpoint desativado, token inválido ou nível insuficiente), `invalid_input`, `not_found`, `rate_limited`, `library_busy`, `upstream_error`, `outcome_unknown`, `confirmation_required`, `too_large`, `no_tab`, `tab_timeout`, `tab_outdated`.
- **Os códigos mais recentes:** `confirmation_required` (uma chamada destrutiva não tem um valor `confirm` válido para este conjunto exato: repita a simulação, mostre o resultado ao utilizador e tente de novo), `outcome_unknown` (uma escrita excedeu o tempo ou a ligação caiu, pelo que pode ou não ter acontecido: volte a ler o estado antes de repetir, nunca repita às cegas), `library_busy` (a biblioteca está ocupada com outra tarefa: tente de novo daqui a pouco).
- **Códigos HTTP à entrada:** 401 para token em falta ou desconhecido, 403 para um pedido de navegador de outra origem ou para as credenciais de um agente em `/api/mcp/tokens`, 404 quando está desativado. A ponte de separadores responde com códigos de fecho.

## Notas de segurança

- Legendas, etiquetas, nomes de ficheiros, caminhos e nomes de álbuns e pessoas vêm da sua biblioteca e podem conter texto escrito para manipular um assistente (injeção de prompts). Cada ferramenta está marcada com `facet/untrusted_content` e diz ao modelo para os tratar como dados. Não dê a um assistente que também lê conteúdo não fiável uma forma de agir sobre o que encontra aqui.
- Os tokens nunca expiram. Revogue os que já não usa.
- Os registos guardam o id do token, a ferramenta, o resultado e o número de linhas, nunca os argumentos nem o token.

## Limitações conhecidas

- Numa instalação aberta (sem palavra-passe), qualquer pessoa que alcance o visualizador pode criar e revogar os tokens `_anonymous` partilhados. Defina uma palavra-passe antes de ativar o endpoint numa rede. A ponte de separador amplia este risco: um cliente que não seja um navegador pode enviar um `Origin` inventado e um token nulo, registar um separador `_anonymous` com o foco, responder às chamadas `ui_*` com os dados que quiser e expulsar separadores reais através do limite de 8 separadores.
- Os limites de frequência e os contadores de autenticações falhadas vivem em memória em cada processo; com `viewer.py --workers N` cada worker conta em separado.
- O registo de separadores vive em memória num só processo. Use um único worker (`viewer.py --workers 1`, o valor por omissão) se depender das ferramentas `ui_*`; com vários workers uma chamada pode chegar a um processo que não conhece o seu separador e responder `no_tab`.
- Um utilizador pode ter no máximo 8 separadores ligados; abrir um nono fecha o mais antigo.
