# Religar uma foto ausente após uma movimentação explícita

`python database.py --relink-photos` atualiza os caminhos já existentes no banco de dados do Facet depois que você mesmo moveu os arquivos. Ele nunca move, copia, exclui nem edita originais ou arquivos sidecar, e nunca contata o Immich. É um comando de manutenção offline para o operador com acesso ao banco de dados e às pastas configuradas. Pare antes o viewer, as varreduras e os editores de arquivos externos; faça backup do banco de dados e revise o plano antes de aplicá-lo.

A aplicação mantém o bloqueio de manutenção da biblioteca do Facet durante toda a gravação no banco de dados. Outro trabalho da biblioteca gera o código de saída 75, sem alterar o banco de dados nem a mídia; um bloqueio inutilizável gera o código 1. A prévia continua somente leitura e não adquire nenhum bloqueio da biblioteca. Esse bloqueio coordena trabalhos em um único host; os requisitos offline continuam valendo para outros hosts e editores externos.

O banco de dados existente não tem nenhum hash criptográfico dos bytes do arquivo original. `phash` e as assinaturas em escala de cinza de rostos manuais não provam identidade byte a byte. Por isso, todo plano informa `original_bytes_unknown`. O SHA-256 do destino identifica apenas o novo arquivo que foi pré-visualizado. Aplicar afirma explicitamente que você identificou, por conta própria, o arquivo movido correto; nunca é uma correspondência verificada automaticamente. Uma afirmação errada pode associar anotações existentes à imagem errada.

Mover ou renomear um diretório inteiro está fora deste modo limitado quando o diretório pai antigo não existe mais. Diretórios ausentes não permitem distinguir uma movimentação intencional de um armazenamento offline. Não recrie diretórios pai vazios para contornar essa verificação.

## Pré-visualizar, revisar e depois aplicar

Crie uma lista JSON com caminhos absolutos canônicos exatos. Uma origem ausente já deve estar registrada no Facet; um destino deve existir como imagem e ainda não pode ter uma linha de foto:

```json
[
  {
    "old": "/photos/before/portrait.jpg",
    "new": "/photos/after/portrait-renamed.jpg",
    "companions": [
      {
        "old": "/photos/before/portrait.jpg.xmp",
        "new": "/photos/after/portrait-renamed.jpg.xmp",
        "kind": "sidecar_full"
      }
    ]
  }
]
```

```sh
# Prévia somente leitura do banco de dados; cria um artefato de revisão privado (0600) e exclusivo.
python database.py --relink-photos --db library.db --config scoring_config.json \
  --mapping moved.json --plan-out relink-plan.json

# Inspecione em relink-plan.json cada caminho antigo/novo, o rótulo de identidade de bytes desconhecidos, o hash do destino, as
# dimensões, as referências, os arquivos acompanhantes e a política de visibilidade.
# Substitua REVIEWED_PLAN_ID pelo plan_id exato desse artefato depois de revisá-lo.
python database.py --relink-photos --db library.db --config scoring_config.json \
  --apply-plan relink-plan.json --ack-plan REVIEWED_PLAN_ID \
  --acknowledge-unverified-identity
```

O modo multiusuário também exige `--user alice` nos dois comandos. Esse é um seletor de escopo para o operador, não um substituto do controle de acesso do sistema operacional nem uma API autenticada. Os dois caminhos devem ser visíveis para esse usuário, e o conjunto de **todos** os usuários que podem ver a foto deve permanecer idêntico. Movimentações de privado para compartilhado ou outras movimentações entre usuários são recusadas. Os dois caminhos devem estar dentro de diretórios de varredura, de usuário ou compartilhados explicitamente configurados. Configuração de raízes em branco, raízes inacessíveis e `viewer.path_mapping` são recusados; esta ferramenta inicial só aceita caminhos nativos canônicos.

A aplicação reverifica todo o plano revisado dentro de uma única transação de gravação do SQLite. Arquivos de destino, linhas de fotos, anotações, esquema, inode do banco de dados ou política de visibilidade alterados exigem uma nova prévia. Um lote com falha desfaz todas as suas gravações no banco de dados. Uma aplicação bem-sucedida imprime um recibo com o ID do plano. Ela não armazena um novo ID de ativo lógico nem um mapeamento de UUID remoto.

## O que acompanha a foto

Rowids das fotos, avaliações/Keep/GPS, tags, IDs de rostos/pessoas e UUIDs manuais, comparações, pontuações aprendidas, preferências por usuário, substituições, participação fixa em álbuns/capas/escolhas de clientes, instantâneos de extração e vetores de embeddings mantêm suas associações. As chaves estrangeiras existentes para photos são descobertas a partir do esquema real; uma nova coluna de caminho não registrada é recusada em vez de ficar órfã em silêncio. As estatísticas derivadas são invalidadas; o estado de treinamento duradouro permanece.

