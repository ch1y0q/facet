# AI 智能体（MCP）

> 🌐 [English](../AGENTS.md) · [Français](../fr/AGENTS.md) · [Deutsch](../de/AGENTS.md) · [Italiano](../it/AGENTS.md) · [Español](../es/AGENTS.md) · [Português](../pt/AGENTS.md) · **简体中文**

Facet 可以充当 [Model Context Protocol](https://modelcontextprotocol.io/)（MCP）服务器，让支持 MCP 的 AI 助手使用与图库相同的筛选条件搜索和查看你的照片库。它提供十三个不会改动照片库的只读工具，以及十四个 `ui_*` 工具：它们操作你已经打开的浏览器标签页（页面、筛选条件、选择），从不写入照片库数据。获得授权的令牌还可以[修改内容](#修改内容)（评分、标记、标签、相册、选片和删除）并操作[暗房](#暗房选片分组)。

## 启用

该端点**默认开启**。要关闭它，请在 `scoring_config.json` 中把 `viewer.mcp.enabled` 设为 `false`（参见 [智能体端点（MCP）](CONFIGURATION.md#智能体端点mcp)），然后重启查看器或重新加载配置；此后 `/mcp` 和所有 `/api/mcp/*` 路由都返回 404。没有 `viewer.password` 时，即使设置了 `viewer.edition_password`，该安装也视为开放安装，其令牌为 `readonly`，除非启用了 `viewer.trusted_local_editing`。在开放安装上，该端点只提供一个只读匿名密钥，它不授予开放的 `/api` 本来没有授予的任何权限。在开放安装上，助手令牌只能在运行 Facet 的电脑上创建、列出和吊销（设置了 `viewer.edition_password` 时，也可在编辑会话中进行）；其他任何请求都会被 403 拒绝。

端点是查看器自身端口上的 `POST /mcp`：Streamable HTTP、无状态、纯 JSON 响应。`GET` 返回 405。只有标签页桥接 `/api/mcp/bridge` 是 WebSocket，参见[控制已打开的标签页](#控制已打开的标签页)。

## 创建令牌

最简单的方式是在浏览器中操作。启用 `viewer.mcp.enabled` 后，打开账户菜单并选择**连接助手**。输入**名称**，选择**助手可执行的操作**：**仅读取和操作界面**；若当前会话具备相应级别，还可选择**代表我操作**或**完全编辑**（令牌的级别不能高于创建它的会话），然后点击**创建令牌**。对话框随后会显示**将此内容粘贴到您的助手中**，并附带一段包含令牌的现成提示词。它只显示一次：请点击**复制提示词**，粘贴到您的助手中，再点击**完成**。**管理令牌（N）**列出您的令牌及其最近使用时间，并可撤销其中一个；状态行则说明此标签页是否已连接、能否被助手操控。级别列表仅限服务器会授予的范围：开放安装只提供**仅读取和操作界面**，**代表我操作**仅出现在多用户安装中，**完全编辑**仅在编辑会话中提供；在开放安装中，这意味着在同一台计算机上的浏览器且启用了 `viewer.trusted_local_editing`。提示词中会写明实际授予的级别。在开放安装上，该对话框只能在运行 Facet 的电脑上使用（设置了 `viewer.edition_password` 时，也可在编辑会话中使用）；在其他设备上，它会显示“在开放安装中，助手令牌只能在运行 Facet 的电脑上管理。设置 viewer.password 后即可从其他设备管理。”以取代表单，并不再向服务器发起请求。

通过脚本创建（curl）：

助手使用以 `fct_` 开头的个人令牌进行认证。用一个已认证的请求创建它（令牌**只返回一次**；Facet 只保存它的 SHA-256 哈希）：

```bash
TOKEN=$(curl -s -X POST http://localhost:5000/api/auth/login -H 'Content-Type: application/json' -d '{"password": "YOUR_VIEWER_PASSWORD"}' | jq -r .access_token)
curl -s -X POST http://localhost:5000/api/mcp/tokens -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"name": "my-assistant", "level": "readonly"}'
```

响应的 `token` 字段包含明文令牌。`GET /api/mcp/tokens` 列出你的令牌（绝不包含密钥本身），`DELETE /api/mcp/tokens/{id}` 吊销其中一个。超级管理员可以用 `?all=1` 列出所有所有者的令牌并吊销任意一个。每位所有者最多持有 20 个有效令牌（超出返回 412）。这些路由会以 403 拒绝智能体自己的凭据，因此助手永远无法创建、列出或吊销令牌。在开放安装（无 `viewer.password`）上，凡不是来自运行 Facet 的电脑的请求，这些路由同样返回 403：经过反向代理的请求（任何 `Forwarded`、`X-Forwarded-*` 或 `X-Real-IP` 头）、使用局域网 IP 或主机名而不是 `localhost`、`127.0.0.1` 或 `[::1]` 寻址的请求，以及经由 Docker 桥接网络到达的请求。请在 Facet 主机上运行上面的示例（NAS 上通过 SSH；在 Docker 中使用 `docker compose exec facet python -c "import urllib.request ..."`，因为镜像里没有 curl），或者设置 `viewer.password`。使用 `viewer.edition_password` 登录的会话可从任何设备接受。反向代理必须发送 `X-Forwarded-For` 或 `Forwarded`，否则会被当作本机。

## 连接您的助手

对话框生成的提示词包含支持 MCP 的助手所需的一切：服务器名称 `facet`、URL（`http://<主机>/mcp`）、传输方式（Streamable HTTP）、请求头 `Authorization: Bearer fct_...`、已授予的访问级别，以及用于确认连接的 `status` 工具调用。请把它粘贴到您的助手中，或自行把该服务器添加到您使用的 MCP 客户端。只要查看器可以从你自己的机器之外访问，就请使用 HTTPS，因为每次调用令牌都会放在请求头里传输。

## 权限级别

令牌创建时被授予一个级别：`readonly`、`user` 或 `edition`。**有效**级别在每次调用时重新计算，取令牌授予级别与其所有者当前级别中较低的一个：

- 单密码安装：`user` 在创建时被限制为 `readonly`，因为该模式没有中间级别。`edition` 令牌需要编辑会话，且只在编辑密码未变更期间有效。
- 多用户安装：之后被降级的用户的 `edition` 令牌会降为 `user`；升级绝不会让令牌超过其授予级别。
- 开放安装（未设置 `viewer.password`，即使设置了 `viewer.edition_password`）：令牌归属于共享所有者 `_anonymous`，为 `readonly`，除非启用了 `viewer.trusted_local_editing`（见下一条）。它们只能在同一台电脑上创建、列出和吊销。
- **开放安装上的本地编辑。** 启用 `viewer.trusted_local_editing` 后，“连接助手”对话框可在同一台计算机的浏览器中创建**完全编辑**令牌（仍需 `viewer.mcp.enabled` 和令牌：不带令牌的调用仍为 401）。该令牌仅对来自同一台机器的 `/mcp` 请求为 `edition`：对端为环回地址，URL 为 `http://localhost:<port>` 或 `127.0.0.1`，且没有代理头；`:4200`（`ng serve` 开发代理）和 `:5000` 均符合。使用同一令牌的任何其他请求（包括局域网客户端）都会降为 `readonly`，主机名或 `0.0.0.0` 的 URL 以及 Docker 部署也一样，即使提示词写的是完全编辑。任何密码都会把令牌降为 `readonly`，清除密码后令牌恢复（令牌本身未被改动）。删除类工具仍需要 `viewer.mcp.allow_destructive`。本地助手与本地浏览器一样，无需 `viewer.features.show_scan_button` 即可扫描（`start_scan`、`scan_status`）。
- **注意。** `ng serve --host 0.0.0.0` 或同一主机上任何未加标记的代理，会让发送 `Host: localhost` 的局域网客户端越过边界，此时只剩令牌保护 `/mcp`。
- 单密码安装没有 `user` 级别：有效级别只有 `edition` 或 `readonly`，因此[修改内容](#修改内容)中标为 `user` 的工具在那里同样需要 `edition` 令牌。 用较低级别的令牌调用 `user` 工具时，返回 `forbidden_level` 并说明需要 `edition`。
- 每个工具都有自己的最低级别，在读取或写入任何内容之前检查；级别更低的令牌会收到 `forbidden_level`。

所有者的凭据一旦变化，令牌会自动失效：单密码模式下是查看器或编辑密码，多用户模式下是所有者的密码，或其账户被删除。此后它在入口处返回 401。

## 工具

十三个数据工具均为只读：

| 工具 | 作用 |
|------|--------------|
| `search_photos` | 像图库一样筛选和排序照片库，除非筛选条件另行设置，否则应用查看器的默认隐藏开关（闭眼、连拍、重复、包围曝光、全景、已拒绝）（会报告 `hidden_summary`）。默认显示在你打开的标签页中（见下文）；`fields` 可添加任意照片列 |
| `semantic_search` | 按含义查找照片，或用 `scope: "text"` 按说明文字中的词查找。它返回的行会固定在标签页中。 `filters` 像图库的筛选一样缩小搜索范围,每一行都带有其 `similarity`。 |
| `get_photo` | 按路径获取单张照片的完整详情（不含直方图） |
| `get_thumbnail` | 查看一张照片:其缩略图作为图像部分(`size` 160 至 640,默认 512)。若 JPEG 会超过 `viewer.mcp.max_image_bytes`,则使用更小的尺寸;都放不下则返回 `too_large` |
| `contact_sheet` | 将 1 至 16 张照片作为一张带编号的网格图查看(`columns` 2 至 4,最长边 1024)。文本部分列出 `legend`(格子编号对应路径,按请求顺序)和 `unavailable`(因照片缺失或不可见而留空的格子) |
| `possible_faces` | 与某个已识别人物相似的人脸:与该人物质心的余弦相似度,最佳在前,仅限同一嵌入模型。`scope` 为 `unassigned`(默认)、`other_persons` 或 `all`;`min_similarity` 默认 0.30;`limit` 最多 100。超过 192000 张人脸的扫描会被拒绝(`too_large`):用 `scope`、`path_prefix`、`date_from` 或 `date_to` 缩小范围。照片会显示在你的标签页中。`candidates` 是范围内您可见的人脸数量（在嵌入维度检查之前）；`faces_scanned` 是实际评分的行数。 |
| `similar_photos` | 按视觉嵌入或颜色查找与某张照片相似的照片；`min_similarity`（0 到 1）设定下限 |
| `filter_options` | 筛选条件接受的词汇：相机、镜头、标签、人物、构图模式、类别、叙事瞬间、垃圾类型、指标范围 |
| `list_persons` | 已识别的人物，可按姓名过滤 |
| `list_albums` | 令牌所有者能看到的相册 |
| `library_stats` | 照片库统计：`kind` 选择规模与评分概览（默认）或统计页面的任意数据（见下文） |
| `status` | 令牌是谁、它的有效级别、服务器标志以及它能控制的已打开标签页 |
| `available_actions` | 此刻适用于你已打开的标签页和该令牌的任务,每项附带其工具;超出令牌级别的工具不会列出 |

在每个筛选对象中，`show_rejected` 是布尔值：`true` 只列出被淘汰的照片，`false` 或省略则为常规列表。

## 结果会显示在你的标签页中

- `search_photos`、`semantic_search` 和 `similar_photos` 带有 `show`（默认 `true`）。第一页搜索成功后，服务器会在你打开的 Facet 标签页中显示它。`search_photos` 和 `similar_photos` 把同一查询应用到该标签页并替换其筛选条件；`semantic_search` 则始终固定恰好它返回的那些行（相似度顺序，最多 `limit` 行，无论有无 `filters` 或 `scope`），作为助手选定的列表（`shown_in_tab.mode` 为 `paths`），因为标签页自身的语义视图受隐藏开关过滤且排序不同。两种情况下，无需询问你都能看到助手找到了什么。助手被告知不要询问是否打开或显示结果；`show: false` 用于中间探查和计数，你看到的是最后一次显示的搜索。
- 结果带有 `shown_in_tab`：`{"applied": true, "tab_id", "keys", "total"}`，或 `{"applied": false, "reason"}`，原因为 `no_tab`、`bridge_disabled`、`tab_outdated`、`tab_timeout`（标签页仍可能应用它）、`forbidden`、`page_not_first`、`empty_result`、`unsupported_filters`（附带 `keys`）、`invalid_combination`、`unsaved_decisions`、`navigation_refused`（标签页拒绝了导航）或 `comparison_open`（用户在 `/compare` 上）。显示失败绝不会使搜索失败。传入 `tab_id` 可选择标签页。全部原因：`error`（显示本身失败）、`bridge_disabled`、`page_not_first`、`empty_result`、`invalid_combination`、`unsupported_filters`（附带 `keys`），以及标签页桥返回的代码（`no_tab`、`tab_outdated`、`tab_timeout`、`forbidden`、`invalid_input`、`upstream_error`、`unsaved_decisions`、`navigation_refused`）以及 `comparison_open`。行被截短时，`next_page`（连同 `suggested_per_page`）给出恰好接在最后一行之后的页码；若页码无法表达该位置，则由 `next_offset` 以行偏移给出。
- 只显示第一页（标签页在你滚动时自行分页），空结果不会显示，因此你保留之前的视图。使用图库侧栏没有对应控件的筛选（`exclude_tags`、`require_tags`、`is_silhouette`、`junk_kind`、`narrative_moment`、`min_rating`、`min_aggregate`、`show_rejected: true`）的搜索不会被部分应用。
- 显示会离开 `/photo` 并回到图库；仅当用户在 `/culling` 上没有未确认的决定时才会离开它（否则以 `unsaved_decisions` 拒绝）；在 `/compare` 上会以 `comparison_open` 拒绝且不做任何更改，并清除整个视图的选择；在相册页面上会先回到图库，因此相册已保存的筛选绝不会被覆盖。其数量要用作写入工具 `expected_count` 的搜索应使用 `show: false`。
- `ui_show_photos` 固定一份精确的照片列表:图库按你的顺序显示这些照片,直到筛选条件的更改替换该列表。`ui_get_context` 会报告当前是否显示了固定列表。该列表很朴素:不带分组、标记或标签。要复核选片方案,助手使用 `auto_cull`,它会改为在[暗房](#暗房选片分组)(`/culling`)中打开方案。
- **`/culling` 上的方案模式。** `ui_show_culling_plan`(由 `auto_cull` 在试运行时调用)把 `auto_cull` 方案载入暗房:分组、保留/剔除边框、放大镜和对比与手动选片相同,方案的保留照片已预先选中。横幅显示“助手方案 · 已确认 x/y · 退出”,每个分组带有一枚标签“#n · 理由 · 建议:保留 N / 剔除 M”,与方案不同的帧上会出现一个圆点。你按暗房的常规方式逐组确认:同样的空格键、倒计时和撤销;方案显示期间,排序和阈值被禁用,但严格程度滑块仍可使用:拖动它或更改工具栏上的日期范围会重新规划(得到新的 `plan_digest`),你已更改的分组保留你的选择,一个分组落入你已确认的分组之内时,会重新形成为已确认状态,场景分组也不例外(使用 `group_by=all` 时,已确认的 burst 若其保留的照片重新出现在更大的 similar 分组中,会再次被提出;你的剔除仍然有效);已跳过的分组在重新规划后会回来,拖动滑块时仍在倒计时的确认会立即提交;拖动滑块或更改日期范围后方案重新计算期间,确认、跳过和“全部确认”会暂停,直到新方案到达。更改日期范围(范围变窄)会像滑块一样在新窗口上重新规划:翻转和已确认的分组按照片集合延续,窗口之外的分组被丢弃(丢失的翻转会在通知中说明),**所有日期**会对整个图库重新规划,可能触及方案上限(`plan_truncated`)。点击**退出**,或更改分组、相册/场景范围或排序,即退出方案模式。离开 `/culling`(例如去打开一张照片)再返回,会根据标签页中已加载的方案恢复方案模式,并保留你已确认的 x/y;完整重新加载页面会丢弃方案,但会在 URL(`?from=`、`?to=`)中保留它的相册和日期,并落到基于它们的手动列表上。照片库已超前于方案时,会显示过期提示。方案模式中的确认从不添加精选。**建议徽标。** 助手可以用简短理由(`ui_suggest_culling`)标记它会保留或剔除的照片,显示为帧上的虚线徽标,并为分组添加简短备注,显示为分组标题中的标签;点击徽标会像你自己切换一样翻转该照片(分组仍由你确认),不点击则不会有任何改变。这些标记在拖动严格程度滑块或更改日期范围以及再次显示同一方案后依然保留;显示另一个方案、**退出**或离开方案模式会清除它们。徽标出现在分组的缩略图上,不会出现在全屏视图中,也不会出现在已确认或已跳过的分组中。助手的返回结果会列出它未保存的路径:`redundant`(已是方案的选择)、`closed`(已确认或已跳过的分组)和 `missing`(不在方案中)。 你已确认、已跳过或正在确认的分组的备注不会被保存,而是列在 `groups_closed` 中;`suggestions_total` 和 `notes_total` 给出标签页当前保留的数量(最多 300 条建议和 100 条备注)。 参见[助手方案模式](VIEWER.md#助手方案模式)。
- **读取你的进度。** 方案模式之外,`ui_get_context.culling` 为 `null`。在方案模式中它返回 `{plan_digest, groups_total, confirmed, pending, changed, untouched, plan_truncated}`:`confirmed` 列出确认已生效的方案分组编号,`pending` 列出你已与方案不同但尚未确认的分组,`untouched` 统计其余分组,`changed` 以 `{type, group_id, number, keep_paths, reject_paths}` 列出每个保留照片与方案不同的分组(当方案本身被限制在分组或照片数量上限、因此只列出部分分组时,`plan_truncated` 为 `true`;过大而无法一次返回的块,无论是被标签页 100 KiB 的上限还是被服务器截断,其列表都会缩短并将 `truncated` 置为 `true`,真实数量保留在 `groups_total`、`confirmed_count`、`pending_count` 和 `changed_count` 中)。切勿重新决定已确认的分组。已确认的 burst 或 similar 分组会离开下一次预览;已确认的 scene 分组不会被记录在任何地方,可能再次被提出,因此请在下一次试运行及其应用中把 `changed` 作为 `keep_paths` / `remove_paths` 传入。`ui_get_context` 还会返回 `culling_defaults`,即 `{profile, strictness}`:`strictness` 在滑块有已保存值时为该值,仅保存了配置时为 `null`(此时采用配置自身的严格程度),两者都未保存时为 100;`auto_cull` 在未给出任何参数时使用已保存的配置和/或严格程度(严格程度优先;配置提供其其他设置,例如每组最少保留数)。`culling_defaults.strictness` 是滑块当前保存的实时值,按浏览器保存(两个标签页共用);显示方案会把滑块移到方案的严格程度,同时给出配置和 `strictness` 的方案会把两者都保存;在方案模式之外拖动滑块会清除已保存的配置(自定义组合),而在方案模式中则保留它。由于在方案显示期间拖动滑块或更改日期范围会重新规划,请在下一次试运行之前重新读取 `ui_get_context`。`culling.scope`(`{album_id, date_from, date_to}`)是方案所对应的时间窗口;`auto_cull` 只从自己的参数读取日期,因此下一次试运行时请把 `culling.scope` 的日期与 `culling.changed` 一起传入(新方案会替换当前显示的方案)。 `culling` 还包含 `suggestions_open`(`[{path, action}]`:仍在等待你点击的标记)、`suggestions_accepted`(你已将其照片置于建议状态的标记)和 `suggestions_total`(标签页中保留的标记);该列表被截断时,`suggestions_open_count` 给出其真实长度。 `suggestions_total` 只统计照片建议,不含分组备注。
- **日期。** 筛选工具(`auto_cull`、`list_culling_groups`、`suggest_culling_profile`)接受 ISO 日期(`2026-06-01`)、ISO 日期时间(`2026-06-01T08:30:00` 或用空格分隔)或 EXIF 形式(`2026:06:01 08:30:00`);仅有日期的 `date_to` 覆盖整天。按天粒度的工具(`library_stats`、`possible_faces`、`cull_report` 的计数和暗房集合均如此)只接受日期,带时间会以 `invalid_input` 拒绝。
- 每行包含相机、镜头、光圈、快门速度、ISO、焦距和 `is_monochrome`。三个搜索工具上的 `fields` 可添加任何其他照片列（图像和嵌入数据除外），例如 `leading_lines_score`；`learned_score` 仅在按其排序时才有值。字节上限截短行数时，结果会增加 `returned`（以及 `next_offset` 或 `suggested_per_page`）。
- `library_stats` 接受 `kind`（默认 `overview`：规模、各类型数量和评分概览）。概览包含 `basis`，说明每个总数的统计口径：`total_photos` 统计在 `date_from`/`date_to` 和类别范围内您可见的照片（未指定时为所有日期和类别），忽略隐藏开关并包含已拒绝的照片，而 `type_counts` 应用隐藏开关并忽略日期和类别过滤器。其他取值均为只读，返回统计页面的数据；过长的列表会在 50 项处截断并带 `truncated: true`：

| kind 取值 | 数据 |
|------|------|
| `score_distribution`、`top_cameras`、`categories`、`gear`、`stats_settings`、`timeline`、`correlations` | 统计页面的各个面板；接受 `date_from`、`date_to` 和 `category`。`correlations` 还接受 `x`、`y`（逗号分隔列表）、`group_by` 和 `min_samples` |
| `category_breakdown`、`category_weights`、`category_correlations`、`category_overlap` | 分类统计（无参数） |
| `timeline_dates`、`timeline_months` | 按日或按月的照片数量；需要 `year`（`timeline_dates` 还接受 `month`） |
| `timeline_years` | 按年的照片数量 |

## 控制已打开的标签页

除数据工具外，服务器始终列出十四个 `ui_*` 工具，它们作用于你在浏览器中打开的 Facet 标签页：切换页面、修改筛选或选择，并读回你看到的内容。它们从不写入照片库数据，因此 `readonly` 令牌就够了。

| 工具 | 作用 |
|------|------|
| `ui_navigate` | 前往某个页面（图库、人物、相册、统计等） |
| `ui_set_gallery_filters` | 把补丁合并到图库的筛选和排序中（`null` 移除某个筛选，`replace: true` 从零开始） |
| `ui_get_gallery_view` | 路由、当前筛选、匹配总数、前若干个可见照片路径以及已选数量；还返回 `album_filter_json`（智能相册会保存的筛选）和 `filters_scopable`（这些筛选是否描述整个视图） |
| `ui_get_context` | 已打开的页面(路由)、图库状态(总数、已加载数量、是否显示固定列表)、已选照片数量,以及此处适用于你的令牌的 `actions`;还有 `focused`(用户所在的照片)、`culling`(助手在 `/culling` 上的方案:已确认、待确认和已更改的分组,以及它所对应的 `scope`)、`culling_defaults`(`{profile, strictness}`:已保存的配置和滑块当前保存的实时严格程度,按浏览器;两者都未给出时 `auto_cull` 同时使用二者)和 `user_activity`(用户做过的操作),并接受 `activity_since`(见下文) |
| `ui_open_photo` | 打开一张照片 |
| `ui_show_photos` | 按此顺序精确显示这些 `paths`(最多 200 个)作为图库列表;无法访问的会在 `missing` 中返回。任何筛选条件的更改都会替换该列表 |
| `ui_select_photos` | 选择明确的 `paths`，或用 `select_view: true` 选择整个筛选视图，模式为 `replace`、`add` 或 `remove` |
| `ui_clear_selection` | 清空选择 |
| `ui_get_selection` | `scope`（`paths` 或 `view`）和 `count`，附带 `paths`；视图范围则附带 `filters` 和 `excluded_paths` |
| `ui_next_page` | 加载图库的下一页 |
| `ui_show_culling_group` | 在暗房中打开某个分组，由 `(type, group_id)` 标识（编辑账户） |
| `ui_show_culling_plan` | 在暗房中打开一个 `auto_cull` 方案(预览中的 `plan_digest` 和 `request`,可选 `focus` 为分组编号),方案的保留照片已预先选中,供你调整并确认(编辑账户)。试运行时 `auto_cull` 会替你调用它。与已显示方案相同的摘要只会移动焦点;不同的摘要会替换方案,若你持有未确认的决定则被拒绝为 `unsaved_decisions`,若照片库自预览以来发生变化则拒绝为 `plan_changed`,若标签页因其他原因无法加载方案则拒绝为 `plan_load_failed` |
| `ui_suggest_culling` | 在 `/culling` 显示方案期间,标记你会保留或剔除的照片(`photos`:`path`、`action`、`reason`,最多 100 项)以及想要评注的分组(`groups`:该分组中任一照片的 `path` 和一条 `note`,最多 50 项);理由或备注最长 200 个字符。你会看到每张照片一个徽标、每个分组一枚标签,不点击徽标就不会有任何改变。多次调用按路径合并,`replace: true` 先丢弃已保留的全部内容,`replace` 配合空列表则全部清除。返回 `{plan_digest, applied, redundant, closed, missing, groups_applied, groups_missing, groups_closed, suggestions_total, notes_total}`;拒绝情形为 `no_plan`(该标签页没有方案)、`too_large`(标签页最多保留 300 条建议和 100 条备注:请使用 `replace`)和 `forbidden_level`(仅限编辑账户)。打开多个标签页时,请传入 `shown_in_tab` 或 `status` 中的 `tab_id` |
| `ui_show_comparison` | 打开成对比较页面，可选指定类别和策略；它只负责打开页面，由您自己选出胜者 |

工作方式：

- 只要你已登录，且 `viewer.mcp.enabled` 与 `viewer.mcp.bridge` 都为 `true`，每个 Facet 标签页都会向 `/api/mcp/bridge` 打开一个同源 WebSocket，并在第一条消息中用你的会话完成认证。桥接默认开启；把 `viewer.mcp.bridge` 设为 `false` 即可关闭，此时 `ui_*` 工具会返回明确的错误。
- `ui_get_context` 读取已打开的页面、图库状态、所选照片数量,以及适用于此页面和该令牌的 `actions`;`available_actions` 由服务器针对你已打开的标签页回答同一问题。超出令牌级别的工具不会列出。
- 工具只能到达令牌所有者的标签页。单密码安装中所有会话是同一个用户；开放安装中每个标签页都属于共享用户 `_anonymous`，包括 edition 登录。
- 每个标签页都带有打开它的会话的级别，令牌只能控制级别不低于其有效级别的标签页：`edition` 令牌绝不会使用仅有查看会话的标签页，而 `readonly` 令牌可以控制 `edition` 标签页。在单密码安装中，令牌还受创建它的会话限制：由仅查看会话创建的令牌只能到达查看级标签页，绝不会到达 `edition` 标签页（此规则之前创建的令牌被限制在其自身级别）。在开放安装中，令牌同样被限制在查看级别：只能到达查看级标签页，绝不会到达 `edition` 标签页，本地编辑标签页除外（见下）。标签页只能被同级或更高级的标签页替换：仅查看会话重用 `edition` 标签页的 `tab_id` 会被以 4409 拒绝，超过每用户标签页上限时最低级别的标签页最先被移除。`status` 只列出该令牌能控制的标签页。 `status` 还会返回 `out_of_reach_tabs`，即此令牌无法驱动的已打开标签页数量。在开放安装上启用 `viewer.trusted_local_editing` 时，握手通过同机边界的标签页以 `edition` 注册，并在该选项关闭后一次 ping 内降为 `readonly`；局域网或被转发的标签页保持 `readonly`。从本机使用的令牌无论创建时是什么级别，都能到达该本地编辑标签页；从另一台机器（局域网）使用的令牌永远无法到达它，并得到 `no_tab`，附带说明非本地请求无法操控本地编辑标签页的消息。
- 打开多个标签页时，使用最近获得焦点的那个，结果中的 `tab` 字段会说明。传入 `tab_id`（由 `status` 列出）可选择其他标签页。
- 标签页会拒绝其账户无权执行的操作（例如非编辑账户访问 `/culling`），工具会返回该拒绝信息。
- 标签页返回的内容不可信：深度、字符串长度和列表长度都有上限，整体还受 `max_bytes` 限制。
- 错误：`no_tab`（没有已连接的标签页，或桥接已关闭）、`tab_timeout`（在 `call_timeout_s` 内无响应）和 `tab_outdated`（已打开的标签页不认识该工具；升级 Facet 后请刷新页面）。
- 桥接先接受 WebSocket，再以关闭码而非 HTTP 状态码拒绝：端点或桥接关闭时为 4404（此后标签页保持断开，直到重新加载页面），`Origin` 缺失或不被允许时为 4403，会话缺失或被拒绝时为 4401。
- 反向代理必须为 `/api/mcp/bridge` 转发 WebSocket 升级；参见[部署](DEPLOYMENT.md)。如果它改写了 `Host` 头，请把公开来源写入 `viewer.mcp.allowed_origins`（例如 `["https://photos.example.com"]`），因为页面的来源必须与主机匹配或在列表中。
- 标签页注册表按进程保存，因此桥接需要单个 worker（默认值）。
- **用户正在做什么。** `ui_get_context` 还会返回 `focused`,即 `{path}`:图库中键盘光标所在的照片、照片页中打开的照片或暗房中的当前照片(否则为 `null`;悬停不算,切换到助手窗口时保留,照片离开列表时清除),以及 `user_activity`,即 `{items, until, truncated}`:用户在标签页中做过的操作(评分、拒绝、收藏、`/culling` 上助手方案的确认和跳过(`cull_confirm`、`cull_skip`:仅在方案模式中记录,于确认生效或跳过倒计时结束之后;手动选片以及由退出触发提交的确认不记录)、标签、相册、导航),最多 50 项、每项最多 20 个路径,保留最新的。它是无状态的:把上一次回答中的 `until` 作为 `activity_since` 传入,只获取更新的内容;不带它的两次调用返回相同的项。助手自己的写入和它自己的 `ui_*` 导航从不列出。该日志存放在标签页内存中,重新加载后丢失。标签页保留最近 500 个操作。

补充说明：

- 当打开的是其他页面时，`ui_set_gallery_filters` 会先跳转到图库，再应用补丁。如果补丁中包含标签页无法操作的筛选条件，整个补丁会被拒绝（`invalid_input`）；这类条件请使用 `search_photos`。 在相册页面上，任何更改都会先回到图库（不只是 `replace: true`），因此相册已保存的筛选不会被覆盖，相册范围也会被放弃。它还接受 `semantic_query`、`semantic_threshold`（0 到 0.5）、`similar_to`、`similarity_mode` 和 `min_similarity`（0 到 1）；`similar_to` 与 `semantic_query` 不能同时使用。
- `ui_get_gallery_view`、`ui_next_page` 以及带 `select_view` 的 `ui_select_photos` 要求当前打开的页面是图库（或相册），否则返回 `no_active_view`；请先调用 `ui_navigate` 前往 `/`。`ui_select_photos` 必须恰好给出 `paths` 与 `select_view` 之一。若界面工具会在用户持有未确认决定时离开 `/culling`，则返回 `unsaved_decisions`；标签页自身拒绝的导航返回 `navigation_refused`；`forbidden_level` 仅表示权限拒绝。
- `no_tab` 也表示没有打开任何 Facet 标签页：请在浏览器中打开 Facet 并登录。**连接助手**对话框中的状态行会显示此标签页是否已连接；`status` 工具会列出已打开的标签页及其 id。
- 标签页的会话被拒绝后会停止重连（请重新登录）；如果您的另一个标签页接管了连接，它会等到您回到该标签页再重连。
- 仅当服务器声明桥接可用（端点已启用且 `viewer.mcp.bridge` 为 true）时，标签页桥接才会连接；桥接关闭时，标签页完全不会连接。
- `ui_set_gallery_filters` 会以 `invalid_input` 拒绝未知的筛选名称，也会拒绝同时给出 `category` 与 `type`、或同时给出 `person` 与 `person_id` 的补丁。它只提供图库能够显示的筛选条件；其他条件请使用 `search_photos`。
- `ui_navigate` 只打开应用自身的静态页面：登录页、共享页、外部 URL 和未知路径会被拒绝（`invalid_input`），仅限编辑的页面会对非编辑会话拒绝。
- 在整个视图被选中的状态下，`ui_select_photos` 的 `remove` 模式会忽略已加载视图之外的路径，并在结果中以 `not_in_view` 列出。

## 实时更新

助手通过写入工具更改照片时,您已打开的 Facet 标签页无需重新加载即可同步。

- **哪些内容会刷新。** 图库原地更新有变化的卡片,保留助手的固定列表,并移除从图库中删除的照片(`delete_photos`)。被 `cull_apply` 移动或移入回收站的照片仍保留其图库记录,因此会留在固定列表中,而隐藏已拒绝照片的视图(默认设置)本来就会隐藏它。无法指明具体照片的写入(见下文)会改为重新加载视图,并在新数据到达前保持当前行和您的选择显示在屏幕上,因此网格不会变空。语义搜索和相似照片视图会刷新已显示的照片,从不移除任何照片,对无法指明具体照片的写入也是如此。照片页面会重新获取该照片(照片从图库中删除时会返回上一页)。暗房(`/culling`)原地更新拒绝、收藏和评分,显示“已拒绝”标记并保留您自己的决定;遇到无法界定范围的更改时,仅在没有任何风险时才重新加载,否则显示一个“重新加载”横幅,直到您重新加载才会消失。
- **每一波只提示一次。** 更改会被合并(400 毫秒尾部防抖,最长 2 秒),只显示一条“助手更改了 N 张照片”的提示。
- **每次助手调用对应一条记录。** 写入多张照片的一次调用在活动面板中只出现一次,标签为助手工具名称的你所用语言译文(没有标签的工具显示原始名称),整次调用的照片合并计数。超过 200 张时,该条记录不列出任何照片,视图会重新加载,且没有 **显示照片** 按钮。应用 `auto_cull` 之后,**显示照片** 会固定它所拒绝的照片(最多 200 张)。
- **哪些写入。** 评分、收藏、拒绝、标签、说明、相册成员、筛选整理、删除、序列与类别的修正、人脸指派、清除垃圾标记以及暗房确认。读取、试运行、被拒绝的写入、创建相册、导出元数据和扫描不会触发。超时的写入(`outcome_unknown`)仍会刷新,因为该写入可能已经生效;此刻仍在运行的写入会在下一次刷新或重新加载时显示。
- **无范围的写入。** 针对 `filters` 视图的写入、包含同组相邻帧的写入、超过 200 张照片的写入,或未指明任何路径的写入,会重新加载视图,而不是刷新指定的卡片。
- **桥接必须开启。** 通过 `/mcp` 进行的写入经由标签页桥接到达您的标签页,因此 `viewer.mcp.bridge` 必须为 `true`。页面自身发起的写入(`POST /api/mcp/call`)由响应驱动(`changed_paths`),即使桥接关闭也会更新。
- **仅限同一进程。** 通知只会到达写入者连接到同一服务器进程的标签页;使用 `viewer.py --workers N` 时可能漏掉某个标签页(桥接需要单个 worker,即默认值)。
- **升级后请重新加载已打开的标签页。** 工具列表已更改,已打开的标签页在重新加载之前会返回 `tab_outdated`。

## 页面内 WebMCP（浏览器智能体）

除 `/mcp` 端点之外，已登录的标签页还会通过 W3C [WebMCP](https://webmachinelearning.github.io/webmcp/) API（`document.modelContext`）向运行在浏览器内部的智能体提供同一组 `ui_*` 工具。因此浏览器原生的助手看到的正是上文列出的工具，在您正在查看的标签页中执行，并且无需令牌。

- **仅限安全上下文。** Facet 只在 HTTPS 或 `localhost` 下注册这些工具。在普通 HTTP 下不会提供页面内的工具；上文基于令牌的连接仍可使用。
- 当 `viewer.mcp.enabled` 为 true 且您已登录时注册，退出登录时移除。
- 该对象是 `document.modelContext`（不提供已弃用的 `navigator.modelContext` 别名）。它是一个 polyfill，仅在浏览器没有原生实现时安装，且无法卸载：登录前它可能已存在但不含任何 Facet 工具，退出登录后它仍保留，工具列表为空。
- 这些工具的功能与上表相同，并受同一账户级别的限制。
- 浏览器智能体通过 `ui_get_context` 读取同一份 `actions` 列表。
- **页面内的图库工具。** 标签页还提供服务器自身的工具（搜索、评分、标签、相册、暗房、报告），通过 `GET /api/mcp/inpage_tools`（列表，含每个工具的 schema、`required_level` 以及会话当前的 `level`）和 `POST /api/mcp/call`（`{tool, arguments, selection_snapshot?}`）。它们以你已登录的会话身份，经与 `/mcp` 相同的封装层运行，因此级别、预览、`confirm` 值和速率限制的行为完全一致。工具失败时返回正常的 `ok: false` 信封（HTTP 200）；调用还会报告 `changed`（已写入的照片数）。
- **级别。** 级别取你登录时的级别与你当前角色中较低者，每次调用都会重新读取：被降级的账户立即失去写入权限，被删除的账户会被拒绝（401）。低于工具的最低要求时，答复为 `forbidden_level`（"This session's level is readonly; set_rating needs edition: unlock edition in Facet"）。在单密码安装中，执行写入的会话必须已解锁编辑权限。
- **谁可以调用。** 仅限已登录的人。智能体自己的 `/mcp` 令牌在这些路由上会被拒绝（403），外部 `Origin` 也一样；仅有 cookie 永远不能认证。每次调用都带有 `X-Facet-Agent-Session` 头（1 到 64 个字母、数字、`_` 或 `-`；缺失或格式错误则返回 400）。它用来区分标签页：为某个标签页签发的 `confirm` 值会被拒绝给另一个标签页；该值由页面自己选择，所以它只起区分作用，不起认证作用。
- **不包含的内容。** 图像工具（`get_thumbnail`、`contact_sheet`）和 `available_actions`（请用 `ui_get_context`）。工具的 `show` 参数始终关闭，因为调用者就是标签页本身，`tab_id` 会被拒绝。`status` 只报告服务器与界面契约的版本。`target: "selection"` 使用页面发送的 `selection_snapshot`（即 `ui_get_selection` 返回的内容），并且对 `target: "view"` 的 `create_album`，还包含 `ui_get_gallery_view` 返回的 `album_filter_json` 与 `filters_scopable`，缺少它则为 `invalid_input`。破坏性操作仍遵循 `viewer.mcp.allow_destructive`。
- **品味。** 与任何助手的写入一样，从页面发起的工具调用从不记录比较，也从不触发重新训练。
- **开关。** `viewer.mcp.inpage_tools`（默认 `true`）会关闭这两个路由（404），并将 `/api/auth/status` 中的 `features.mcp_inpage` 置为假；`viewer.mcp.enabled: false` 同样会关闭它们。

## 修改内容

写入工具与只读工具列在同一个 `/mcp` 列表中。每个工具都经由查看器自己的 `/api` 路由，因此路由的保护仍然生效，并且每次调用都计入 `write_rate_per_min` 预算。“级别”是可以调用该工具的最低有效级别（参见[权限级别](#权限级别)）。

| 工具 | 级别 | 作用 | 上限 |
|------|------|------|------|
| `set_rating` | `user` | 设置照片的星级评分（0-5） | 50 个路径 |
| `set_favorite` | `user` | 收藏或取消收藏照片（收藏会清除淘汰状态） | 50 个路径 |
| `set_rejected` | `user` | 淘汰或取消淘汰照片（淘汰会清除评分和收藏） | 50 个路径 |
| `batch_set_rating` | `edition` | 设置大量照片的评分 | 1000 个路径，或 `filters` |
| `batch_set_favorite` | `edition` | 把大量照片标为收藏 | 1000 个路径，或 `filters` |
| `batch_set_rejected` | `edition` | 淘汰大量照片 | 1000 个路径，或 `filters` |
| `add_tags` | `edition` | 添加手动标签（与 AI 标签分开保存） | 10 个标签；1000 个路径，或 `filters` |
| `remove_tags` | `edition` | 移除手动标签 | 10 个标签；1000 个路径，或 `filters` |
| `create_album` | `edition` | 创建相册（不幂等：调用两次会创建两个相册）：可为空，也可由 `filters` / `target: "view"` 创建跟随这些筛选条件的智能相册，或由 `paths` / `target: "selection"` 创建并在同一次调用中填充的固定相册（`added`、`skipped`）。智能相册使用查看器自身的隐藏开关，在 `list_albums` 中显示 0 张照片 | |
| `album_add_photos` | `edition` | 向相册添加照片（已有的会被忽略） | 1000 个路径 |
| `album_remove_photos` | `edition` | 从相册移除照片；照片本身不受影响 | 1000 个路径 |
| `assign_faces` | `edition` | 将人脸移到某个人物;属于其他人物的人脸保持不变,除非设置 `allow_reassign`,结果会列出被跳过的内容 | 50 个人脸 id |
| `set_caption` | `edition` | 设置照片的说明文字(集合语义;未变化的说明文字返回 `already`) | 1 张照片,2000 个字符 |
| `export_metadata` | `edition` | 在文件旁写入 XMP 附属文件 | 100 个路径,或 `filters`,或 `target` |
| `junk_list` | `readonly` | 列出废片清理的候选，可只列某一种 `kind` | 每页 100 条 |
| `junk_reject` | `edition` | 淘汰废片清理的候选（与 `batch_set_rejected` 相同） | 1000 个路径 |
| `junk_clear` | `edition` | 保留候选：把它们标为已评估且无问题，使其离开队列 | 50 个路径 |
| `cull_apply` | `edition` | 复制保留的照片，或移动、移入回收站被淘汰的照片（[先预览再确认](#破坏性操作先预览再确认)） | 10000 个路径，或 `filters` |
| `delete_photos` | `edition` | 把文件移入回收站并删除其照片库记录（[先预览再确认](#破坏性操作先预览再确认)） | 1000 个路径 |

- **在单密码安装上，`user` 工具需要编辑令牌**，因为该模式没有中间级别（参见[权限级别](#权限级别)）。
- **设置语义。** 逐张照片的工具先读取当前状态，只写入有差异的部分，因此重复调用是无害的；每个路径会报告 `changed` 或 `already`。它们一次处理一个路径，遇到第一个 `library_busy`、`outcome_unknown` 或 `forbidden_level` 就停止，并报告 `affected`、每个路径的 `results` 和 `not_attempted`。批量工具设置的是同样的状态。
- **选择照片。** 批量、标签和 `cull_apply` 工具接受 `paths` 或 `filters`（`search_photos` 的筛选对象）二者之一，外加可选的 `exclude` 列表。`filters` 目标必须带有 `expected_count`，即应用 `exclude` 之前筛选条件的匹配数（`search_photos` 的 `total`）。Facet 会先重新统计，数字不一致时不写入任何内容（`invalid_input`，附带 `actual_count`）。 查看器的默认隐藏开关(包括已拒绝的照片)对 `filters` 的应用方式与 `search_photos` 完全相同,因此其 `total` 就是 `expected_count`。所以已拒绝的照片会从 `filters` 目标中隐藏:对于 `move_rejects` 和 `trash_rejects`,请把 `show_rejected`(或 `hide_rejected: false`)同时传给 `search_photos` 和 `cull_apply`;`copy_keeps` 无需额外设置。
- **状态归谁。** 评分、收藏和淘汰都属于令牌所有者本人。
- **被跳过的文件。** 当 `cull_apply` 或 `delete_photos` 返回非空的 `skipped` 列表时，结果还会带有 `skipped_reason`：这些库路径在磁盘上没有可读文件（缺失、已移动或不在扫描目录内），对它们未执行任何操作。
- **用户所选的照片。** 在工具接受 `paths` 的地方,`target: "selection"` 改用已打开标签页的选择(`tab_id` 选择标签页)。预览与确认之间选择发生变化时返回 `invalid_input` 并带 `selection_changed`,选择过大而无法放入标签页回复时返回 `too_large`,`delete_photos` 在确认时会重新读取选择。
- **说明文字与导出。** `set_caption` 只保存文本。说明文字不会重新嵌入,因此语义说明搜索在重新嵌入之前仍会匹配旧文本;增量导出到查看器数据库时,若来源的说明为空则保留已有说明,所以已清除的说明可能随之后的导出或扫描重新出现。`export_metadata` 最多等待 180 秒,报告 `written`、`skipped` 和 `errors`,第一条错误文本在 `first_error` 中,并且在 exiftool 为 13.23 至 13.27 时拒绝写入。
- **人脸。** `assign_faces` 会跳过并列出:不存在的、已在该人物下的、属于其他人物的(除非 `allow_reassign`)、使用其他嵌入模型的或属于已隐藏人物的人脸;`assigned_count` 是实际移动的数量。

### 破坏性操作：先预览再确认

`cull_apply`（`copy_keeps`、`move_rejects`、`trash_rejects`）和 `delete_photos` 带有 `destructiveHint` 标记，除非以 `dry_run: false` 调用，否则按试运行执行。

1. 试运行不改动任何内容，并列出它将要复制、移动或移入回收站的文件（过长的列表会截断到 `max_rows`，并附带 `<key>_count`）。对于 `move_rejects`、`trash_rejects` 和 `delete_photos`，它还会返回一个 `confirm` 值，有效期为 `confirm_expires_in_s`（5 分钟），且只能使用一次。
2. 真正的调用（`dry_run: false`）必须传入该 `confirm`。Facet 会重新解析文件集合和选项，并与该值签发时的集合比对。若有任何变化，该值作废，调用返回 `confirmation_required`：请重新试运行。
3. `copy_keeps` 不需要 `confirm`：它只写入副本。默认仍先试运行。

`confirm` 值绑定到令牌、操作以及确切的文件集合和选项。它保存在单个进程的内存中，因此重启会丢弃所有待处理的值。

**推荐做法：** 在调用 `dry_run: false` 之前，务必把试运行摘要（数量和文件列表）展示给用户并获得明确同意。切勿擅自确认。

- `move_rejects` 和 `trash_rejects` 只作用于所有者已淘汰的照片；其余的会报告为 `excluded_by_state`。随附的 RAW 和 `.xmp` 文件（`include_companions`）以及包围曝光或全景组中的其他帧（`include_sequence_siblings`）不会被触及，除非你主动开启。
- `delete_photos` 把文件送入系统回收站并**删除其照片库记录**：评分、标签和评级无法恢复，即使文件本身可以恢复。
- **前提条件。** `trash_rejects` 和 `delete_photos` 需要将 `viewer.cull.allow_trash` 设为 `true`（默认 `false`；否则调用会被拒绝）。`copy_keeps` 和 `move_rejects` 的 `target_dir` 必须位于允许的导出位置之下：`viewer.export.allowed_target_dirs` 加上你的扫描目录（参见[导出与选片目标位置](CONFIGURATION.md#导出与选片目标位置)）。

## 修正与参考数据

- **修正**（`edition`）。`override_sequence`（`kind`：`panorama`、`bracket`、`hdr_panorama` 或 `suppress`；除 `suppress` 外至少 2 个路径）和 `clear_sequence_override` 记录一项在下一次检测遍历时生效的修正（结果报告 `pending`）。`override_category` 和 `clear_category_override` 设置或清除持久的类别，它在重新扫描后依然保留并保持评分上下文。
- **比较画面**（`readonly`）。`group_compare` 比较一个选片分组中的画面（最多 12 个路径），`by: "faces"`（每帧：人脸数、眨眼、最低睁眼度、最佳笑容、`best_path_by_eyes`）或 `by: "subjects"`（主体清晰度与突出度、`sharpest_path`）。这只是建议，不是决定。`cull_report` 用一次调用汇总一个范围：总数、保留、淘汰、收藏、已评分、未审阅、隐藏开关会隐藏的内容、垃圾、低分、最佳照片，以及（使用 edition 令牌时）暗房的前几个分组。各原因相互重叠。 它包含 `basis`,说明每个计数遵循哪些过滤器(隐藏开关不适用于这些计数)。
- **品味。** `comparison_status`（`edition`）报告你做了多少次成对比较以及它们对照片库的覆盖程度。没有任何工具能提交、编辑或删除比较：每一对的答案是你自己的点击。助手所做的写入（评分、淘汰、暗房确认、`auto_cull`）从不记录比较，也从不触发自动重新训练；你本人在图库中做同样的操作仍会如此。 助手写入的评分、收藏和淘汰，在个人排序器依据你的评分重建时同样不会进入训练对；一旦你自己给该照片评分，它们就会重新计入。这份记录保存在单独的表中，永不导出。
- **扫描。** `start_scan` 和 `scan_status`（`edition`）启动并跟踪对已配置目录的扫描。仅当 `viewer.features.show_scan_button` 开启且安装已锁定（多用户模式下为超级管理员密钥）时才会列出；在 `viewer.trusted_local_editing` 下，本机的完全编辑令牌无需 `show_scan_button` 也会列出。扫描是追加式的，并在另一项任务运行时被拒绝（`conflict`）。与 Immich 的同步仍通过命令行进行。
- **资源。** 除工具外，服务器还列出五个只读的 `facet://` 资源：`facet://categories`、`facet://tags`、`facet://persons`、`facet://filters`（每个搜索筛选条件及其取值范围，加上指标范围）和 `facet://scoring-contexts`。每个资源按密钥所有者看到的照片库读取，上限 200 行和 32 KiB（`truncated` 会标明）；另有第六个资源 `facet://scoring-weights`（每个类别的非零权重），仅向 `edition` 密钥提供。
- **选择列出的内容。** `viewer.mcp.tool_profile` 为 `full`（默认）或 `core`：`core` 只列出面向小模型的 11 个工具（`status`, `search_photos`, `semantic_search`, `get_photo`, `filter_options`, `library_stats`, `ui_show_photos`, `set_rating`, `set_favorite`, `set_rejected`, `album_add_photos`）。它只改变列表，不改变密钥可调用的内容。`viewer.mcp.allow_destructive`（默认 `false`）控制 `delete_photos`（关闭时不列出）、`cull_apply` 的 `move_rejects` 与 `trash_rejects` 操作，以及带 `allow_reassign` 的 `assign_faces`；被拒绝的调用返回 `feature_disabled`。令牌级别无法调用的工具同样不会列出。
- **另外两个错误代码。** `feature_disabled`：该路由被某个配置键关闭，消息中会指出该键。`conflict`：照片库正忙于与此冲突的任务（例如已有扫描在运行）。

## 评分与权重

读取评分权重并进行试算。这里的任何操作都不会改变评分或配置。

- **解释评分**（`readonly`）。`explain_score`（`path`，或用 `target: "selection"` 指定恰好一张已选照片；`top_n` 为 1 到 12，默认 5）说明一张照片为何得到该评分：它所属的类别、以及为何没有被更高优先级的类别选中，已存储的综合分，以 `{metric_key, value, weight_percent, contribution}` 表示的主要指标，其余指标的数量与总和，优势、弱点与扣分项。分析基于规则且只读（从不运行 VLM）。`weight_percent` 是计算实际使用的有效权重，可能与配置的 `*_percent` 不同（`quality` 会并入 `aesthetic`，本安装未运行的指标会被重新归一化）。它需要 `viewer.features.show_critique`（默认开启）；关闭时该工具不会被列出，`status` 会在 `hidden_tools.disabled` 下指出它。
- **读取权重**（`edition`）。`category_weights` 返回某个类别的非零权重、修饰项、筛选条件与优先级，或返回每个类别的非零权重与加分。资源 `facet://scoring-weights` 提供同样的列表。对于单个类别，它还返回 `configured_keys`，即该类别配置中实际存在的 `*_percent` 键（包括显式的零）。
- **预览更改**（`edition`）。`preview_weights(category, weights | deltas, sample)` 是近似预览：它用当前权重和建议权重（均按计算所用的方式归一化）对该类别最多 `sample` 张照片重新打分（默认 30，最多 100），先报告排名变化，再报告平均偏移、`warnings` 和一次性的 `preview_digest`（有效期 5 分钟，保存在单个进程的内存中）。请提供 `weights`（合并到当前值之上的部分映射）或 `deltas`（带符号的百分点）。它不存储任何内容，结果带有 `basis: "approximate"`：没有百分位快照、没有扣分，评分上限为 10。只执行服务器自身的规则（每个权重为 0 到 100）；总和超出 95 到 105（配置加载器会重新缩放）以及未知键（按原样存储，并在带校验的加载时被丢弃）都以 `warnings` 返回，而不是拒绝。助手无法编辑 `bonus` 和修饰项。照片超过 100 张的类别只从按综合分排序的最好 100 张和最差 100 张中抽样（`sample_scope`）。digest 不代表同意：请先向用户展示建议、偏移和 `basis_note`。它仅使用已存储的指标，并拒绝所有权重均为 0 的方案（`all_weights_zero`）。

## Prompts

服务器还提供五个现成的提示词,由 `prompts/list` 列出并按令牌级别过滤。提示词只会提到令牌可调用的工具,破坏性工具只出现在试运行与确认之后。每次调用都计入读取速率限制,并按名称记录审计,从不记录其参数。

| 提示词 | 参数 | 它要求助手做什么 |
|--------|------|------------------|
| `find_photo` | `description` | 根据描述找到一张照片并显示 |
| `cull_shoot` | `scope_hint` | 检查一次拍摄,建议拒绝哪些,并在你决定后用 `confirm_culling_groups` 记录你的决定;移动或移入回收站只在试运行并经你确认之后进行 |
| `build_album` | `theme`, `album_name` | 把匹配的照片收集到新相册 |
| `tag_people` | `person` | 找到与某人相似的人脸并分配你确认的那些 |
| `teach_taste` | `category` | 在你的标签页中打开成对比较页面并统计你已做的比较次数；每一对的答案始终是你自己的点击 |

## 暗房（选片分组）

暗房工具对应 `/culling` 页面。它们全部需要 `edition` 级别，包括只做列表的那些。

| 工具 | 作用 |
|------|------|
| `list_culling_groups` | 列出分组（`burst`、`similar`、`scene`、`bracket`、`panorama`、`hdr_panorama`）及其照片和分数，可排序，并可按相册或日期范围限定 |
| `culling_profiles` | 按题材划分的选片预设以及默认预设 |
| `suggest_culling_profile` | 指出适合某个相册或拍摄时间段的预设 |
| `keeper_hints` | 逐张照片的“这组连拍中有更好的一张”提示，最多 100 个路径（未训练保留者排序头时为空） |
| `auto_cull` | 在保留预算下对某个范围自动筛选:逐页预览方案,再用 `confirm` 值应用 |
| `confirm_culling_groups` | 确认最多 20 个分组：保留其 `keep_paths`，淘汰 `paths` 中的其余照片 |

- **分组由 `(type, group_id)` 这一对标识**，绝不能只用 `group_id`：相似分组的 id 在与连拍合并时会被偏移。
- **默认的 `group_by: "all"` 只返回连拍和相似分组。** 如需 `scene`、`bracket`、`panorama` 或 `hdr_panorama`，请明确指定。
- **页面通过缩短每个分组的 `photos` 列表来适应 `max_bytes`，绝不会丢弃分组。** `photo_count` 仍是真实大小，`photos_truncated` 标记列表被截断的分组，`has_more` 表示后面是否还有一页。
- **包围曝光、全景和 HDR 全景整组保留。** 在 `confirm_culling_groups` 中，这些类型的 `keep_paths` 必须等于 `paths`（否则 `invalid_input`），`auto_cull` 也从不拆分它们。
- **空的 `keep_paths` 会淘汰该分组的每一帧。** 此时第一次调用返回 `confirmation_required` 并附带一个 `confirm` 值；先展示给用户，再带上该值重复调用。若批量调用在 `forbidden_level`、`library_busy` 或 `rate_limited` 处停止，会报告已完成的分组。
- **`auto_cull` 默认只预览**,返回每组的保留与拒绝划分,以及一个 `confirm` 值(仅在还有内容待拒绝时)。每次调用都会规划整个范围,并按完整分组分页返回(路由按 200 张照片分页,但单个更大的分组会独占一页,工具为适应结果大小可能返回更少的分组):用上一次的 `next_cursor` 作为 `cursor`、并用 cursor 为 0 那一页的 `plan_digest` 作为 `plan_digest`(`cursor` > 0 时必填)重复调用,直到 `next_cursor` 为 `null`。自第一页以来已变化的方案会以 `confirmation_required` 拒绝:请从 cursor 0 重新开始。每一行带有全方案范围的 `number`,`kept` 和 `rejected` 涵盖完整方案。整个日期范围请在一次调用中筛选,不要按月拆分。
- **一个 `confirm` 覆盖完整方案**(有效期 300 秒,仅可使用一次)。应用时会重新计算方案,若自预览以来已变化,则以 `confirmation_required` 拒绝。与您在图库中进行的同样筛选不同,助手做出的拒绝从不进入个人排序器。`confirm` 仅在 cursor 为 0 的那一页签发。应用只返回计数(`groups_processed`、`kept`、`rejected`、`highlights_added`)。
- **覆盖。** `keep_paths` 和 `remove_paths`(各最多 1000 个)覆盖方案中的单帧。在签发 `confirm` 的试运行和应用时传入相同的覆盖。不在方案中的路径会被忽略,并以 `ignored_overrides` 报告(前 20 个,附 `ignored_overrides_count`)。移除方案在包围曝光、全景或 HDR 全景组中保留的帧、使某个分组没有保留照片,或把同一路径同时列入两个列表,都会被拒绝为 `invalid_input`,并指明相关路径或分组;移除方案本来就剔除的帧则不起作用。成组规则适用于完全由单一序列类型构成的分组:把普通帧与序列帧混合的分组不会整体保留,所以其中的帧可以像任何连拍一样被覆盖。
- **应用不会读回用户的调整。** 应用从不读取标签页。要尊重用户对方案所做的更改,请读取 `ui_get_context.culling.changed`,并把这些分组的 `keep_paths` / `reject_paths` 作为 `keep_paths` / `remove_paths` 传给下一次试运行及其应用(两次的列表必须相同)。在标签页中已确认的分组会离开方案:方案摘要随之改变,因此待处理的 `confirm` 会被拒绝为 `confirmation_required`,你需要重新预览;新的预览不再包含已确认的分组,你也绝不要重新决定它们。
- **如果用户在预览与应用之间改动了内容。** 应用会与预览比对。用户自预览以来更改了评分、收藏或拒绝状态的照片会被排除,并以 `skipped_user_changed` 报告(前 50 个路径,附 `skipped_user_changed_count`);没有保留照片的分组会被整体跳过,并计入 `skipped_user_changed_groups`。逐照片的排除仅在既未给出 `keep_paths` 也未给出 `remove_paths` 时适用;给出显式列表时,应用会重新运行试运行,方案的任何变化(包括手动拒绝)都会被拒绝。任何人在预览与应用之间写入的评分、收藏或拒绝(包括助手自己的写入)都算作更改。无法由这些照片解释的方案变化仍会被拒绝为 `confirmation_required`。当服务器不再保存该预览(超过 15 分钟、被淘汰,或由另一进程持有)时,答复会给出 `state_guard: "unavailable"`,并适用全有或全无的拒绝。该保护只覆盖助手的请求;命令行 `--auto-cull` 不变。该保护最多记住所有页面合计 12000 张照片的方案;更大的方案不会被记住,预览会给出 `state_guard: "unavailable"`,并适用全有或全无的拒绝。
- **`scope_dependent_kinds`** 列出成员取决于日期范围或候选池的分组类型(`similar`、`scene`,开启 `trim_brackets` 时还有 `bracket`),并附说明:请在一次调用中筛选整个范围。连拍和全景不随范围变化,包围曝光在 `trim_brackets` 关闭时也不随范围变化。
- **`show`**(默认 `true`,可配合 `tab_id`)。试运行时,方案通过 `ui_show_culling_plan` 在用户的 `/culling` 页面中打开(见上文 `/culling` 上的方案模式),结果带有 `shown_in_tab`:`{"applied": true, ...}` 或 `{"applied": false, "reason"}`,其中包含显示失败的各种原因,以及方案特有的 `unsaved_decisions`(用户在页面上持有未确认的决定)、`plan_changed`(照片库自预览以来发生变化)和 `too_large`(覆盖过大,无法发送到标签页)。因 `plan_changed` 以外的原因而加载失败的方案会报告为 `plan_load_failed`。只有第一页(`cursor` 为 0)会加载方案;`cursor` > 0 的页面只会把标签页的焦点移到该页的第一个分组。显示失败不会使调用失败。应用从不显示。应用的实时更新(以及在页面内,`/api/mcp/call` 响应的 `show_paths`)携带它拒绝的照片,最多 200 张,以便活动条目的**显示照片**可以固定它们;工具结果本身仍只有计数。没有拒绝任何照片的应用不提供**显示照片**,试运行也不发出实时更新。
- **取自标签页的设置。** 既未给出 `strictness` 也未给出 `profile` 时,`auto_cull` 使用已打开标签页的 `/culling` 页面起始所用的设置:严格程度滑块的已保存值(从未拖动过时:已保存配置自身的严格程度,无配置则为 100),若设置了此浏览器中保存的选片配置,则一并使用:配置提供其其他设置(例如每组最少保留数),而滑块的严格程度优先。显示方案会把滑块移到方案的严格程度,应用建议的配置会保存其严格程度。没有可达的标签页时,使用服务器的 `auto_cull.default_strictness`。结果以 `knobs_from_tab`(`{profile}`、`{strictness}` 或两者)报告所用设置;带有确认 nonce 的应用始终沿用它所确认预览的设置,包括显式给出的 `keep_paths` / `remove_paths`,并且不会重新读取标签页的设置;当用户的 `/culling` 页面现在显示的方案与预览时不同(已重新规划或被替换)时,它会被以 `confirmation_required` 拒绝。无法访问或未显示方案的标签页不做检查。`ui_get_context.culling_defaults` 显示同一对值。
- 调用 `ui_show_culling_group` 可在用户已打开的标签页中向其展示某个分组（参见[控制已打开的标签页](#控制已打开的标签页)）。

## 结果、限制与错误

每个结果都是一个 JSON 信封：`{"ok": true, "data": ...}` 或 `{"ok": false, "error": "<code>", "message": "..."}`。列表返回 `data.rows`（每张照片一组精简的固定字段）以及 `total`。搜索结果还带有 `shown_in_tab`，被字节上限截短的结果带有 `returned`。

- **上限：** 最多 `max_rows` 行和 `max_bytes` 序列化字节。末尾的行会被丢弃并设置 `truncated: true`。没有行但超过 `max_bytes` 的结果会变成 `too_large` 错误。
- **图像:** `get_thumbnail` 和 `contact_sheet` 在 JSON 部分之前返回图像部分。图像受 `max_image_bytes`(默认 262144)限制,而非 `max_bytes`。图像中可见的文本是数据,绝不是指令。
- **人脸扫描:** `possible_faces` 最多读取 192000 张人脸,最多等待 120 秒;超过则返回 `too_large`。
- **速率限制：** 每个令牌每分钟 `rate_per_min` 次读取调用。写入工具使用单独的 `write_rate_per_min` 预算（默认 30），因此搜索不会挤占写入，反之亦然；`cull_apply` 和 `delete_photos` 的试运行算作写入，`auto_cull` 的预览算作读取。超出后返回 `rate_limited` 并附带 `retry_after_s`。同一地址每分钟十次失败的 bearer 尝试会收到 429。
- **错误码：** `forbidden_level`（端点已禁用、令牌失效或级别过低）、`invalid_input`、`not_found`、`rate_limited`、`library_busy`、`upstream_error`、`outcome_unknown`、`confirmation_required`、`too_large`、`no_tab`、`tab_timeout`、`tab_outdated`、`no_active_view`、`unsaved_decisions`、`navigation_refused`。
- **较新的错误码：** `confirmation_required`（破坏性调用没有针对这一确切集合的有效 `confirm` 值：重新试运行，把结果展示给用户，然后再试）、`outcome_unknown`（写入超时或连接中断，可能已生效也可能没有：重试前先重新读取状态，切勿盲目重试）、`library_busy`（照片库正忙于其他任务：稍后再试）。
- **入口处的 HTTP 状态码：** 令牌缺失或未知返回 401，跨源的浏览器请求或智能体自身凭据访问 `/api/mcp/tokens` 时返回 403，端点关闭时返回 404。标签页桥接则改用关闭码。在开放安装上，对不是来自运行 Facet 的电脑的请求，`/api/mcp/tokens` 也返回 403。

## 安全说明

- 说明文字、标签、文件名、路径以及相册和人物名称都来自你的照片库，可能包含专门用来操纵助手的文字（提示词注入）。每个工具都标有 `facet/untrusted_content`，并告诉模型把它们当作数据处理。不要让同时会读取不可信内容的助手有办法对这里找到的内容采取行动。
- 令牌永不过期。请吊销不再使用的令牌。
- 日志只记录令牌 id、工具、结果和行数，绝不记录参数或令牌本身。

## 已知限制

- 在开放安装（无密码）上，共享的 `_anonymous` 令牌只能在运行 Facet 的电脑上创建、列出和吊销（设置了 `viewer.edition_password` 时，也可在编辑会话中进行）；其他任何请求都会得到 403，因此网络上的其他设备无法占满 20 个令牌的上限。`/mcp`、页内工具和标签页桥接仍可被任何能访问查看器的人以同一个匿名主体访问：在网络上启用该端点之前请先设置密码。标签页桥接会放大这一风险：非浏览器客户端可以发送伪造的 `Origin` 和空令牌，注册一个处于焦点的 `_anonymous` 标签页，用任意数据应答 `ui_*` 调用，并通过 8 个标签页的上限挤掉真实的标签页。启用 `viewer.trusted_local_editing` 时，本地进程还可以注册一个伪造的 `edition` 标签页（它能在 WebSocket 上伪造 `Host` 和 `Origin`），但它本来就能充当浏览器；局域网客户端做不到，因为要求对端为环回地址。
- 速率限制和认证失败计数器保存在各进程内存中；使用 `viewer.py --workers N` 时每个 worker 各自计数。
- 标签页注册表保存在单个进程的内存中。依赖 `ui_*` 工具时请使用单个 worker（`viewer.py --workers 1`，默认值）；有多个 worker 时，调用可能落到不认识你标签页的进程并返回 `no_tab`。
- 每位用户最多可同时连接 8 个标签页；打开第 9 个会关闭最旧的一个。
- 标签页不会向外部助手推送任何内容:助手只能通过调用 `ui_get_context` 了解方案进度和用户活动。`auto_cull` 的应用不会读取标签页。
- `auto_cull` 的状态保护为每个用户保留 8 个方案、15 分钟;工具的预览记忆与之分开,持续 300 秒,所有用户共计 64 条。两者都存放在单个进程的内存中。使用多个 worker 时,应用可能落到不持有它们的进程上;此时回答会给出 `state_guard: "unavailable"`。
