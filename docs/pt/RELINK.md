# Religar fotos movidas

`python database.py --relink-photos` altera apenas os caminhos de fotos já indexadas após movê-las manualmente. Pare visualizador, scanners e editores externos; faça backup do banco. Não move, modifica ou exclui originais ou acompanhantes e não contata Immich.

O banco não prova a identidade dos bytes do original ausente: cada plano indica `original_bytes_unknown`. SHA-256 identifica apenas o novo destino revisado. Verifique a identidade independentemente antes das duas confirmações; uma associação errada pode anexar anotações à imagem errada.

Caminhos devem ser absolutos, nativos e canônicos, sem links simbólicos, dentro das raízes configuradas. O original deve faltar, mas a pasta pai precisa existir e ser legível. Pastas inteiras ausentes são recusadas porque podem estar offline. Não recrie pastas vazias para contornar isso. Uma pasta legível não prova montagem; `source_mount_status=not_verified` exige verificação independente.

A prévia não escreve no banco. Revise o plano salvo; aplicar verifica novamente arquivos, hashes, dimensões conhecidas, anotações, esquema, inode e acesso em uma transação SQLite. Qualquer conflito reverte todo o lote. Outros programas não são bloqueados. O plano é criado exclusivamente com POSIX0600 e contém caminhos privados.

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
python database.py --relink-photos --db library.db --config scoring_config.json \
  --mapping moved.json --plan-out relink-plan.json
python database.py --relink-photos --db library.db --config scoring_config.json \
  --apply-plan relink-plan.json --ack-plan REVIEWED_PLAN_ID \
  --acknowledge-unverified-identity
```

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

IDs, notas/Keep/GPS, tags, rostos/pessoas, UUIDs manuais, comparações, preferências, álbuns fixos e vetores preservam seus vínculos. Todos os retângulos manuais exigem revisão e salvamento explícitos. O histórico mantém caminhos antigos e pode não permitir reversão; revisões privadas são invalidadas. Filtros inteligentes, chaves lógicas de grupos, registros históricos e estado Immich não são reescritos.

Declare acompanhantes com caminhos antigo/novo e `kind`: `sidecar_full` para `photo.ext.xmp`, `sidecar_basename` para `photo.xmp`, `sidecar_facet` para `photo.ext.facet.xmp`, `raw` para RAW não indexado da mesma base. RAW indexado requer entrada principal própria; RAW/JPEG indexados são religados no mesmo plano. Os bytes não mudam; acompanhantes desaparecidos desconhecidos não podem ser descobertos.

Multiusuário exige `--user` e visibilidade idêntica para todos antes/depois. Recusa raízes vazias/inacessíveis, path_mapping, originais presentes, destinos registrados, arquivos/inodes duplicados, ambiguidades de caixa/Unicode/extensão dupla, vários RAW, acompanhantes não declarados e mudanças de formato. Limites:100 fotos,300 arquivos,512MiB por arquivo,2GiB no total,2MiB JSON. Reduza o lote quando necessário.