As entradas do histórico de organização mantêm seus conteúdos de caminhos históricos originais. Os gatilhos existentes de mudança de caminho avançam o relógio de revisões e invalidam os caches de revisão privados; uma entrada que se refira ao caminho antigo pode deixar de aparecer ou de poder ser revertida após a religação. A religação preserva os valores de anotação e as associações atuais, mas não reescreve ações passadas para torná-las aplicáveis a um caminho diferente.

Todos os retângulos manuais são mantidos, mas exigem revisão no novo caminho. A assinatura antiga e aproximada não pode provar os pixels do original ausente. Um marcador `relink_unverified` impede que as verificações de assinatura comuns apaguem esse estado de revisão; abra o editor e salve explicitamente cada retângulo em relação ao novo quadro antes que ele possa ser exportado ou suprimir detecções. Os IDs de retângulos e de pessoas existentes são preservados.

O estado de envio/pendente do Immich permanece inalterado: uma afirmação local sobre o nome de um arquivo não pode verificar uma identidade remota. Nenhuma avaliação remota, limpeza, participação em álbum ou UUID é religada. Revise separadamente o mapeamento remoto antes de sincronizar. Os caminhos históricos de falhas de varredura continuam históricos; os predicados de filtros de álbuns inteligentes e as chaves de grupos lógicos de sequências não são reescritos em silêncio. As participações estáticas e os valores de grupos de sequência/rajada/duplicata permanecem intactos.

## Arquivos acompanhantes explícitos e recusas

Liste os arquivos acompanhantes explicitamente; a ferramenta não consegue descobrir arquivos RAW/XMP não indexados que sumiram do diretório antigo. `sidecar_full` significa `photo.ext.xmp`, `sidecar_basename` significa `photo.xmp`, `sidecar_facet` significa `photo.ext.facet.xmp` e `raw` mantém um par RAW informado explicitamente, no mesmo diretório e com o mesmo nome base, compatível com a seleção atual. Essas regras de nomes validam uma relação declarada; não provam a identidade dos arquivos. Fotos RAW indexadas precisam de sua própria entrada de religação de nível superior para que suas anotações sejam preservadas.

Sidecars ou acompanhantes RAW não listados no destino são recusados, incluindo pacotes alternativos do Facet e variações de maiúsculas/minúsculas. Vários candidatos RAW e propriedade XMP ambígua são recusados, incluindo `IMG.CR2` + `IMG.CR2.jpg` + `IMG.CR2.xmp`, `IMG.CR2` + `IMG.CR2.facet.jpg` + `IMG.CR2.facet.xmp`, além de colisões de nome base e de maiúsculas/minúsculas ou Unicode. Nenhum acompanhante é atribuído pela primeira correspondência. Os bytes dos acompanhantes existentes passam por hash, são reverificados e permanecem intocados. Acompanhantes ausentes e não listados continuam desconhecidos; não interprete uma lista vazia como prova de que não existiam.

São recusadas cópias cujo original antigo ainda está presente, diretórios pai antigos ausentes ou ilegíveis, fotos de destino ou linhas dependentes já existentes, mapeamentos repetidos, conteúdos de fotos ou inodes de destino duplicados, mudanças apenas de maiúsculas/minúsculas ou de Unicode, links simbólicos e mudanças de extensão ou formato. As dimensões canônicas armazenadas, quando conhecidas, devem coincidir com o destino decodificado. Nenhuma busca por similaridade ou nome de arquivo e nenhuma reconciliação automática é executada.

Limites: 100 fotos, 300 arquivos nomeados explicitamente, 512 MiB por arquivo, 2 GiB de bytes de arquivos no total e 2 MiB de JSON de entrada ou de plano revisado. Reduza o lote quando um limite for atingido. A transação do banco de dados é atômica; o sistema de arquivos não é bloqueado contra outros aplicativos, daí o requisito offline. Os testes com fixtures não afirmam nenhuma ida e volta com um aplicativo externo real ou um servidor remoto.

Diretórios legíveis **não** provam que o armazenamento está montado. Um volume desmontado pode deixar um ponto de montagem vazio, porém legível, indistinguível de um diretório realmente vazio após a movimentação. O plano informa explicitamente `source_mount_status: not_verified`; confirme de forma independente que cada origem foi movida e não apenas ficou indisponível antes de reconhecer a identidade. O comando não detecta todas as condições de volume offline. Os planos revisáveis contêm caminhos completos privados e a política de escopo de usuário; `--plan-out` os cria de forma exclusiva com modo 0600 em POSIX.

| Opção | Função |
|---|---|
| `--db` | Banco de dados existente |
| `--config` | Configuração resolvida |
| `--user` | Usuário configurado obrigatório no modo multiusuário |
| `--mapping` | Caminhos antigo/novo JSON; prévia |
| `--plan-out` | Criar novo plano privado sem sobrescrever |
| `--apply-plan` | Aplicar um plano revisado |
| `--ack-plan` | Hash exato do plano revisado |
| `--acknowledge-unverified-identity` | Confirmação explícita apesar dos bytes originais desconhecidos |
