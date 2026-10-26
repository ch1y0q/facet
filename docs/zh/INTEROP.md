# 后期软件互操作实用指南

> 🌐 [English](../INTEROP.md) · [Français](../fr/INTEROP.md) · [Deutsch](../de/INTEROP.md) · [Italiano](../it/INTEROP.md) · [Español](../es/INTEROP.md) · [Português](../pt/INTEROP.md) · **简体中文**

实用的分步指南，帮助你在 Facet 与摄影师真正在用的外部后期软件和数字资产管理（DAM）工具之间双向流转 Facet 的星级、颜色标签和标签。本页假设你已经知道 Facet *确实* 会写出 XMP —— `--export-sidecars` / `--import-sidecars` 选项的完整说明和字段对应关系（`xmp:Rating`、`xmp:Label`、`dc:subject`）请见[命令 — 预览与导出](COMMANDS.md#预览与导出)。

只有在查看器中明确导出元数据或运行 `--export-sidecars` 时，才会导出手动位置和审阅决定。GPS 使用标准 `exif:GPSLatitude` / `exif:GPSLongitude`；扫描得到的旧坐标不会覆盖文件中的 GPS。`--embed-originals` 还会将 EXIF GPS 写入支持的原始文件。更正后的拍摄日期会导出为 `exif:DateTimeOriginal`（使用 `--embed-originals` 时，还会作为 EXIF `DateTimeOriginal` 写入支持的原始文件）；点击**使用文件日期**后，下一次导出会将其从 sidecar 中移除，但不会触碰其他编辑器写入的日期。

命名空间 `https://github.com/ncoevoet/facet/ns/1.0/` 定义 `facet:ReviewDecision`（`kept`、`rejected`、`undecided`）和 `facet:GPSState`（`set`、`cleared`），以及 `facet:DateState`（`set`），用于标记 Facet 导出到 sidecar 的拍摄日期。保留独立于星级和收藏；淘汰会清除保留、星级和收藏。`--import-sidecars` 在标准审阅字段一致或缺失时应用私人决定。如果标准淘汰状态与私人字段不一致，说明外部编辑器更改了标准字段而保留了旧的私人标签：此时忽略私人决定，标准字段仍按现有的扫描时间规则判断是否导入。只包含决定的导入仍可明确应用，无需比较扫描时间。与标准审阅字段一同导出的决定采用同样的“较新者优先”检查，但尚无审阅状态（无星级、收藏、保留或拒绝）的照片除外：这样重新扫描的照片库仍能恢复其决定，而较旧的导出无法撤销此后做出的决定。已有手动 GPS 默认保留；使用 `--overwrite-manual-gps` 才会覆盖。明确清除的位置可以导入；缺失字段或无效坐标不会清除位置。`--user alice` 遵守该用户的可见目录和私人决定；GPS 仍为共享数据。未指定用户时使用全局状态。ExifTool 保留其他软件的元数据；没有 ExifTool 时，保留原有附属文件并写入 `.facet.xmp`。只有明确请求嵌入时才修改原始文件。

ExifTool 导出需要 Facet 随附的标签定义。如果这些定义不可用，导出会在修改照片或附属文件之前停止；请重新安装 Facet 以恢复它们。

## RAW 附属文件命名陷阱

Facet 在 `IMG_1234.CR2` 旁导出 `IMG_1234.CR2.xmp`，继续使用 darktable 的完整文件名约定。Lightroom Classic 和 Capture One 通常为专有 RAW 使用 `IMG_1234.xmp`。下面的导入策略不会改变导出文件名。JPEG/HEIC/TIFF/PNG/DNG 可通过 `--embed-originals` 使用文件内嵌通道；GIF/WebP/BMP/AVIF 和专有 RAW 仍需匹配的附属文件命名。

使用 `--import-sidecars --sidecar-naming full|basename|auto` 明确选择发现策略：

- `full`（默认）：读取 `<image.ext>.xmp` 或 `<image.ext>.facet.xmp` 中文件修改时间较新的一个；时间相同时优先使用前者。
- `basename`：只去掉图像最后一个扩展名，读取 `<image>.xmp`。忽略完整名称及其回退文件。
- `auto`：只存在一种命名系列时接受该系列。两种系列同时存在时跳过照片并报告歧义，不按修改时间解决冲突。请明确选择 `full` 或 `basename`。

若已索引照片或相邻图像文件共享基本名，例如 `same.CR3` 和 `same.jpg`，`basename` 与 `auto` 都会拒绝导入，即使所选目录或用户范围只包含其中一张。请为它们使用独立的完整名称附属文件。`same_v1.jpg` 的基本名不同。命名不匹配、歧义、不可读或无效的数据包都会报告；解析失败后不会尝试另一命名系列。CLI 汇总中的歧义计入跳过数量，命名不匹配计入没有所选附属文件的数量。

双扩展名派生文件（如 `IMG.CR2.jpg`）不得读取属于 `IMG.CR2` 的 `IMG.CR2.xmp`；保护也适用于其他图像的 `.facet.xmp` 回退文件。所有策略每次导入仅显示每类命名提示的一个示例；汇总仍计入所有受影响的照片。

导入不需要 ExifTool；导出合并、嵌入和 MWG 人脸矩形需要 ExifTool。没有它时，保留已有编辑器附属文件，XML 回退写入 `<image.ext>.facet.xmp`，不含 MWG 矩形。此文件需要明确交接给其他编辑器，不是各软件普遍自动发现的文件名。这些策略不会重命名文件。

## Lightroom Classic

### Facet → Lightroom

1. `python facet.py --export-sidecars`（加上路径可限定范围，例如 `--export-sidecars /photos/2026-wedding`）。加上 `--embed-originals` 还会直接写入 JPEG/HEIC/TIFF/PNG/DNG 文件。
2. 在 Lightroom Classic 的图库模块中选中照片（Ctrl/Cmd+A 全选），然后选择**元数据 → 从文件中读取元数据**。Lightroom 会用附属文件（或上述格式的内嵌元数据）中的内容覆盖其目录里的星级、颜色标签和关键字。

Facet 的淘汰标记（`xmp:Rating = -1`）会被读回为 Lightroom 的排除（Reject）旗标。Facet 的收藏会写出 `xmp:Label = Yellow`，Lightroom 把它显示为**黄色的颜色标签** —— 而不是留用（Pick）旗标。如果你的 Lightroom 工作流依据的是留用旗标而不是颜色标签，请加一个“颜色标签转留用旗标”的步骤，或者改为按黄色标签筛选。

现在还有 `python facet.py --export-manifest` 这条数据源（路径、类别、全部评分、标签，以及与 `--export-sidecars` 相同的星级列 —— 在多用户安装上还可通过 `--export-manifest --user alice` 导出按用户区分的星级），供那些希望拿到 Facet 数据又不想解析 XMP 的工具使用 —— 见[命令 — 预览与导出](COMMANDS.md#预览与导出)。下文的 Facet 增效工具消费的正是这份数据。

**清单版本 2。** 清单现在还携带 `burst_group_id`、`sequence_kind`、`sequence_group_id`、`score_stars`，以及一个顶层的 `pending_corrections` 计数（尚未被检测运行应用的曝光包围／全景手动修正——重新运行 `--detect-panoramas`）。下面的连拍留用／淘汰与星级兜底选项要用到逐照片字段，而 `pending_corrections` 会在增效工具的预览里显示为一行警告，让你知道再跑一次检测仍可能改变哪些帧是首选帧。这里没有向后兼容的读取路径：为版本 2 构建的增效工具会直接拒绝版本 1 的清单，弹出对话框要求你重新导出；旧版增效工具也无法读取版本 2 的清单。如果看到那个对话框，重新运行 `--export-manifest` 即可。

在网页版查看器中，图库的 **Export to editor**（导出到编辑器）对话框通过一个 **Download Lightroom manifest**（下载 Lightroom 清单）按钮提供同一份清单，其范围与旁边的附属文件导出使用同一份选择／筛选条件 —— 见[导出到编辑器](VIEWER.md#导出到后期软件)。它写出的 `facet_manifest.json` 形态与 `--export-manifest` 完全相同，所以无论文件是哪一侧生成的，下面的增效工具对话框都能同样工作。

### Facet 增效工具（星级、留用旗标、元数据字段与关键字）

Facet 仓库里的 `facet.lrplugin/` 是一个 Lightroom Classic 增效工具，它把 Facet 的星级和收藏／淘汰状态**直接写进目录**。它之所以存在，是因为上文提到的两件事无法从 XMP 一侧解决：Lightroom 永远找不到专有 RAW 文件对应的 Facet 附属文件，而 XMP 根本没有承载 Lightroom 留用旗标的通道。该增效工具读取的是一个清单文件，因此它从不与 Facet 服务器通信，不需要密码，即使 Facet 没有运行也能工作 —— 而且因为它按路径而不是按附属文件匹配照片，**纯 RAW 照片库的表现与 JPEG 照片库完全一样**。

该增效工具在**图库 → 增效工具附加功能**（**Library → Plug-in Extras**）下注册了两个菜单项：**Facet: Apply ratings and flags...**（清单 → 目录方向，本节介绍）和 **Facet: Export Lightroom State to Facet...**（反方向 —— 见下文[Lightroom → Facet](#lightroom--facet)）。

**安装**（只需一次）：

1. 把 `facet.lrplugin` 文件夹复制到运行 Lightroom 的机器上。在 macOS 上请先压缩成 zip —— 访达会把 `.lrplugin` 文件夹当作程序包。
2. 在 Lightroom Classic 中：**文件 → 增效工具管理器 → 添加**，选择 `facet.lrplugin` 文件夹，然后点击**完成**。

**使用**（每当你想把 Facet 的判断带进目录时）：

1. `python facet.py --export-manifest /photos/2026-wedding`（路径用于限定导出范围；文件始终以 `facet_manifest.json` 的名字落在当前目录）。如果 Facet 运行在别的机器上，请把它复制到 Lightroom 所在的机器。
2. 在图库模块中选中照片，然后选择**图库 → 增效工具附加功能 → Facet: Apply ratings and flags...**（增效工具界面为英文）。
3. 在对话框中指向 `facet_manifest.json`。该路径会被记住，下次直接可用。
4. **如果 Facet 是在另一台机器上扫描这些照片的，请填写两个路径前缀。** 清单里保存的是执行扫描那台机器的路径（NAS 上是 `/volume1/photos/...`），而 Lightroom 记录的是桌面电脑的路径（`Z:\photos\...`）。请输入指向同一个文件夹的 Lightroom 前缀和 Facet 前缀；两者一致时就都留空。填错这里是首次运行中唯一真正要紧的失败 —— 它只会导致一张照片都匹配不上。
5. 选择范围：选中的照片（默认），或当前文件夹里的全部照片。
6. 点击 **Preview...**（预览）。**此时还什么都没有写入。** 增效工具会报告它在清单中匹配到了多少张照片、有多少张没匹配上，以及会设置多少个星级和旗标。如果匹配数为 0，它会把一个 Lightroom 路径样例和一个清单路径样例并排显示，让你看清前缀应该是什么。
7. 点击 **Apply**（应用）。过程中会显示进度并可以取消；结束时会有一个汇总对话框，说明哪些被设置、哪些被跳过、哪些没有找到。

**它写入什么** —— 仅此而已，并且从不写入你的图像文件：

| Facet 状态 | Lightroom 字段 |
|---|---|
| `star_rating` 1-5 | 星级 |
| 收藏 | 留用（Pick）旗标 |
| 已淘汰 | 排除（Reject）旗标 |

Facet 的星级为 0 表示“没有意见”（见 `xmp_export.score_to_rating`），永远不会被写出。

**覆盖语义** —— 默认情况下，增效工具绝不与你争辩：只有当照片在 Lightroom 中*没有星级*时它才设置星级，只有当照片*没有旗标*时它才设置留用／排除旗标。你手动评过星或打过旗标的内容一律原样保留，并在预览中计入“kept as they are”（保持原样）。勾选 **Overwrite ratings and flags that are already set in Lightroom** 才会改为覆盖它们。这与 `xmp_export.score_to_rating` 中的 `only_when_unrated` 一致，因此增效工具和附属文件这两条路径对待你的手动修改的方式完全相同。

**新的对话框选项**（均为可选，各自会记住到下次）：

- **Fill in star ratings from Facet scores for photos you have not rated** —— 当一张照片在清单里没有 `star_rating`（或为 0），但 Facet 的 `aggregate` 分数能映射出一个星级时，用这个推算出的星级补上空缺。因为这只是给*未评级*照片的兜底，不是清单里真正的星级，所以它**永远不会覆盖 Lightroom 里已有的星级 —— 即便勾选了 Overwrite 也不会。** 清单里真正的 `star_rating` 仍然遵循上面那条正常的覆盖规则，不受影响。
- **Pick the recommended frame of each burst** —— 对清单中至少有 2 个成员的每个连拍组，把清单标记为 `is_burst_lead` 的每一个成员（一组连拍可以保留不止一张）都设为留用（Pick）。清单从未把它和其他照片分到一组的孤立帧永远不会被这个选项动到，而整个清单中都没有任何 `is_burst_lead` 成员的连拍组会被完全跳过（没有可依据的信息）。手动设置的留用／淘汰旗标 —— 或清单里的 Facet 收藏／淘汰 —— 永远优先于这个推算出的留用。
- **Reject the other frames**（嵌套在上一个选项之下，只有连同它一起勾选才会启用）—— 把连拍中*不是*首选帧的每个成员设为淘汰（Reject），但有两个例外：曝光包围、全景或 HDR 全景的成员永远不会被这条规则淘汰，即便它的 `burst_group_id` 也把它和其他照片分到了一组 —— 这些集合要整套保留；而整个清单里都没有首选帧的组（见上文）同样不会得到任何淘汰。
- **Create Facet collections for bursts, brackets, panoramas and HDR panoramas** —— 对当前范围内至少匹配到 2 张照片的每个组，创建或复用一个名为 `<yyyy-mm-dd HH:MM:SS> – <filename>` 的收藏集（取最早那个成员的拍摄时间和文件名；该成员没有拍摄时间时用 `~ (no date) – <filename>`），嵌套在 `Facet › Bursts`、`Facet › Brackets`、`Facet › Panoramas` 或 `Facet › HDR panoramas` 之下。如果一个普通连拍组的成员*全部*已经完整属于某个曝光包围／全景／HDR 全景集合，就不会再为它单独建一个 Bursts 收藏集，因为那只会和 Brackets/Panoramas/HDR panoramas 下已有的那个重复。**重新运行只会新增**——把照片补进重新找到的收藏集，绝不会移除，所以一个收藏集可能会与之后被重新分组或重新检测的集合脱节（某张照片在之后的扫描里被移出某个曝光包围组，并不会把它从收藏集里移除）。如果两个不同组的最早成员在拍摄时间上精确到秒完全相同，且文件名也相同，收藏集的名字也会发生冲突——两台相机都在同一时刻写出了 `IMG_0001`，最终会共用一个收藏集，而不是各自得到一个。这是一个已知的局限，不是需要上报的缺陷。
  - **Rebuild (clear and refill) Facet collections fully covered by this run**（嵌套在上一个选项之下）—— 不再只是新增，而是清空并重新填充一个收藏集，但仅当该收藏集及其整个组都完全落在本次运行的范围之内时才会这样做；只被部分覆盖的收藏集（有成员在选择范围之外），或指向智能／无法解析的收藏集，会保持原样并计为已跳过，汇总会报告重建、删除、跳过和失败的数量。它还会触及本次运行中组已经解散的 Facet 收藏集（组内符合范围的成员不再满足至少 2 个，因而没有计划条目）——这样的收藏集也会被清空并删除，但仅当其当前持有的每张照片都是本次运行匹配到的；若其中持有任何一张本次运行之外的照片，则保持原样不动。只有在 **Create Facet collections for bursts, brackets, panoramas and HDR panoramas** 启用时才会提供——也才会运行——Rebuild；取消勾选该选项会同时关闭 Rebuild。已解散收藏集的清理只会触及名称与 Facet 自身生成的形式完全匹配的收藏集（一个 ISO 日期时间，或未注明日期的 `~ (no date)` 前缀，后接 ` – <filename>`），因此您自己在某个 Facet 集合下重命名的收藏集永远不会被清空或删除。当清理有内容可删除时，Preview 会新增一行 `Facet collections to delete: N`，并且即使这是唯一待处理的变更，清理也会运行，而不会被报告为无需更改。
- **Write Facet scores/category/set-kind as Lightroom plug-in metadata fields** —— 把 `aggregate` 分数（例如 `8.4`）、一个整数档位（`0`-`10`）、类别以及集合类型写入 Facet 自己的增效工具元数据字段，这些字段在“元数据”面板中可见，并可作为文本（`sdktext:`）条件用于图库筛选器／智能收藏集 —— 例如一个匹配档位“任意为 8、9、10”的智能收藏集。当某个字段不再适用于一张照片时（例如它离开了包围曝光集，集合类型随之消失），该字段会被清空而不是留下过期的值——否则依赖该字段的智能收藏集或图库筛选条件会继续匹配一张已经不再符合条件的照片。Adobe 的 SDK 只允许增效工具自有的字段以文本或枚举的形式进入搜索词汇表，绝不允许数值区间，所以仍然没有“aggregate > 8”这样的智能收藏集 —— 档位是最接近的文本替代方案。另外两个记账用的属性（本次运行推算出的星级／留用值）会同时写入，但不会出现在图库筛选器和智能收藏集条件里 —— 见下文 [Lightroom → Facet](#lightroom--facet) 中关于反向导出的说明。**尚未在真实目录上验证：** 一个无标题的元数据字段在“元数据”面板和图库筛选器中是否真的不可见，仅凭 Lightroom SDK 文档并不能确认；因此这两个记账属性被标记为 `searchable = false, browsable = false`，作为更保险、已确认的退路，而不是依赖未经确认的“省略标题即隐藏”行为 —— 它们在某些 Lightroom Classic 版本中仍可能可见。
- **Create "Facet" keywords from Facet tags (never included on export)** —— 创建一个 `Facet` 根关键字，为你照片携带的每个 Facet 标签建一个子关键字，并让每张照片的 `Facet ›` 子关键字与它清单中的标签精确对应（随着标签在多次运行之间变化而增删）。这个选项创建或触碰到的每个关键字都关闭了 `Include on Export`，所以 Facet 的自动标签永远不会泄露到 JPEG/TIFF 导出或客户画廊里。你自己在 `Facet` 根之外的关键字会被读取（用来检测一个预先存在的顶层 `Facet` 关键字，并将其采用为根），但这个选项永远不会新增、移除或写入它们；你自己手动放在这个被采用的 `Facet` 根下面的任何子关键字，都会被当作过时项移除。你的[手动标签](#手动标签与-xmp-关键字)与 AI 标签一样以 `Facet ›` 子关键字出现；因此在 Facet 中移除手动标签，会在下一次 Apply 时删除对应的子关键字。

**为什么是收藏集，不是堆叠。** Lightroom 的 SDK 没有任何调用可以创建或管理堆叠（Stack）——`stackInFolder`／`stackPositionInFolder` 在 `LrPhoto` 上都是只读的。收藏集是最接近的可写替代方案，而 `canReturnPrior` 让重新运行增效工具时能找回同一个收藏集，而不是重复创建。如果你想要真正的 Lightroom 堆叠，请自己选中某个收藏集里的照片，使用**照片 → 堆叠 → 编为堆叠**（Ctrl/Cmd+G）——这一步增效工具无法替你完成。

**局限**，实话实说：

- **留用旗标只存在于目录中。** 这是 Lightroom 的设计，不是增效工具的问题：Lightroom 从不把留用旗标写进 XMP，因此它到不了任何其他应用，一旦你从文件重建目录就会丢失。星级则可以通过**元数据 → 将元数据存储到文件**保留下来。
- **基于元数据字段的智能收藏集途径仍然只是文本。** Adobe 的 SDK 只允许增效工具自有的字段以文本或枚举（`sdktext:`）的形式进入搜索词汇表；数值运算符（`>`、`<`、“在范围内”）只属于 Lightroom 内置的条件。上文的档位字段是“aggregate > 8”最接近的文本替代方案；把原始评分经由**星级**（上文的兜底选项）传递，仍然是 Lightroom 自身唯一会按数值筛选和排序的通道。
- **撤销**一次只作用于一批：增效工具按每 200 张照片为一块写入，因此按一次 Ctrl/Cmd+Z 会撤销 200 张照片。
- 如果你需要逐行查看哪些路径匹配上了、写入了什么，请在运行前勾选 **Write facet-apply.log next to the manifest**（在清单旁写出 facet-apply.log）。

### Lightroom → Facet

**星级、留用与淘汰 —— Lightroom 说了算（通过增效工具）。** **Library → Plug-in Extras → Facet: Export Lightroom State to Facet...** 会打开一个保存面板（没有默认文件名或位置），用来写出一个 Lightroom 状态文件（每张照片一条记录：`path`，以及仅在仍需要传递时才出现的 `rating`／`pick` —— 见下文）。用 `python facet.py --import-lightroom facet_lightroom_state.json` 把它导回来（在多用户安装上加上 `--user alice`；那里是必需的），或者在网页版查看器中，用图库 **Export to editor** 对话框里的 **Import Lightroom state…** 按钮，它会把文件内容直接发给服务器。对于记录中出现的每一个键，Lightroom 的值都会无条件胜出 —— 命令行和查看器共享同一个导入器 `processing/lightroom_sync.py`，它会报告 `matched`／`unmatched`／`changed` 计数：

| Lightroom 状态 | Facet 结果 |
|---|---|
| 留用旗标 = 已选中（`pick = 1`） | 收藏 = 开，淘汰 = 关 |
| 留用旗标 = 已淘汰（`pick = -1`） | 收藏 = 关，淘汰 = 开 |
| 留用旗标 = 无（`pick = 0`） | 收藏 = 关，淘汰 = 关 |
| 星级（`rating`，0-5） | `star_rating`（`0` 会清空它） |

一条省略了 `rating` 或 `pick` 的记录，会让 Facet 对应的值保持不变 —— 导出只有当 Lightroom 当前的值与 Apply 方向最后一次为那张照片推算出的值不同时，才会包含这个键（两个隐藏、不可搜索的增效工具属性记录着这个基准），所以重新导出一张未被触碰的照片会写出一条空记录，什么都不会改变。因为 Lightroom 无条件胜出，导出还会清除任何已导出照片上 Apply 方向从未触碰过的 Facet 评分／收藏／淘汰状态 —— 在 Lightroom 中未评分、未标记的照片（`pick = 0`，没有 `rating`）会把 Facet 已有的星级或收藏／淘汰状态覆盖为“无”。一次改变了任何内容的成功导入，也会像其他任何星级写入一样，重建星级推导的训练对，并触发同样的空闲触发式自动再训练。虚拟副本会在导出前按路径去重到其母版，两者都存在时优先保留母版。

**星级、标签和关键字（通过 XMP）。** 另外，在这个方向上仍然是单向的：

1. 在 Lightroom 中选中照片，选择**元数据 → 将元数据存储到文件**（Ctrl/Cmd+S）。这会把目录中的星级／颜色标签／关键字刷写进 XMP 附属文件（RAW），或直接嵌入文件本身（DNG/JPEG/PSD/TIFF）。
2. `python facet.py --import-sidecars /path --sidecar-naming basename` 读取已保存的 RAW 附属文件；共享基本名的 RAW/JPEG 会被拒绝。此命令不提取内嵌元数据。外部关键字会成为手动标签。

### 冲突规则

- **标签和关键字默认合并。** 导出会添加 Facet 关键字；`--reconcile-keywords` 还会移除仅属于 Facet 的过时名称。导入会添加手动标签，不会替换 AI 标签。 [手动标签与 XMP 关键字](#手动标签与-xmp-关键字).
- **多用户**（`--export-sidecars --user alice` / `--import-sidecars --user alice`）：评分会写入 Alice 的 `user_preferences` 行，而不是全局列。无论 `--user` 如何，关键字都保持全局——手动标签由所有用户共享。
- 导入的关键字会进入 `photo_manual_tags` 表，标签筛选直接读取该表，因此 `--import-sidecars` 之后不再需要运行 `python database.py --migrate-tags`。

## Capture One

Capture One 从不像 Lightroom 的自动保存那样写入原始文件或写入持续同步的 XMP 附属文件 —— 它把自己的调整保存在 `.cos` 设置文件（Sessions）或它的目录数据库里，而它的 **Sync Metadata** 首选项有一个双向的“Full Sync”模式，可能会静默覆盖后写入的那一方。通过这个设置来跑双向循环，有丢失 Facet 或 Capture One 任一方修改的风险。安全的做法是**单向，Facet → Capture One**：

1. `python facet.py --export-sidecars /path/to/shoot --embed-originals`。
2. 在 Capture One 中，把 **Preferences → General → Sync Metadata** 保持为默认值（不要选“Full Sync”）。
3. 选中导入的图像，右键点击，选择 **Load Metadata**，把附属文件（或内嵌元数据）里的星级／颜色标签／关键字一次性拉进 Capture One 的目录字段。

将 Facet 作为 AI 星级和标签来源：执行一次 `Load Metadata`，然后在 Capture One 中继续操作，不启用自动双向同步。要明确导入已保存的 XMP，对于去掉图像扩展名的 RAW 附属文件运行 `--import-sidecars /path/to/shoot --sidecar-naming basename`，完整名称则用 `full`。共享基本名的 RAW/JPEG 会被拒绝。此命令只读取附属文件，不读取内嵌元数据。

## digiKam

digiKam 的[附属文件设置](https://docs.digikam.org/en/setup_application/metadata_settings.html#sidecars-settings)选择一种命名约定：通常为 `filename.ext.xmp`；启用 **Sidecar file names are compatible with commercial programs** 后则为 `filename.xmp`。不要假定它会同时尝试两种名称。读取 Facet 导出时，请使用完整名称设置并启用 **Read from sidecar files**，再明确将文件元数据重新读入 digiKam 数据库并核对所选字段。从 digiKam 导入 Facet 时，按保存的设置选择 `--sidecar-naming full` 或 `basename`。星级、颜色标签和选片标记语义不同；文件名一致不等于已验证跨应用往返。

### Batch Queue Manager 挂钩

可在 digiKam 批处理队列管理器（BQM）的 **Custom Script** 工具中运行 Facet 导入。先启用附属文件写入，保存命名设置，并在导入前应用待处理的元数据更改；延迟同步可能推迟写入。下面示例假设使用完整名称；只有商业命名的照片集合不存在基本名歧义时，才将 `full` 改为 `basename`：

```bash
#!/bin/bash
python /path/to/facet.py --import-sidecars --sidecar-naming full "$(dirname "$INPUT")"
cp "$INPUT" "$OUTPUT"
```

`$INPUT` / `$OUTPUT` 是 digiKam 的按文件占位符（在 Linux／macOS 上，BQM 通过 `/bin/bash` 执行脚本并期望有一个输出文件，因此需要 `cp` 透传）。由于 `--import-sidecars` 会扫描整个文件夹，在大批量任务中对每张照片都执行一次是多余的，尽管无害（它是幂等的 —— 未改变的照片会被跳过）。批量很大时，跳过 BQM 挂钩，等队列跑完后手动执行一次 `python facet.py --import-sidecars /path/to/folder` 即可。

## darktable

darktable 在[配置 — 查看器](CONFIGURATION.md#查看器)（`viewer.raw_processor.darktable` 导出配置文件／样式）和[查看器 — 下载](VIEWER.md#api-端点)（`type=darktable` 转换）中已经享有一等公民的待遇。在 XMP 一侧：darktable 会自己写出 `<image><ext>.xmp` 来保存它的编辑历史，而 Facet 由 exiftool 驱动的附属文件写入器会就地合并进同一个文件 —— `darktable:history`／蒙版节点会被保留，绝不会被覆盖。这里不需要单独的操作指南：上文为 Lightroom 描述的双向附属文件行为（导出／导入、最新者胜、标签求并集）同样适用，而且没有 RAW 命名不一致的问题，因为 darktable 和 Facet 在 `<image><ext>.xmp` 上是一致的。

**exiftool 版本。** 建议使用 ExifTool **13.28 或更高版本**。人脸变更需要 **12.65 或更高版本**；较旧或未知版本会警告并跳过人脸变更，仍导出其他元数据。13.23 至 13.27 版本会损坏带有 darktable 编辑历史的 XMP sidecar（以 `=` 结尾的属性值后紧跟另一个属性时会被错误解析，而 exiftool 仍返回退出码 0），因此 Facet 拒绝使用这些版本写入，并报告错误提示升级。Docker 镜像内置固定版本的 exiftool，不受影响；发行版软件包则可能受影响（Debian trixie 的 `libimage-exiftool-perl` 为 13.25）。

**注意：darktable 自己的 XMP 重新加载并不可靠。** 与 Facet 的写入路径无关，重新导入一张 darktable 已经编辑过的图像，可能会让 darktable 用一份空白历史覆盖附属文件里的编辑历史，而不是把它加载回来 —— 这是一个仍未解决的上游 bug（[darktable#20537](https://github.com/darktable-org/darktable/issues/20537)，报告于 2026-03-15），“check for new/updated xmp files on start”这个首选项并不能防住它。Facet 不是原因（上文经由 exiftool 的合并已经保留了 `darktable:history`），但风险恰恰落在本页的往返流程所依赖的回读步骤上。实用的规避办法，遵循与上文 Capture One 指南相同的“一次性”纪律：执行 `--export-sidecars` 之后，不要对已经编辑过的文件夹做批量重新导入 —— 只为 Facet 刚刚触及的那些图像重新加载附属文件，确认编辑历史还在，再去信任这一批的其余部分。

## 手动标签与 XMP 关键字

Facet 把你自己输入的标签（参见[查看器——手动标签](VIEWER.md#手动标签)）保存在一张独立的附表 `photo_manual_tags` 中，与 `photos.tags` 里的 AI 标签分开。这种分离使重新扫描或重新打标不会动到它们，也决定了关键字如何经由 XMP 往返：

- **导出。** 每个写关键字的环节都按先 AI 标签、再手动标签、最后人物姓名的顺序输出，并且不区分大小写地去重：`--export-sidecars`、照片库的 XMP 导出和“将元数据写入文件”操作，以及 Lightroom 清单（`--export-manifest`、`/api/lightroom/manifest`）。
- **导入。** `--import-sidecars` 只读取 `dc:subject`。每个关键字都会像手动输入的标签一样被规范化（去除首尾空白、转小写、最多 64 个字符、每张照片最多 50 个手动标签）。它会被存为来源为 `xmp` 的手动标签，除非它已经是照片当前的某个 AI 标签、等于照片的某个人物姓名、是分层路径 `a|b`、含逗号或控制字符，或会超出上限。导入的关键字不再写入 `photos.tags`，所以重新打标不会再覆盖它们。
- **删除必须明确选择。** 默认导出仍只添加关键字。安装 ExifTool 后，`--export-sidecars /路径 --reconcile-keywords` 仅移除 Facet 曾声明拥有、而当前 Facet 关键字中已不存在的名称。原有外部名称（包括同名词）保持不变；旧文件没有归属标记，就不授予任何归属。`facet:KeywordState` 保存归属及删除标记。名称在文件中重新出现，或 Facet 再次写入该名称时，旧删除标记失效。外部重新添加的手动关键字可以再次导入，后续导出将其视为外部名称。使用 `--user` 时关键字仍为共享数据。
- **导出以 Facet 当前关键字为准。** 两种模式都会重新写入仍在 Facet 中、但被其他编辑器从文件移除的词。如需接受外部删除，也须在 Facet 中删除该词；不会自动删除数据库标签或进行双向同步。`2024`、`1.50`、`1e3`、`true`、`false` 和 `null` 等名称保留原有拼写，即使 ExifTool 将其表示为 JSON 数字或布尔值。现有文件读取失败或结构无效时，任何导出都会在写入前拒绝。每份列表最多 10,000 个名称，每个名称最多 1,024 个字符；超限会拒绝写入并保留删除标记。没有 ExifTool 时，协调操作在写入前拒绝。
- **Lightroom 清单则会传播移除。** 插件的关键字选项会在 Apply 时把每张照片的 `Facet ›` 子关键字改写成与清单一致；在 Facet 中移除的标签因此会在下一次 Apply 时从 Lightroom 中消失。
- **重新标记保留 AI 来源。** 新数据包区分 AI 与手动标签；旧 AI 标签不会因重新标记而变为手动标签。无标记的旧数据包仍按原有方式添加。没有 ExifTool 时，协调操作会在写入前拒绝；层级关键字仍只添加。
- **旧版 Facet 导入的关键字留在原处。** 在手动标签出现之前，导入会把关键字直接合并进 `photos.tags`，在那里它们与 AI 标签无法区分，也没有任何迁移会移动它们。这样的关键字会一直显示为 AI 标签，直到 `photos.tags` 被清空或照片被重新打标；而由于导入会跳过已在 `photos.tags` 中的关键字，它也不会重新出现为手动标签。要转换它，请先清空或重新打标 `photos.tags`，再重新运行 `--import-sidecars`；或者直接手动添加该标签。
- **被移动或重命名的文件会失去它的手动标签。** 它们与照片路径绑定，而移动或重命名后该路径指向的是另一张照片。
- **`--export-csv` 和 `--export-json` 仍然只含 AI 数据。** 它们的 `tags` 值是原始的 AI 列，不含手动标签。

## Facet 如何合并

| 字段 | Facet 写入 | Facet 读回 | 冲突规则 |
|---|---|---|---|
| 星级／淘汰 | `xmp:Rating`（`-1` = 已淘汰） | `xmp:Rating` | 审核字段编辑时间；旧数据使用扫描时间 |
| 颜色标签 | `xmp:Label`（`Red` = 已淘汰，`Yellow` = 收藏） | `xmp:Label` | 审核字段编辑时间；旧数据使用扫描时间 |
| 标签／关键字 | `dc:subject`（扁平，AI 标签 + 手动标签，包含已命名人脸的人物姓名） | `dc:subject`（存为手动标签） | 默认只添加；`--reconcile-keywords` 仅移除属于 Facet 的过时名称；导入仍只添加 ([手动标签与 XMP 关键字](#手动标签与-xmp-关键字)) |
| 层级标签 | `lr:hierarchicalSubject`（`Category\|<cat>`、`People\|<name>`） | 不再导入 | 仅导出 |
| 照片描述 | `dc:description`（+ 经由 exiftool 的 `IPTC:Caption-Abstract`） | 不再导入 | 仅导出 |
| 命名的人脸区域 | MWG `mwg-rs:RegionList` + `facet:RegionOwner=Facet`（中心归一化，`Type=Face`） | 不再导入 | 仅导出；由 digiKam 原生读取，Lightroom **不**读取（一个已知的 Adobe 限制 —— Lightroom 只消费它自己写出的 MWG 区域） |

完整的 CLI 参考（`--export-sidecars`、`--import-sidecars`、`--embed-originals`、`--score-to-stars`、`--user`）请见[命令 — 预览与导出](COMMANDS.md#预览与导出)。

当过时的 `facet:GPSState=cleared` 标记与标准 GPS 字段并存时，以完整且有效的经纬度为准。含有非空值但不完整或无效的坐标存在歧义，将被忽略，绝不会清除位置。仅当坐标均缺失或为空且存在明确的清除标记时才清除 GPS。已有手动 GPS 仍受保护，除非明确要求覆盖。

使用 ExifTool 导出说明时，只更新 `dc:description` 的 `x-default` 语言，保留现有附属文件或图像中的其他语言。Facet 说明为空时，现有说明保持不变。没有 ExifTool 时，XML 包含默认语言；若已有附属文件，默认改写到 `<image>.facet.xmp`。显式覆盖仍会替换整个目标数据包。

ExifTool 仅替换 Extensions 中带 `facet:RegionOwner=Facet` 标记的 MWG 矩形。未标记的区域（包括旧版 Facet 导出）会保留，因为名称和坐标不能证明归属。升级后，旧的未标记人脸可能与新的带标记副本同时出现；清除人脸仍会保留旧副本。重复导出只替换带标记副本，不会继续累积重复区域。外部区域及其未知扩展保持不变。当前人脸尺寸不一致，或外部区域的图像尺寸不同或未知时，会警告并跳过全部人脸变更，但仍导出评分、标签、关键词和 GPS。无法读取或无效的现有人脸元数据会在写入前拒绝单张导出或嵌入，并返回 HTTP 412。无 ExifTool 的 XML 后备方式不导出人脸矩形。带标记区域即使被外部编辑仍归 Facet 管理；如需作为独立标注，请先移除归属标记。 嵌入前会检查原图及附属文件的已知前提条件。分开写入多个文件并非原子操作；后续外部修改或 I/O 故障仍可能留下部分结果。

ExifTool 版本检查不可用、失败或返回无效结果时，会在下一次检查时重试。版本未知期间，Facet 跳过人脸区域修改，仍可导出其他元数据；后续检查成功且该版本支持人脸导出时，会恢复人脸导出。已知有缺陷的版本仍会在写入前被拒绝。

## 附属文件导入预览与冲突

`--import-sidecars /路径 --dry-run` 输出 JSON，列出所选文件、前后值、标签增加、来源和跳过原因。现有数据库以只读方式打开，不迁移、不提交。正式应用会在写事务中重新读取文件和数据库；预览 JSON 不是应用令牌。

如果数据库不存在、无法读取或无效，预览会显示错误消息并以退出码 1 结束；不会创建或修复数据库。`--dry-run-count` 仅限制扫描样本数，不限制导入预览。

`--sidecar-fields review,gps,keywords` 选择字段组。`review` 将星级、收藏、拒绝和 Keep 作为整体，避免半个决定生效。没有 `--overwrite-manual-gps` 时仍保护手动 GPS。关键字仍只添加，且使用 `--user` 时仍共享。

升级后，SQLite 触发器为每张照片、账户及审核字段保存一条最新凭据，包括重置和删除偏好行。较旧数据包产生 `newer_local_edit`，保留整个审核组；`--overwrite-sidecar-review` 可明确覆盖。XMP 凭据记录文件与时间；`local` 表示未知 SQL 写入者，并不表示已验证的人类作者。不增加描述、人脸、层级或无标记外部 GPS 导入。

没有凭据表示编辑时间未知，这是数据状态而非旧模式别名。`untracked_legacy_edit` 明确表示采用扫描时间，不推测人工编辑时间。预览无需迁移即可读取已发布版本的模式；缺少 Keep 字段表示未决定。来源时间取 `xmp:MetadataDate`，缺失或无效时取文件修改时间。最多展示范围内 1,000 张照片及每张 100 条诊断，并提供省略计数；范围和用户可见性在规划前生效。

编辑凭据仅属于其所在数据库。新导出的查看器数据库不包含扫描端凭据或 XMP 路径；增量导出仅保留查看器已有的凭据，不复制扫描端的编辑权限。查看器中的显式重置（包括删除的用户偏好）会保留；没有查看器编辑的扫描端值仍正常更新。旧预览版本可能已经复制了无法确定来源的凭据：为避免丢弃真实的查看器编辑，系统保守保留这些凭据，不推测时间戳。显式重建前请备份并检查数据库；完整重建不会保留查看器本地修改。
