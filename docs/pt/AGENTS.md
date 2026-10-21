# Agentes de IA (MCP)

> 🌐 [English](../AGENTS.md) · [Français](../fr/AGENTS.md) · [Deutsch](../de/AGENTS.md) · [Italiano](../it/AGENTS.md) · [Español](../es/AGENTS.md) · **Português** · [简体中文](../zh/AGENTS.md)

O Facet pode atuar como servidor [Model Context Protocol](https://modelcontextprotocol.io/) (MCP), de modo que um assistente de IA compatível com MCP possa pesquisar e inspecionar a sua biblioteca com os mesmos filtros da galeria. Expõe treze ferramentas de leitura que não alteram nada na biblioteca e doze ferramentas `ui_*` que movem o separador do navegador que já tem aberto (página, filtros, seleção) e nunca escrevem dados da biblioteca. Os tokens autorizados também podem [alterar a biblioteca](#alterar-a-biblioteca) (classificações, marcadores, etiquetas, álbuns, triagem e eliminação) e usar a [câmara escura](#câmara-escura-grupos-de-triagem).

## Ativá-lo

O endpoint está **ativado por predefinição**. Para o desligar, defina `viewer.mcp.enabled` como `false` em `scoring_config.json` (ver [Endpoint de agentes (MCP)](CONFIGURATION.md#endpoint-de-agentes-mcp)) e reinicie o visualizador, ou recarregue a configuração; `/mcp` e todas as rotas `/api/mcp/*` respondem então 404. Sem `viewer.password` a instalação é considerada aberta, mesmo que `viewer.edition_password` esteja definida: os seus tokens são `readonly`, a menos que `viewer.trusted_local_editing` esteja ativo. Numa instalação aberta o endpoint serve apenas uma chave anónima só de leitura, que não concede nada que a `/api` aberta não conceda já.

O endpoint é `POST /mcp` na porta do visualizador: Streamable HTTP, sem estado, respostas JSON simples. `GET` responde 405. Só a ponte do separador, `/api/mcp/bridge`, é um WebSocket; veja [Controlar o separador aberto](#controlar-o-separador-aberto).

## Criar um token

O mais simples é o navegador. Com `viewer.mcp.enabled` ativo, abra o menu da conta e escolha **Ligar um assistente**. Introduza um **Nome**, escolha **O que o assistente pode fazer**: **Apenas ler e controlar**, mais **Agir como eu** ou **Edição completa** se a sua sessão tiver esse nível (um token não pode superar a sessão que o cria), e clique em **Criar token**. A caixa mostra então **Cole isto no seu assistente** com um prompt já pronto que contém o token. É mostrado uma única vez: clique em **Copiar prompt**, cole-o no seu assistente e clique em **Concluir**. **Gerir tokens (N)** lista os seus tokens com a última utilização e permite revogar um, e uma linha de estado indica se este separador está ligado e, portanto, controlável pelos assistentes. A lista de níveis limita-se ao que o servidor concederá: uma instalação aberta oferece apenas **Apenas ler e controlar**, **Agir como eu** só aparece em instalações multiutilizador e **Edição completa** só numa sessão de edição, o que numa instalação aberta significa um navegador no mesmo computador com `viewer.trusted_local_editing` ativo. O prompt indica o nível efetivamente concedido.

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
- Instalações abertas (sem `viewer.password`, mesmo que `viewer.edition_password` esteja definida): os tokens pertencem a um proprietário partilhado `_anonymous` e são `readonly`, a menos que `viewer.trusted_local_editing` esteja ativo (ponto seguinte).
- **Edição local numa instalação aberta.** Com `viewer.trusted_local_editing` ativo, a caixa «Ligar um assistente» pode criar um token de **Edição completa** a partir de um navegador no mesmo computador (`viewer.mcp.enabled` continua necessário, tal como um token: uma chamada sem token continua a ser 401). Esse token é `edition` apenas para pedidos `/mcp` da mesma máquina: par em loopback, URL `http://localhost:<port>` ou `127.0.0.1` e sem cabeçalhos de proxy; servem tanto `:4200` (o proxy de desenvolvimento do `ng serve`) como `:5000`. Qualquer outro pedido com o mesmo token, incluindo um cliente da rede local, passa a `readonly`, tal como um URL com nome de anfitrião ou `0.0.0.0` ou uma implantação Docker, mesmo que o prompt diga Edição completa. Qualquer palavra-passe baixa o token para `readonly`, e remover a palavra-passe reativa-o (o token em si não é tocado). As ferramentas de eliminação continuam a precisar de `viewer.mcp.allow_destructive`. A análise (`start_scan`, `scan_status`) funciona para o assistente local, como para o navegador local, sem `viewer.features.show_scan_button`.
- **Ressalva.** `ng serve --host 0.0.0.0`, ou qualquer proxy não assinalado no mesmo computador, deixa um cliente da rede local que envie `Host: localhost` passar a fronteira; resta apenas o token a proteger `/mcp`.
- As instalações com palavra-passe única não têm o nível `user`: o nível efetivo é `edition` ou `readonly`, pelo que as ferramentas marcadas `user` em [Alterar a biblioteca](#alterar-a-biblioteca) também precisam aí de um token `edition`. Uma ferramenta `user` chamada com um token de nível inferior responde `forbidden_level`, indicando que precisa de `edition`.
- Cada ferramenta tem o seu próprio nível mínimo, verificado antes de ler ou escrever o que quer que seja; um token inferior recebe `forbidden_level`.

Um token deixa de valer automaticamente quando as credenciais do seu proprietário mudam: a palavra-passe do visualizador ou de edição no modo de palavra-passe única, a palavra-passe do proprietário no modo multiutilizador, ou a eliminação da sua conta. Recebe então um 401 à entrada.

## Ferramentas

As treze ferramentas de dados são só de leitura:

| Ferramenta | O que faz |
|------|--------------|
| `search_photos` | Filtra e ordena a biblioteca como a galeria, aplicando as ocultações padrão do visualizador (piscadelas, rajadas, duplicados, brackets, panorâmicas, rejeitadas) a menos que o filtro as defina (informa `hidden_summary`). Mostrado por padrão na sua aba aberta (veja abaixo); `fields` acrescenta qualquer coluna da foto |
| `semantic_search` | Encontra fotos pelo significado, ou por palavras das legendas com `scope: "text"` (não mostrado na aba). `filters` restringem a pesquisa como os da galeria, e cada linha traz a sua `similarity`. |
| `get_photo` | Detalhe completo de uma foto a partir do seu caminho (sem o histograma) |
| `get_thumbnail` | Ver uma foto: a miniatura como parte de imagem (`size` de 160 a 640, 512 por omissão). Usa-se um tamanho menor se o JPEG excedesse `viewer.mcp.max_image_bytes`; `too_large` se nenhum couber |
| `contact_sheet` | Ver de 1 a 16 fotos como uma grelha numerada (`columns` de 2 a 4, lado mais comprido 1024). A parte de texto lista `legend` (número da célula e caminho, na ordem pedida) e `unavailable` (células em branco porque a foto falta ou não é visível) |
| `possible_faces` | Rostos parecidos com uma pessoa reconhecida: semelhança cosseno com o centroide da pessoa, os melhores primeiro, apenas o mesmo modelo de embedding. `scope` é `unassigned` (omissão), `other_persons` ou `all`; `min_similarity` é 0,30 por omissão; `limit` até 100. Uma análise com mais de 192000 rostos é recusada (`too_large`): restrinja com `scope`, `path_prefix`, `date_from` ou `date_to`. As fotos são mostradas na sua aba. `candidates` é o número de rostos no âmbito que você pode ver, antes da verificação da dimensão do embedding; `faces_scanned` é o número de linhas realmente pontuadas. |
| `similar_photos` | Fotos semelhantes a uma foto, por embedding visual ou por cor; `min_similarity` (de 0 a 1) define o limite |
| `filter_options` | O vocabulário que um filtro aceita: câmaras, objetivas, etiquetas, pessoas, padrões, categorias, momentos narrativos, tipos de lixo, intervalos de métricas |
| `list_persons` | Pessoas reconhecidas, filtráveis por nome |
| `list_albums` | Álbuns que o proprietário do token pode ver |
| `library_stats` | Estatísticas da biblioteca: `kind` escolhe o resumo de tamanho e pontuações (padrão) ou qualquer dado da página Estatísticas (veja abaixo) |
| `status` | Quem é o token, o seu nível efetivo e as sinalizações do servidor e os separadores abertos que pode controlar |
| `available_actions` | As tarefas que se aplicam agora à sua aba aberta e a este token, cada uma com as suas ferramentas; ferramentas acima do nível do token não são listadas |

Em cada objeto de filtros, `show_rejected` é um booleano: `true` lista apenas as fotos rejeitadas, `false` ou omitido dá a listagem normal.

## Os resultados aparecem na sua aba

- `search_photos`, `semantic_search` e `similar_photos` aceitam `show` (padrão `true`). Depois de uma busca bem-sucedida da primeira página, o servidor aplica a mesma consulta à aba do Facet aberta, substituindo os filtros dela: você vê o que o assistente encontrou sem precisar pedir. Os assistentes são instruídos a nunca perguntar se devem abrir ou mostrar os resultados; `show: false` serve para sondagens intermediárias e contagens, e a última busca mostrada é a que você vê.
- O resultado traz `shown_in_tab`: `{"applied": true, "tab_id", "keys", "total"}`, ou `{"applied": false, "reason"}` em que o motivo é `no_tab`, `bridge_disabled`, `tab_outdated`, `tab_timeout` (a aba ainda pode aplicá-la), `forbidden`, `page_not_first`, `empty_result`, `unsupported_filters` (com `keys`) ou `invalid_combination`. Uma exibição que falha nunca faz a busca falhar. Passe `tab_id` para escolher uma aba. Todos os motivos: `error` (a própria exibição falhou), `bridge_disabled`, `page_not_first`, `empty_result`, `invalid_combination`, `unsupported_filters` (com `keys`; em `semantic_search` são `scope` ou `threshold`, um limite acima de 0,5 que o controle deslizante da barra lateral não consegue expressar) e os códigos devolvidos pela ponte de abas (`no_tab`, `tab_outdated`, `tab_timeout`, `forbidden`, `invalid_input`, `upstream_error`). A aba pagina sozinha, então numa busca semântica ela pode mostrar mais linhas do que o assistente recebeu. Quando linhas são cortadas, `next_page` (com `suggested_per_page`) indica a página que continua exatamente após a última linha devolvida ou, se as páginas não conseguem expressar isso, `next_offset` a dá como deslocamento de linhas.
- Só a primeira página é mostrada (a aba pagina sozinha ao rolar) e um resultado vazio não é mostrado, para você manter a vista anterior. Uma busca com filtros para os quais a barra lateral da galeria não tem campo (`exclude_tags`, `require_tags`, `is_silhouette`, `junk_kind`, `narrative_moment`, `min_rating`, `min_aggregate`, `show_rejected: true`) não é aplicada parcialmente, e `semantic_search` com `scope: "text"` também não é mostrada.
- Mostrar sai de `/culling`, `/compare` e `/photo` para a galeria, limpa uma seleção de toda a vista e, na página de um álbum, volta primeiro à galeria, de modo que os filtros salvos de um álbum nunca são sobrescritos. Uma busca cuja contagem alimenta o `expected_count` de uma ferramenta de escrita deve usar `show: false`.
- `ui_show_photos` fixa uma lista exata de fotos: a galeria mostra-as na sua ordem até uma alteração de filtro substituir a lista. `ui_get_context` indica se uma lista fixada é mostrada. Os campos opcionais `groups` (um número de grupo por caminho) e `marks` (`keep` ou `remove` por caminho) anotam as fotos fixadas: cada grupo começa na sua própria linha sob um cabeçalho («Grupo 3 — 4 fotos · 2 manter · 1 remover», contadas a partir das marcas atuais, ou apenas «Grupo 3» quando a lista não tem marcas), e cada cartão marcado tem na base uma faixa Manter/Remover de largura total em que pode clicar para a inverter. Uma foto marcada Remover fica esbatida (o cinzento fica reservado para uma rejeição real), um ponto indica uma marca que alterou, e uma legenda de chips conta os grupos, os Manter e os Remover. Com o cursor numa foto marcada, `K` marca-a Manter e `R` marca-a Remover, passando depois à foto seguinte; `X` continua a ser a rejeição real. As suas inversões ficam no separador até a lista ser limpa, e `ui_get_context.review` devolve-as como `{keep, remove}` (até 1000 caminhos cada) para que o assistente atue de acordo com as suas edições.
- **Datas.** As ferramentas de triagem (`auto_cull`, `list_culling_groups`, `suggest_culling_profile`) aceitam uma data ISO (`2026-06-01`), uma data e hora ISO (`2026-06-01T08:30:00` ou com espaço) ou a forma EXIF (`2026:06:01 08:30:00`); um `date_to` sem hora cobre o dia inteiro. As ferramentas com granularidade de dia (`library_stats`, `possible_faces`, `cull_report` tanto nas contagens como nos conjuntos da câmara escura) só aceitam uma data e recusam uma hora com `invalid_input`.
- As linhas trazem câmera, objetiva, abertura, velocidade do obturador, ISO, distância focal e `is_monochrome`. `fields` (nas três ferramentas de busca) acrescenta qualquer outra coluna da foto, exceto dados de imagem e de embeddings, por exemplo `leading_lines_score`; `learned_score` só é preenchido ao ordenar por ele. Quando o limite de bytes corta linhas, o resultado acrescenta `returned` (e `next_offset` ou `suggested_per_page`).
- `library_stats` aceita `kind` (padrão `overview`: tamanho, contagens por tipo e resumo das pontuações). A visão geral inclui um `basis` que indica o que cada total conta: `total_photos` conta as fotos que pode ver dentro de `date_from`/`date_to` e da categoria (todas as datas e categorias se nenhuma for indicada), ignora os interruptores de ocultação e inclui as fotos rejeitadas, enquanto `type_counts` aplica os interruptores de ocultação e ignora os filtros de data e categoria. Os demais valores são somente leitura e devolvem os dados da página Estatísticas; listas longas são cortadas em 50 entradas com `truncated: true`:

| Valor de kind | Dados |
|------|------|
| `score_distribution`, `top_cameras`, `categories`, `gear`, `stats_settings`, `timeline`, `correlations` | Os painéis da página Estatísticas; aceitam `date_from`, `date_to` e `category`. `correlations` aceita também `x`, `y` (lista separada por vírgulas), `group_by` e `min_samples` |
| `category_breakdown`, `category_weights`, `category_correlations`, `category_overlap` | Estatísticas por categoria (sem parâmetros) |
| `timeline_dates`, `timeline_months` | Número de fotos por dia ou por mês; exigem `year` (`timeline_dates` aceita também `month`) |
| `timeline_years` | Número de fotos por ano |

## Controlar o separador aberto

Ao lado das ferramentas de dados, o servidor lista sempre doze ferramentas `ui_*` que atuam sobre o separador do Facet que tem aberto num navegador: mudam de página, alteram os filtros ou a seleção e voltam a ler o que vê. Nunca escrevem dados da biblioteca, por isso basta um token `readonly`.

| Ferramenta | O que faz |
|------------|-----------|
| `ui_navigate` | Ir para uma página (galeria, pessoas, álbuns, estatísticas, ...) |
| `ui_set_gallery_filters` | Juntar uma alteração aos filtros e à ordenação da galeria (`null` remove um filtro, `replace: true` parte do zero) |
| `ui_get_gallery_view` | Rota, filtros ativos, total de resultados, os primeiros caminhos de fotos visíveis e o número de fotos selecionadas |
| `ui_get_context` | A página aberta (rota), o estado da galeria (total, quantidade carregada, se uma lista fixada é mostrada), o número de fotos selecionadas e as `actions` que aqui se aplicam ao seu token |
| `ui_open_photo` | Abrir uma foto |
| `ui_show_photos` | Mostra exatamente estes `paths` (até 200) por esta ordem como lista da galeria; os inalcançáveis voltam em `missing`. Qualquer alteração de filtro substitui a lista. Os campos opcionais `groups` e `marks` (uma entrada por caminho) numeram as fotos e marcam cada uma como Manter ou Remover; pode inverter uma marca no cartão e `ui_get_context.review` devolve as suas escolhas |
| `ui_select_photos` | Selecionar `paths` explícitos, ou toda a vista filtrada com `select_view: true`, em modo `replace`, `add` ou `remove` |
| `ui_clear_selection` | Limpar a seleção |
| `ui_get_selection` | O `scope` (`paths` ou `view`) e o `count`, com os `paths` ou, numa vista, os `filters` e os `excluded_paths` |
| `ui_next_page` | Carregar a página seguinte da galeria |
| `ui_show_culling_group` | Abrir a câmara escura num grupo, identificado por `(type, group_id)` (contas de edição) |
| `ui_show_comparison` | Abrir a página de comparação por pares, opcionalmente numa categoria e numa estratégia; apenas abre a página, os vencedores são escolhidos por si |

Como funciona:

- Enquanto tiver sessão iniciada e `viewer.mcp.enabled` e `viewer.mcp.bridge` forem `true`, cada separador do Facet abre um WebSocket da mesma origem para `/api/mcp/bridge` e autentica-se com a sua sessão na primeira mensagem. A ponte vem ativa por omissão; ponha `viewer.mcp.bridge` a `false` para a desativar e as ferramentas `ui_*` passam a responder com um erro claro.
- `ui_get_context` lê a página aberta, o estado da galeria, o número de fotos selecionadas e as `actions` que se aplicam a esta página e a este token; `available_actions` responde à mesma pergunta a partir do servidor para a sua aba aberta. Ferramentas acima do nível do token não são listadas.
- Uma ferramenta só chega aos separadores do dono do token. Com uma única palavra-passe todas as sessões são o mesmo utilizador; numa instalação aberta cada separador pertence ao utilizador partilhado `_anonymous`, incluindo as sessões de edição.
- Cada separador tem o nível da sessão que o abriu, e um token só controla separadores de nível igual ou superior ao seu nível efetivo: um token `edition` nunca usa um separador com sessão apenas de consulta, enquanto um token `readonly` pode controlar um separador `edition`. Com uma palavra-passe única, um token também é limitado pela sessão que o criou: um token criado numa sessão apenas de consulta só alcança separadores de consulta, nunca o separador `edition` (um token anterior a esta regra é limitado ao seu próprio nível). Numa instalação aberta um token também é limitado ao nível de consulta: só alcança separadores de consulta, nunca um separador `edition`, exceto o separador de edição local (ver abaixo). Um separador só pode ser substituído por outro de nível igual ou superior: uma sessão apenas de consulta que reutilize o `tab_id` de um separador `edition` é recusada com 4409 e, acima do limite de separadores por utilizador, sai primeiro o de nível mais baixo. O `status` lista apenas os separadores que o token pode controlar. `status` também indica `out_of_reach_tabs`, o número de separadores abertos que este token não consegue controlar. Com `viewer.trusted_local_editing` numa instalação aberta, um separador cujo handshake passa a fronteira «mesma máquina» regista-se como `edition` e desce para `readonly` num ping quando a opção é desligada; os separadores da rede local ou reencaminhados continuam `readonly`. Um token usado a partir da máquina local alcança esse separador de edição local seja qual for o nível com que foi criado, ao passo que um token usado a partir de outra máquina (rede local) nunca o alcança e recebe `no_tab`, com uma mensagem a explicar que um pedido não local não pode controlar um separador de edição local.
- Com vários separadores abertos usa-se o que teve o foco mais recentemente e o campo `tab` do resultado di-lo. Passe `tab_id` (listado por `status`) para escolher outro.
- Um separador recusa o que a sua conta não pode fazer (por exemplo `/culling` para uma conta sem edição) e a ferramenta devolve essa recusa.
- O que um separador devolve não é de confiança: a profundidade e o comprimento de cadeias e listas são limitados, e tudo fica contido por `max_bytes`.
- Erros: `no_tab` (nenhum separador ligado, ou ponte desativada), `tab_timeout` (sem resposta em `call_timeout_s`) e `tab_outdated` (o separador aberto não conhece a ferramenta; recarregue a página depois de atualizar o Facet).
- A ponte aceita primeiro o WebSocket e depois recusa-o com um código de fecho em vez de um estado HTTP: 4404 se o endpoint ou a ponte estiver desativado (o separador fica então desligado até a página ser recarregada), 4403 se faltar `Origin` ou não for permitido, 4401 para uma sessão em falta ou rejeitada.
- Um proxy reverso tem de reencaminhar a atualização para WebSocket em `/api/mcp/bridge`; veja [Implantação](DEPLOYMENT.md). Se reescrever o cabeçalho `Host`, indique a origem pública em `viewer.mcp.allowed_origins` (por exemplo `["https://photos.example.com"]`), porque a origem da página tem de coincidir com o host ou constar da lista.
- O registo de separadores é por processo, por isso a ponte exige um único worker (o valor por omissão).

Em complemento:

- `ui_set_gallery_filters` leva primeiro à galeria se estiver aberta outra página e depois aplica o patch. Recusa o patch inteiro (`invalid_input`) se nomear um filtro que o separador não sabe controlar; para esses use `search_photos`. Na página de um álbum, qualquer alteração volta primeiro à galeria (não só `replace: true`), de modo que os filtros salvos do álbum não são sobrescritos e o âmbito do álbum é abandonado. Aceita também `semantic_query`, `semantic_threshold` (de 0 a 0,5), `similar_to`, `similarity_mode` e `min_similarity` (de 0 a 1); `similar_to` e `semantic_query` não podem ser combinados.
- `ui_get_gallery_view`, `ui_next_page` e `ui_select_photos` com `select_view` precisam que a galeria (ou um álbum) seja a página aberta; caso contrário respondem `no_active_view`; chame antes `ui_navigate` para `/`. Dê a `ui_select_photos` exatamente um de `paths` e `select_view`.
- `no_tab` também significa que não há nenhum separador do Facet aberto: abra o Facet num navegador e inicie sessão. A linha de estado da caixa **Ligar um assistente** mostra se este separador está ligado; a ferramenta `status` lista os separadores abertos e os respetivos id.
- Um separador deixa de se religar quando a sua sessão é recusada (inicie sessão de novo) e espera que volte a ele se outro dos seus separadores tomou o seu lugar.
- A ponte do separador só se liga se o servidor a declarar disponível (o endpoint está ativo e `viewer.mcp.bridge` é true); com a ponte desativada, os separadores não se ligam de todo.
- `ui_set_gallery_filters` recusa um nome de filtro desconhecido com `invalid_input`, e também um patch que indique em simultâneo `category` e `type`, ou `person` e `person_id`. Só oferece os filtros que a galeria sabe mostrar; para os outros use `search_photos`.
- `ui_navigate` abre apenas as páginas estáticas da aplicação: a página de início de sessão, as páginas partilhadas, os URL externos e os caminhos desconhecidos são recusados (`invalid_input`), e as páginas só de edição são recusadas a uma sessão sem edição.
- `ui_select_photos` em modo `remove` com uma seleção de toda a vista ignora os caminhos fora da vista carregada e lista-os como `not_in_view` no resultado.

## Atualizações em direto

Quando um assistente altera fotos com uma ferramenta de escrita, os separadores do Facet que tem abertos acompanham sem recarregar.

- **O que se atualiza.** A galeria atualiza no próprio local os cartões alterados, mantém a lista fixada de uma revisão do assistente com as suas marcas e retira uma foto eliminada da biblioteca (`delete_photos`). Uma foto que `cull_apply` moveu ou enviou para o lixo mantém a sua linha na biblioteca, pelo que permanece numa revisão fixada, enquanto as vistas que ocultam as fotos rejeitadas (o valor por omissão) já a ocultam. Uma escrita que não consegue nomear as suas fotos (ver abaixo) recarrega a vista em vez disso, mantendo no ecrã as linhas atuais e a sua seleção até chegarem as novas, pelo que a grelha nunca fica em branco. As vistas de pesquisa semântica e de fotos semelhantes atualizam as fotos já mostradas e nunca retiram nenhuma, mesmo perante uma escrita que não consegue nomear as suas fotos. A página de uma foto volta a pedi-la (uma foto eliminada da biblioteca leva-o de volta). A câmara escura (`/culling`) atualiza no local rejeição, favorito e classificação, mostra um indicador Rejeitada e mantém as suas próprias decisões; perante uma alteração que não consegue delimitar, só recarrega quando nada está em jogo; caso contrário, mostra um banner Recarregar que permanece até recarregar.
- **Um só aviso por rajada.** As alterações são agrupadas (anti-ressalto de 400 ms, no máximo 2 s) num único aviso «O assistente alterou N fotos».
- **Que escritas.** Classificações, favoritos, rejeições, etiquetas, legendas, pertença a álbuns, seleções, eliminações, correções de sequência e de categoria, atribuições de rostos, limpeza de descartes e confirmações da câmara escura. Leituras, simulações, escritas recusadas, criação de álbuns, exportação de metadados e análises não contam. Uma escrita que expira (`outcome_unknown`) atualiza mesmo assim, porque a escrita pode ter sido aplicada; uma escrita ainda em curso nesse momento surge na atualização ou recarga seguinte.
- **Escritas sem âmbito.** Uma escrita dirigida a uma vista `filters`, uma que inclui os fotogramas irmãos de um conjunto, uma com mais de 200 fotos ou uma que não nomeia nenhum caminho recarrega a vista em vez de atualizar cartões nomeados.
- **A ponte tem de estar ativa.** Uma escrita feita por `/mcp` chega aos seus separadores pela ponte do separador, por isso `viewer.mcp.bridge` tem de ser `true`. Uma escrita feita pela própria página (`POST /api/mcp/call`) é guiada pela resposta (`changed_paths`) e atualiza mesmo com a ponte desativada.
- **Só no mesmo processo.** O aviso só chega aos separadores do autor ligados ao mesmo processo do servidor; com `viewer.py --workers N` pode faltar um separador (a ponte exige um único worker, o valor por omissão).
- **Após uma atualização, recarregue os separadores abertos.** A lista de ferramentas mudou: um separador aberto responde `tab_outdated` até ser recarregado.

## WebMCP na página (agentes do navegador)

À parte do endpoint `/mcp`, um separador com sessão iniciada oferece também as mesmas ferramentas `ui_*` aos agentes que vivem no próprio navegador, através da API W3C [WebMCP](https://webmachinelearning.github.io/webmcp/) (`document.modelContext`). Um assistente nativo do navegador vê assim exatamente as ferramentas listadas acima, executa-as no separador que está a ver e não precisa de token.

- **Apenas em contexto seguro.** O Facet só regista as ferramentas em HTTPS ou em `localhost`. Em HTTP simples as ferramentas na página não são oferecidas; a ligação por token acima continua a funcionar.
- Registadas quando `viewer.mcp.enabled` é true e tem a sessão iniciada, e removidas ao terminar a sessão.
- O objeto é `document.modelContext` (o alias obsoleto `navigator.modelContext` não é fornecido). É um polyfill, instalado apenas se o navegador não tiver um nativo, e não pode ser desinstalado: pode existir antes de iniciar sessão sem qualquer ferramenta do Facet e permanece depois de terminar a sessão com uma lista de ferramentas vazia.
- As ferramentas fazem o mesmo, limitadas pelo mesmo nível de conta, que na tabela acima.
- Um agente do navegador lê a mesma lista `actions` através de `ui_get_context`.
- **Ferramentas da biblioteca na página.** O separador também oferece as ferramentas próprias do servidor (pesquisa, classificações, etiquetas, álbuns, câmara escura, relatórios) através de `GET /api/mcp/inpage_tools` (a lista, com o esquema de cada ferramenta, o seu `required_level` e o `level` atual da sessão) e `POST /api/mcp/call` (`{tool, arguments, selection_snapshot?}`). Executam-se como a sua sessão iniciada, pelo mesmo invólucro que `/mcp`, pelo que níveis, pré-visualizações, valores `confirm` e limites de taxa se comportam de forma idêntica. Uma ferramenta que falha devolve um envelope `ok: false` normal (HTTP 200); uma chamada também devolve `changed` (fotografias escritas).
- **Nível.** O nível é o mais baixo entre o da sua sessão e o seu papel atual, lido de novo em cada chamada: uma conta despromovida perde as escritas de imediato e uma eliminada é recusada (401). Abaixo do mínimo de uma ferramenta a resposta é `forbidden_level` («This session's level is readonly; set_rating needs edition: unlock edition in Facet»). Numa instalação com uma única palavra-passe, uma sessão que escreve tem de ter a edição desbloqueada.
- **Quem pode chamar.** Apenas uma pessoa com sessão iniciada. O token `/mcp` de um agente é recusado nestas rotas (403), tal como uma `Origin` estranha; um cookie sozinho nunca autentica. Cada chamada leva um cabeçalho `X-Facet-Agent-Session` (1 a 64 letras, dígitos, `_` ou `-`; se faltar ou estiver malformado responde 400). Distingue os separadores: um valor `confirm` emitido para um separador é recusado a outro; é a página que o escolhe, pelo que separa mas não autentica.
- **O que fica de fora.** As ferramentas de imagem (`get_thumbnail`, `contact_sheet`) e `available_actions` (use `ui_get_context`). O argumento `show` de uma ferramenta está sempre desligado, porque quem chama é o separador, e `tab_id` é recusado. `status` indica apenas as versões do servidor e do contrato da interface. `target: "selection"` usa o `selection_snapshot` enviado pela página (o que `ui_get_selection` devolveu) e sem ele dá `invalid_input`. As ações destrutivas continuam a seguir `viewer.mcp.allow_destructive`.
- **Gosto.** Como qualquer escrita de um assistente, uma chamada de ferramenta feita a partir da página nunca regista comparações nem arma o retreino.
- **Interruptor.** `viewer.mcp.inpage_tools` (por omissão `true`) desliga as duas rotas (404) e põe `features.mcp_inpage` a falso em `/api/auth/status`; `viewer.mcp.enabled: false` também as desliga.

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
| `assign_faces` | `edition` | Move rostos para uma pessoa; os de outra pessoa ficam como estão salvo `allow_reassign`, e o resultado lista o que foi ignorado | 50 ids de rosto |
| `set_caption` | `edition` | Define a legenda de uma foto (semântica de conjunto; uma legenda inalterada volta como `already`) | 1 foto, 2000 caracteres |
| `export_metadata` | `edition` | Escreve sidecars XMP junto aos ficheiros | 100 caminhos, ou `filters`, ou `target` |
| `junk_list` | `readonly` | Lista os candidatos da limpeza de rejeitadas, opcionalmente de um só `kind` | 100 por página |
| `junk_reject` | `edition` | Rejeita candidatos da limpeza (igual a `batch_set_rejected`) | 1000 caminhos |
| `junk_clear` | `edition` | Mantém candidatos: marca-os como avaliados e limpos para saírem da fila | 50 caminhos |
| `cull_apply` | `edition` | Copia as fotos a manter, ou move ou envia para o lixo as rejeitadas ([pré-visualizar e confirmar](#ações-destrutivas-pré-visualizar-e-confirmar)) | 10000 caminhos, ou `filters` |
| `delete_photos` | `edition` | Envia os ficheiros para o lixo e elimina as suas linhas da biblioteca ([pré-visualizar e confirmar](#ações-destrutivas-pré-visualizar-e-confirmar)) | 1000 caminhos |

- **As ferramentas `user` precisam de um token de edição numa instalação com palavra-passe única**, que não tem nível intermédio (veja [Níveis de permissão](#níveis-de-permissão)).
- **Semântica de definição.** As ferramentas por foto leem o estado atual e só escrevem uma diferença, pelo que repetir uma chamada é inofensivo; cada caminho indica `changed` ou `already`. Processam um caminho de cada vez e param no primeiro `library_busy`, `outcome_unknown` ou `forbidden_level`, indicando `affected`, os `results` por caminho e `not_attempted`. As ferramentas em lote definem o mesmo estado.
- **Escolher as fotos.** As ferramentas em lote, de etiquetas e `cull_apply` aceitam OU `paths` OU `filters` (o objeto de filtros de `search_photos`), mais uma lista `exclude` opcional. Um alvo `filters` tem de trazer `expected_count`, o número de correspondências dos filtros antes de aplicar `exclude` (o `total` de `search_photos`). O Facet volta primeiro a contar os filtros e não escreve nada se os números diferirem (`invalid_input`, com `actual_count`). As ocultações padrão do visualizador (incluindo as fotos rejeitadas) aplicam-se a `filters` exatamente como em `search_photos`, pelo que o seu `total` é o `expected_count`. As fotos rejeitadas ficam assim ocultas de um alvo `filters`: para `move_rejects` e `trash_rejects`, passe `show_rejected` (ou `hide_rejected: false`) tanto a `search_photos` COMO a `cull_apply`; `copy_keeps` não precisa de mais nada.
- **De quem é o estado.** As classificações, favoritos e rejeições são os do proprietário do token.
- **Ficheiros ignorados.** Quando `cull_apply` ou `delete_photos` devolve uma lista `skipped` não vazia, o resultado traz também um `skipped_reason`: esses caminhos da biblioteca não têm nenhum ficheiro legível no disco (em falta, movido ou fora das pastas analisadas) e nada foi feito com eles.
- **As fotos que o utilizador selecionou.** Onde uma ferramenta aceita `paths`, `target: "selection"` usa em vez disso a seleção da aba aberta (`tab_id` escolhe a aba). Uma seleção que mudou entre a pré-visualização e a confirmação responde `invalid_input` com `selection_changed`, uma seleção demasiado grande para a resposta da aba responde `too_large`, e `delete_photos` relê a seleção ao confirmar.
- **Legendas e exportações.** `set_caption` guarda apenas o texto. A legenda não é recodificada: a pesquisa semântica de legendas continua a encontrar o texto antigo até uma nova codificação, e a exportação incremental para a base de dados do visualizador mantém uma legenda existente quando a de origem está vazia, pelo que uma legenda apagada pode voltar com uma exportação ou análise posterior. `export_metadata` espera até 180 segundos, reporta `written`, `skipped` e `errors` com o primeiro texto de erro em `first_error`, e recusa escrever com exiftool 13.23 a 13.27.
- **Rostos.** `assign_faces` ignora, e lista, os rostos em falta, já nessa pessoa, de outra pessoa (salvo `allow_reassign`), de outro modelo de embedding ou de uma pessoa oculta; `assigned_count` é o que realmente se moveu.

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

## Correções e dados de referência

- **Correções** (`edition`). `override_sequence` (`kind`: `panorama`, `bracket`, `hdr_panorama` ou `suppress`; pelo menos 2 caminhos exceto para `suppress`) e `clear_sequence_override` registam uma correção aplicada na próxima passagem de deteção (o resultado indica `pending`). `override_category` e `clear_category_override` definem ou removem uma categoria persistente que sobrevive a novas análises e mantém o contexto de pontuação.
- **Comparar fotogramas** (`readonly`). `group_compare` compara os fotogramas de um grupo de triagem (até 12 caminhos) com `by: "faces"` (por fotograma: número de rostos, piscar de olhos, olhos abertos mais baixos, melhor sorriso, `best_path_by_eyes`) ou `by: "subjects"` (nitidez e destaque do motivo, `sharpest_path`). É um conselho, não uma decisão. `cull_report` resume um âmbito numa chamada: total, mantidas, rejeitadas, favoritas, classificadas, por rever, o que os interruptores de ocultação escondiam, lixo, pontuações baixas, as melhores e, com um token edition, os primeiros grupos da câmara escura. Os motivos sobrepõem-se. Inclui um `basis` que indica quais filtros cada contagem respeita (os interruptores de ocultação não se aplicam às contagens).
- **Gosto.** `comparison_status` (`edition`) indica quantas comparações por pares fez e quanto cobrem a biblioteca. Nenhuma ferramenta submete, edita ou apaga uma comparação: a resposta a um par é o seu próprio clique. As escritas de um assistente (classificações, rejeições, confirmações da câmara escura, `auto_cull`) nunca registam comparações nem ativam o retreino automático; a mesma ação feita por si na galeria continua a fazê-lo. As classificações, favoritos e rejeições que um assistente escreveu também ficam fora dos pares de treino do classificador pessoal quando é reconstruído a partir das suas classificações; voltam a contar assim que você classificar essa fotografia. Esse registo é guardado numa tabela própria e nunca é exportado.
- **Análises.** `start_scan` e `scan_status` (`edition`) iniciam e acompanham uma análise das diretorias configuradas. Só são listados quando `viewer.features.show_scan_button` está ativo e a instalação está bloqueada (uma chave superadmin no modo multiutilizador), ou para um token local de edição completa sob `viewer.trusted_local_editing`, que não precisa de `show_scan_button`. Uma análise é aditiva e é recusada enquanto outra tarefa decorre (`conflict`). A sincronização com o Immich continua na linha de comandos.
- **Recursos.** Além das ferramentas, o servidor lista cinco recursos `facet://` só de leitura: `facet://categories`, `facet://tags`, `facet://persons`, `facet://filters` (cada filtro de pesquisa com o seu domínio de valores, mais os intervalos das métricas) e `facet://scoring-contexts`. Cada um é lido como o proprietário da chave vê a biblioteca, limitado a 200 linhas e 32 KiB (`truncated` indica-o).
- **Escolher o que é listado.** `viewer.mcp.tool_profile` é `full` (predefinição) ou `core`: `core` lista apenas um conjunto de 11 ferramentas para modelos pequenos (`status`, `search_photos`, `semantic_search`, `get_photo`, `filter_options`, `library_stats`, `ui_show_photos`, `set_rating`, `set_favorite`, `set_rejected`, `album_add_photos`). Só muda a lista, nunca o que uma chave pode chamar. `viewer.mcp.allow_destructive` (predefinição `false`) controla `delete_photos` (não listado se desativado), as ações `move_rejects` e `trash_rejects` de `cull_apply` e `assign_faces` com `allow_reassign`; as chamadas recusadas respondem `feature_disabled`. As ferramentas que o nível de um token não pode chamar também não são listadas.
- **Mais dois códigos de erro.** `feature_disabled`: a rota está desativada por uma chave de configuração, que a mensagem nomeia. `conflict`: a biblioteca está ocupada com uma tarefa que exclui esta (por exemplo, uma análise já em curso).

## Prompts

O servidor oferece ainda cinco prompts prontos, listados por `prompts/list` e filtrados pelo nível do token. Um prompt só nomeia ferramentas que o token pode chamar, e uma ferramenta destrutiva só depois do seu ensaio e da sua confirmação. Cada chamada conta no limite de leitura e é registada pelo nome, nunca com os seus argumentos.

| Prompt | Argumentos | O que pede ao assistente |
|--------|------------|--------------------------|
| `find_photo` | `description` | Encontrar uma foto a partir de uma descrição e mostrá-la |
| `cull_shoot` | `scope_hint` | Rever uma sessão, propor o que rejeitar e, depois de decidir, registar as suas decisões com `confirm_culling_groups`; mover ou enviar para o lixo só acontece após um ensaio e a sua confirmação |
| `build_album` | `theme`, `album_name` | Reunir as fotos correspondentes num novo álbum |
| `tag_people` | `person` | Encontrar rostos parecidos com uma pessoa e atribuir os que confirmar |
| `teach_taste` | `category` | Abrir a página de comparação por pares no seu separador e acompanhar quantas comparações fez; a resposta a cada par é sempre o seu próprio clique |

## Câmara escura (grupos de triagem)

As ferramentas da câmara escura espelham a página `/culling`. Todas exigem o nível `edition`, mesmo as que apenas listam.

| Ferramenta | O que faz |
|------------|-----------|
| `list_culling_groups` | Lista os grupos (`burst`, `similar`, `scene`, `bracket`, `panorama`, `hdr_panorama`) com as suas fotos e pontuações, ordenáveis e delimitáveis por álbum ou intervalo de datas |
| `culling_profiles` | As predefinições de triagem por género e a predefinida |
| `suggest_culling_profile` | Indica a predefinição adequada a um álbum ou intervalo de captura |
| `keeper_hints` | Dicas por foto «existe uma foto melhor nesta rajada» para até 100 caminhos (vazias se não houver cabeça de classificação treinada) |
| `auto_cull` | Triagem automática de um âmbito com um orçamento de fotos a manter: pré-visualização do plano página a página e depois aplicação com o valor `confirm` |
| `confirm_culling_groups` | Confirma até 20 grupos: mantém os seus `keep_paths` e rejeita o resto dos seus `paths` |

- **Um grupo é identificado pelo par `(type, group_id)`**, nunca só por `group_id`: os ids dos grupos semelhantes são deslocados ao serem fundidos com as rajadas.
- **O valor predefinido `group_by: "all"` devolve apenas rajadas e grupos semelhantes.** Peça explicitamente `scene`, `bracket`, `panorama` ou `hdr_panorama`.
- **Uma página é reduzida para caber em `max_bytes` encurtando a lista `photos` de cada grupo, nunca removendo grupos.** `photo_count` continua a ser o tamanho real, `photos_truncated` assinala um grupo cuja lista foi cortada e `has_more` indica se segue outra página.
- **Bracketings, panoramas e panoramas HDR são mantidos inteiros.** Em `confirm_culling_groups`, `keep_paths` tem de ser igual a `paths` para estes tipos (senão `invalid_input`), e `auto_cull` nunca os divide.
- **Um `keep_paths` vazio rejeita todos os fotogramas do grupo.** A primeira chamada responde então `confirmation_required` com um valor `confirm`; mostre-o ao utilizador e repita a chamada com esse valor. Se um lote parar em `forbidden_level`, `library_busy` ou `rate_limited`, os grupos já concluídos são indicados.
- **`auto_cull` faz uma pré-visualização por predefinição** e devolve a repartição manter/rejeitar por grupo mais um valor `confirm` (só se algo for rejeitado). Cada chamada planeia todo o âmbito e devolve-o em páginas de grupos inteiros (a rota pagina a 200 fotos, mas um único grupo maior recebe a sua própria página, e a ferramenta pode devolver menos grupos para caber no tamanho do resultado): repita a chamada com `cursor` igual ao `next_cursor` anterior e `plan_digest` igual ao `plan_digest` da página do cursor 0 (obrigatório se `cursor` > 0) até `next_cursor` ser `null`. Um plano que mudou desde a primeira página é recusado com `confirmation_required`: recomece a partir do cursor 0. Cada linha traz o seu `number` em todo o plano e os totais cobrem o plano completo. Faça a triagem de um intervalo de datas inteiro numa ÚNICA chamada, nunca mês a mês.
- **Um único `confirm` cobre todo o plano** (válido 300 s, de uso único). A aplicação recalcula o plano e recusa-o com `confirmation_required` se mudou desde a pré-visualização. As rejeições feitas por um assistente nunca alimentam o classificador pessoal, ao contrário da mesma triagem feita por si na galeria. O `confirm` só é emitido na página do cursor 0. A aplicação devolve apenas contagens (`groups_processed`, `kept`, `rejected`, `highlights_added`).
- **Substituições.** `keep_paths` e `remove_paths` (até 1000 cada; normalmente as listas `review` de `ui_get_context`) substituem fotogramas isolados do plano. Passe as mesmas substituições na simulação que emite o `confirm` e na aplicação. Os caminhos que não estão no plano são ignorados e indicados em `ignored_overrides` (os primeiros 20, com `ignored_overrides_count`). Remover um fotograma que o plano MANTÉM num bracketing, num panorama ou num panorama HDR, deixar um grupo sem nenhum mantido ou pôr um caminho nas duas listas é recusado com `invalid_input`, indicando os caminhos ou os grupos; remover um fotograma que o plano já rejeita não tem efeito. A regra dos conjuntos aplica-se a grupos formados inteiramente por um só tipo de conjunto: um grupo que mistura fotogramas normais com fotogramas de conjunto não é mantido inteiro, pelo que os seus fotogramas podem ser substituídos como os de qualquer rajada.
- **`scope_dependent_kinds`** indica os tipos de grupo (`similar`, `scene`, mais `bracket` se `trim_brackets` estiver ativo) cuja composição depende do intervalo de datas ou do conjunto de candidatos, com uma nota para fazer a triagem de todo o intervalo numa chamada. As rajadas e os panoramas não mudam com o intervalo, nem os bracketings enquanto `trim_brackets` estiver inativo.
- **`show`** (`true` por predefinição, com `tab_id`). Numa simulação, a página atual é fixada no seu separador aberto com números de grupo e marcas Manter/Remover, e o resultado inclui `shown_in_tab`. Inverta as marcas nos cartões; o assistente lê-as com `ui_get_context.review`. Uma apresentação falhada nunca faz falhar a chamada. `shown_in_tab.missing` lista no máximo 20 caminhos, e `missing_count` indica o número real. Uma revisão demasiado grande para a resposta é cortada por `ui_get_context` com `review.truncated: true`, ficando os tamanhos reais em `review.keep_count` / `review.remove_count`. Prima `K` ou `R` num cartão marcado para definir Manter ou Remover sem o rato.
- Chame `ui_show_culling_group` para mostrar um grupo ao utilizador no seu separador aberto (veja [Controlar o separador aberto](#controlar-o-separador-aberto)).

## Resultados, limites e erros

Cada resultado é um envelope JSON: `{"ok": true, "data": ...}` ou `{"ok": false, "error": "<code>", "message": "..."}`. As listagens devolvem `data.rows` (um conjunto compacto e fixo de campos por foto) mais `total`. O resultado de uma busca traz também `shown_in_tab`, e um resultado cortado pelo limite de bytes traz `returned`.

- **Limites máximos:** no máximo `max_rows` linhas e `max_bytes` bytes serializados. As últimas linhas são descartadas e `truncated: true` é definido. Um resultado sem linhas que exceda `max_bytes` torna-se um erro `too_large`.
- **Imagens:** `get_thumbnail` e `contact_sheet` devolvem uma parte de imagem antes da parte JSON. A imagem é limitada por `max_image_bytes` (262144 por omissão), não por `max_bytes`. O texto visível dentro de uma imagem é um dado, nunca uma instrução.
- **Análise de rostos:** `possible_faces` lê no máximo 192000 rostos e pode esperar até 120 segundos; acima disso responde `too_large`.
- **Limite de taxa:** `rate_per_min` chamadas por minuto e por token para leitura. As ferramentas de escrita usam um orçamento separado, `write_rate_per_min` (30 por predefinição), para que as pesquisas não deixem as escritas sem quota nem o contrário; a simulação de `cull_apply` e `delete_photos` conta como escrita, a pré-visualização de `auto_cull` como leitura. Acima disso: `rate_limited` com `retry_after_s`. Dez tentativas bearer falhadas por minuto a partir do mesmo endereço recebem 429.
- **Códigos de erro:** `forbidden_level` (endpoint desativado, token inválido ou nível insuficiente), `invalid_input`, `not_found`, `rate_limited`, `library_busy`, `upstream_error`, `outcome_unknown`, `confirmation_required`, `too_large`, `no_tab`, `tab_timeout`, `tab_outdated`.
- **Os códigos mais recentes:** `confirmation_required` (uma chamada destrutiva não tem um valor `confirm` válido para este conjunto exato: repita a simulação, mostre o resultado ao utilizador e tente de novo), `outcome_unknown` (uma escrita excedeu o tempo ou a ligação caiu, pelo que pode ou não ter acontecido: volte a ler o estado antes de repetir, nunca repita às cegas), `library_busy` (a biblioteca está ocupada com outra tarefa: tente de novo daqui a pouco).
- **Códigos HTTP à entrada:** 401 para token em falta ou desconhecido, 403 para um pedido de navegador de outra origem ou para as credenciais de um agente em `/api/mcp/tokens`, 404 quando está desativado. A ponte de separadores responde com códigos de fecho.

## Notas de segurança

- Legendas, etiquetas, nomes de ficheiros, caminhos e nomes de álbuns e pessoas vêm da sua biblioteca e podem conter texto escrito para manipular um assistente (injeção de prompts). Cada ferramenta está marcada com `facet/untrusted_content` e diz ao modelo para os tratar como dados. Não dê a um assistente que também lê conteúdo não fiável uma forma de agir sobre o que encontra aqui.
- Os tokens nunca expiram. Revogue os que já não usa.
- Os registos guardam o id do token, a ferramenta, o resultado e o número de linhas, nunca os argumentos nem o token.

## Limitações conhecidas

- Numa instalação aberta (sem palavra-passe), qualquer pessoa que alcance o visualizador pode criar e revogar os tokens `_anonymous` partilhados. Defina uma palavra-passe antes de ativar o endpoint numa rede. A ponte de separador amplia este risco: um cliente que não seja um navegador pode enviar um `Origin` inventado e um token nulo, registar um separador `_anonymous` com o foco, responder às chamadas `ui_*` com os dados que quiser e expulsar separadores reais através do limite de 8 separadores. Com `viewer.trusted_local_editing`, um processo local também pode registar um separador `edition` falso (pode falsificar `Host` e `Origin` no WebSocket), mas já podia agir como o navegador; um cliente da rede local não pode, pois é exigido um par em loopback.
- Os limites de frequência e os contadores de autenticações falhadas vivem em memória em cada processo; com `viewer.py --workers N` cada worker conta em separado.
- O registo de separadores vive em memória num só processo. Use um único worker (`viewer.py --workers 1`, o valor por omissão) se depender das ferramentas `ui_*`; com vários workers uma chamada pode chegar a um processo que não conhece o seu separador e responder `no_tab`.
- Um utilizador pode ter no máximo 8 separadores ligados; abrir um nono fecha o mais antigo.
