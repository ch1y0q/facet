# Religar uma foto ausente após uma movimentação explícita

`python database.py --relink-photos` atualiza os caminhos no banco de dados do Facet depois que você mesmo moveu os arquivos. Ele nunca move, copia, exclui nem edita originais ou arquivos sidecar, e nunca contata o Immich. É um comando de manutenção offline.

Antes de aplicar um plano:

- Pare o viewer, as varreduras e os editores de arquivos externos.
- Faça backup do banco de dados.
- Revise o plano.

Aplicar adquire o bloqueio da biblioteca do Facet. Se outro trabalho da biblioteca estiver em execução, o comando sai com o código 75 e não altera nada; um bloqueio inutilizável sai com o código 1. A prévia é somente leitura e não adquire bloqueio. O bloqueio cobre apenas trabalhos em um único host.

> **Aviso:** o Facet não armazena nenhum hash dos bytes do arquivo original, então não consegue provar que o novo arquivo é o que foi movido. Todo plano informa `original_bytes_unknown`; `phash` e as assinaturas de rostos manuais não provam identidade. O SHA-256 do destino identifica apenas o arquivo que você pré-visualizou. Aplicar afirma que você mesmo verificou a correspondência. Uma afirmação errada associa anotações existentes à imagem errada.

Mover ou renomear um diretório inteiro não é suportado quando o diretório pai antigo não existe mais. Não recrie diretórios pai vazios para contornar essa verificação.

## Pré-visualizar, revisar e depois aplicar

Crie uma lista JSON com caminhos absolutos canônicos exatos. Cada origem já deve estar no Facet. Cada destino deve existir como imagem e ainda não pode ter uma linha de foto:

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

# Inspecione em relink-plan.json cada caminho antigo/novo, o rótulo de identidade de bytes desconhecidos, o hash do destino e
# as dimensões, as referências, os acompanhantes e a política de visibilidade.
# Substitua REVIEWED_PLAN_ID pelo plan_id exato desse artefato depois de revisá-lo.
python database.py --relink-photos --db library.db --config scoring_config.json \
  --apply-plan relink-plan.json --ack-plan REVIEWED_PLAN_ID \
  --acknowledge-unverified-identity
```

No modo multiusuário, adicione `--user alice` aos dois comandos. Ele seleciona o escopo de quem será verificado; não é controle de acesso. Regras:

- Os dois caminhos devem ser visíveis para esse usuário.
- O conjunto de **todos** os usuários que podem ver a foto deve permanecer idêntico. Movimentações de privado para compartilhado e outras movimentações entre usuários são recusadas.
- Os dois caminhos devem estar dentro de diretórios de varredura, de usuário ou compartilhados explicitamente configurados.
- Configuração de raízes em branco, raízes inacessíveis e `viewer.path_mapping` são recusados. Só há suporte para caminhos nativos canônicos.

A aplicação reverifica todo o plano em uma única transação do banco de dados. Se arquivos de destino, linhas de fotos, anotações, esquema, o arquivo do banco de dados ou a visibilidade tiverem mudado, execute uma nova prévia. Um lote com falha desfaz todas as suas gravações no banco de dados. Uma aplicação bem-sucedida imprime um recibo com o ID do plano.

## O que acompanha a foto

Estes mantêm sua associação com a foto:

- IDs das fotos, avaliações, Keep e GPS
- tags, rostos, IDs de pessoas e UUIDs manuais de rostos
- comparações, pontuações aprendidas e preferências por usuário
- substituições, participação fixa em álbuns, capas e escolhas de clientes
- instantâneos de extração e vetores de embeddings
- valores de grupos de rajada, duplicata e sequência

As estatísticas derivadas são invalidadas; o estado de treinamento permanece.

O que não muda:

- **O histórico de desfazer** mantém seus caminhos antigos. Uma entrada do caminho antigo pode deixar de aparecer ou de poder ser revertida após a religação.
- **Os retângulos manuais de rostos** são mantidos, mas marcados como `relink_unverified`. Abra o editor e salve cada retângulo em relação ao novo quadro antes que ele possa ser exportado ou suprimir detecções.
- **O Immich**: o estado de envio e pendente permanece como estava; nenhuma avaliação, álbum ou UUID remoto é religado. Verifique o mapeamento remoto por conta própria antes de sincronizar.
- **O histórico de falhas de varredura, os filtros de álbuns inteligentes e as chaves de grupos de sequência** não são reescritos.

## Arquivos acompanhantes explícitos e recusas

Liste os acompanhantes você mesmo; a ferramenta não consegue encontrar arquivos RAW ou XMP que sumiram do diretório antigo. Tipos de acompanhante:

| Tipo | Arquivo |
|---|---|
| `sidecar_full` | `photo.ext.xmp` |
| `sidecar_basename` | `photo.xmp` |
| `sidecar_facet` | `photo.ext.facet.xmp` |
| `raw` | par RAW no mesmo diretório e com o mesmo nome base |

Essas regras validam a relação declarada; não provam identidade. Uma foto RAW indexada precisa de sua própria entrada de nível superior para que suas anotações sejam preservadas. Os arquivos acompanhantes existentes passam por hash e permanecem intocados. Uma lista de acompanhantes vazia não prova que não existia nenhum.

O Facet recusa:

- sidecars ou acompanhantes RAW não listados no destino, incluindo pacotes alternativos do Facet e variações de maiúsculas/minúsculas
- vários candidatos RAW ou propriedade XMP ambígua, p. ex. `IMG.CR2` + `IMG.CR2.jpg` + `IMG.CR2.xmp`, ou `IMG.CR2` + `IMG.CR2.facet.jpg` + `IMG.CR2.facet.xmp`, além de colisões de nome base, de maiúsculas/minúsculas ou de Unicode
- cópias em que o original antigo ainda está presente
- diretórios pai antigos ausentes ou ilegíveis
- destinos que já têm linhas de foto ou dependentes
- mapeamentos repetidos, conteúdos de fotos ou inodes de destino duplicados
- renomeações apenas de maiúsculas/minúsculas ou de Unicode, links simbólicos e mudanças de extensão ou formato
- um destino decodificado cujas dimensões difiram das armazenadas, quando estas são conhecidas

Nenhuma busca por similaridade ou nome de arquivo é executada.

Limites por lote: 100 fotos, 300 arquivos nomeados, 512 MiB por arquivo, 2 GiB no total e 2 MiB para o JSON de entrada ou o plano. Divida o lote se atingir um deles. A gravação no banco de dados é atômica, mas outros aplicativos ainda podem mexer nos arquivos, e é por isso que o trabalho deve ser executado offline.

> **Aviso:** um diretório legível não prova que o armazenamento está montado. Um volume desmontado pode parecer uma pasta vazia. O plano informa `source_mount_status: not_verified`; confirme que cada origem foi realmente movida antes de reconhecer a identidade. O comando não detecta todas as condições de volume offline.

Os arquivos de plano contêm caminhos completos privados e o escopo de usuário. `--plan-out` os cria de forma exclusiva com modo 0600 em POSIX.

| Opção | Função |
|---|---|
| `--db` | Banco de dados existente |
| `--config` | Configuração resolvida |
| `--user` | Usuário configurado obrigatório no modo multiusuário |
| `--mapping` | Mapeamentos antigo/novo explícitos em JSON; modo de prévia |
| `--plan-out` | Criar um novo arquivo de plano privado; nunca sobrescreve |
| `--apply-plan` | Aplicar um plano revisado anteriormente |
| `--ack-plan` | Hash exato do plano revisado |
| `--acknowledge-unverified-identity` | Confirmação explícita apesar dos bytes originais desconhecidos |
