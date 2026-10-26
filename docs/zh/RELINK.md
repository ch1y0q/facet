# 重新关联已移动照片

`python database.py --relink-photos` 仅在手动移动文件后修改已索引照片的数据库路径。先停止查看器、扫描器和外部编辑器并备份数据库。它不会移动、修改或删除原图与伴随文件，也不联系 Immich。

应用操作在整个数据库写入期间持有 Facet 的照片库维护锁。如果其他照片库任务正在运行，则以退出码 75 结束，不更改数据库或媒体文件；锁无法使用时退出码为 1。预览仍然只读，不获取照片库锁。此锁只协调同一主机上的任务；其他主机和外部编辑器仍须遵守离线操作要求。

数据库不能证明缺失原图的字节身份；每个计划均标注 `original_bytes_unknown`。SHA-256 仅标识已预览的新目标。进行两项确认前必须独立核对身份；错误匹配可能把注释关联到错误照片。

路径必须为配置根目录内的绝对、本机、规范路径，不能含符号链接。旧原图必须缺失，但其父目录须存在且可读。整个目录消失时拒绝操作，因为存储可能离线；不要新建空旧目录绕过检查。可读目录并不证明卷已挂载；`source_mount_status=not_verified` 需要独立确认。

预览不写数据库。检查保存的计划后再应用；应用在单个 SQLite 事务内重新核对文件、哈希、已知尺寸、注释、模式、数据库 inode 和权限。任何冲突均回滚整个批次，但不会锁定其他应用。计划以独占方式创建，POSIX 权限为0600，包含私密路径。

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

| 选项 | 用途 |
|---|---|
| `--db` | 现有数据库 |
| `--config` | 解析后的配置 |
| `--user` | 多用户模式下必须指定已配置用户 |
| `--mapping` | 显式旧/新路径 JSON；预览模式 |
| `--plan-out` | 创建新的私密计划文件，不覆盖已有文件 |
| `--apply-plan` | 应用已审核的计划 |
| `--ack-plan` | 已审核计划的准确摘要 |
| `--acknowledge-unverified-identity` | 明确确认原图字节身份未知的操作 |

行 ID、评分/Keep/GPS、标签、人脸/人物、手动 UUID、比较、偏好、固定相册和向量保留关联。所有手动矩形均须在编辑器中明确复核并保存。历史记录保留旧路径，可能不再可撤销；私有修订缓存失效。不会改写智能相册筛选、逻辑组键、历史日志或 Immich 状态。

伴随文件必须声明旧/新路径及 `kind`：`sidecar_full` 为 `photo.ext.xmp`，`sidecar_basename` 为 `photo.xmp`，`sidecar_facet` 为 `photo.ext.facet.xmp`，`raw` 为同名未索引 RAW。已索引 RAW 必须使用独立顶层条目，并与已索引 JPEG 在同一计划中关联。伴随文件字节保持不变；无法发现未知且已消失的伴随文件。

多用户模式须使用 `--user`，且移动前后所有用户的可见性一致。空或不可访问根目录、path_mapping、仍存在的原图、已注册目标、重复文件/inode、大小写/Unicode/双扩展名冲突、多个 RAW、未声明伴随文件及格式改变均被拒绝。上限：100张照片、300个文件、每文件512MiB、总计2GiB、JSON2MiB。必要时缩小批次。
