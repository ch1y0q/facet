# AI 智能体（MCP）

> 🌐 [English](../AGENTS.md) · [Français](../fr/AGENTS.md) · [Deutsch](../de/AGENTS.md) · [Italiano](../it/AGENTS.md) · [Español](../es/AGENTS.md) · [Português](../pt/AGENTS.md) · **简体中文**

Facet 可以充当 [Model Context Protocol](https://modelcontextprotocol.io/)（MCP）服务器，让 Claude Code 等 AI 助手使用与图库相同的筛选条件搜索和查看你的照片库。它提供九个不会改动照片库的只读工具，以及九个 `ui_*` 工具：它们操作你已经打开的浏览器标签页（页面、筛选条件、选择），从不写入照片库数据。获得授权的令牌还可以[修改内容](#修改内容)（评分、标记、标签、相册、选片和删除）并操作[暗房](#暗房选片分组)。

## 启用

该端点**默认关闭**。在 `scoring_config.json` 中把 `viewer.mcp.enabled` 设为 `true`（参见 [智能体端点（MCP）](CONFIGURATION.md#智能体端点mcp)），然后重启查看器或重新加载配置。关闭期间，`/mcp` 和所有 `/api/mcp/*` 路由都返回 404。 没有 `viewer.password` 时，即使设置了 `viewer.edition_password`，该安装也视为开放安装，其令牌只能是 `readonly`。

端点是查看器自身端口上的 `POST /mcp`：Streamable HTTP、无状态、纯 JSON 响应。`GET` 返回 405。只有标签页桥接 `/api/mcp/bridge` 是 WebSocket，参见[控制已打开的标签页](#控制已打开的标签页)。

## 创建令牌

最简单的方式是在浏览器中操作。启用 `viewer.mcp.enabled` 后，打开账户菜单并选择**连接助手**。在**创建令牌**下输入**名称**，并选择**助手可执行的操作**：**仅读取和操作界面**；若当前会话具备相应级别，还可选择**代表我操作**或**完全编辑**（令牌的级别不能高于创建它的会话）。点击**创建令牌**：令牌只会在**您的新令牌**下显示一次，请立即复制。**访问令牌**列出您的令牌及其最近使用时间，并可撤销其中一个。**添加到 Claude Code**给出可直接粘贴的 Claude Code 命令（见下文），**此标签页**则说明此标签页是否已连接、能否被助手操控。 级别列表仅限服务器会授予的范围：开放安装只提供**仅读取和操作界面**，**代表我操作**仅出现在多用户安装中，**完全编辑**仅在编辑会话中提供。创建后，对话框会说明实际授予的级别（“已授予的权限：{level}”）。

通过脚本创建（curl）：

助手使用以 `fct_` 开头的个人令牌进行认证。用一个已认证的请求创建它（令牌**只返回一次**；Facet 只保存它的 SHA-256 哈希）：

```bash
TOKEN=$(curl -s -X POST http://localhost:5000/api/auth/login -H 'Content-Type: application/json' -d '{"password": "YOUR_VIEWER_PASSWORD"}' | jq -r .access_token)
curl -s -X POST http://localhost:5000/api/mcp/tokens -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"name": "claude-code", "level": "readonly"}'
```

响应的 `token` 字段包含明文令牌。`GET /api/mcp/tokens` 列出你的令牌（绝不包含密钥本身），`DELETE /api/mcp/tokens/{id}` 吊销其中一个。超级管理员可以用 `?all=1` 列出所有所有者的令牌并吊销任意一个。每位所有者最多持有 20 个有效令牌（超出返回 412）。这些路由会以 403 拒绝智能体自己的凭据，因此助手永远无法创建、列出或吊销令牌。

## 连接 Claude Code

```bash
claude mcp add --transport http facet http://localhost:5000/mcp --header "Authorization: Bearer fct_YOUR_TOKEN"
```

之后工具会以 `mcp__facet__search_photos` 等名称出现。只要查看器可以从你自己的机器之外访问，就请使用 HTTPS，因为每次调用令牌都会放在请求头里传输。

## 权限级别

令牌创建时被授予一个级别：`readonly`、`user` 或 `edition`。**有效**级别在每次调用时重新计算，取令牌授予级别与其所有者当前级别中较低的一个：

- 单密码安装：`user` 在创建时被限制为 `readonly`，因为该模式没有中间级别。`edition` 令牌需要编辑会话，且只在编辑密码未变更期间有效。
- 多用户安装：之后被降级的用户的 `edition` 令牌会降为 `user`；升级绝不会让令牌超过其授予级别。
- 开放安装（未设置 `viewer.password`，即使设置了 `viewer.edition_password`）：令牌始终为 `readonly`，并归属于共享所有者 `_anonymous`。
- 单密码安装没有 `user` 级别：有效级别只有 `edition` 或 `readonly`，因此[修改内容](#修改内容)中标为 `user` 的工具在那里同样需要 `edition` 令牌。 用较低级别的令牌调用 `user` 工具时，返回 `forbidden_level` 并说明需要 `edition`。
- 每个工具都有自己的最低级别，在读取或写入任何内容之前检查；级别更低的令牌会收到 `forbidden_level`。

所有者的凭据一旦变化，令牌会自动失效：单密码模式下是查看器或编辑密码，多用户模式下是所有者的密码，或其账户被删除。此后它在入口处返回 401。

## 工具

九个数据工具均为只读：

| 工具 | 作用 |
|------|--------------|
| `search_photos` | 像图库一样筛选和排序照片库，除非筛选条件另行设置，否则应用查看器默认的隐藏开关（会报告 `hidden_summary`） |
| `semantic_search` | 按含义查找照片，或用 `scope: "text"` 按说明文字中的词查找 |
| `get_photo` | 按路径获取单张照片的完整详情（不含直方图） |
| `similar_photos` | 按视觉嵌入或颜色查找与某张照片相似的照片 |
| `filter_options` | 筛选条件接受的词汇：相机、镜头、标签、人物、构图模式、类别、叙事瞬间、垃圾类型、指标范围 |
| `list_persons` | 已识别的人物，可按姓名过滤 |
| `list_albums` | 令牌所有者能看到的相册 |
| `library_stats` | 照片库规模、各类型数量和评分概览 |
| `status` | 令牌是谁、它的有效级别、服务器标志以及它能控制的已打开标签页 |

在每个筛选对象中，`show_rejected` 是布尔值：`true` 只列出被淘汰的照片，`false` 或省略则为常规列表。

## 控制已打开的标签页

除数据工具外，服务器始终列出九个 `ui_*` 工具，它们作用于你在浏览器中打开的 Facet 标签页：切换页面、修改筛选或选择，并读回你看到的内容。它们从不写入照片库数据，因此 `readonly` 令牌就够了。

| 工具 | 作用 |
|------|------|
| `ui_navigate` | 前往某个页面（图库、人物、相册、统计等） |
| `ui_set_gallery_filters` | 把补丁合并到图库的筛选和排序中（`null` 移除某个筛选，`replace: true` 从零开始） |
| `ui_get_gallery_view` | 路由、当前筛选、匹配总数、前若干个可见照片路径以及已选数量 |
| `ui_open_photo` | 打开一张照片 |
| `ui_select_photos` | 选择明确的 `paths`，或用 `select_view: true` 选择整个筛选视图，模式为 `replace`、`add` 或 `remove` |
| `ui_clear_selection` | 清空选择 |
| `ui_get_selection` | `scope`（`paths` 或 `view`）和 `count`，附带 `paths`；视图范围则附带 `filters` 和 `excluded_paths` |
| `ui_next_page` | 加载图库的下一页 |
| `ui_show_culling_group` | 在暗房中打开某个分组，由 `(type, group_id)` 标识（编辑账户） |

工作方式：

- 只要你已登录，且 `viewer.mcp.enabled` 与 `viewer.mcp.bridge` 都为 `true`，每个 Facet 标签页都会向 `/api/mcp/bridge` 打开一个同源 WebSocket，并在第一条消息中用你的会话完成认证。桥接默认开启；把 `viewer.mcp.bridge` 设为 `false` 即可关闭，此时 `ui_*` 工具会返回明确的错误。
- 工具只能到达令牌所有者的标签页。单密码安装中所有会话是同一个用户；开放安装中每个标签页都属于共享用户 `_anonymous`，包括 edition 登录。
- 每个标签页都带有打开它的会话的级别，令牌只能控制级别不低于其有效级别的标签页：`edition` 令牌绝不会使用仅有查看会话的标签页，而 `readonly` 令牌可以控制 `edition` 标签页。在单密码安装中，令牌还受创建它的会话限制：由仅查看会话创建的令牌只能到达查看级标签页，绝不会到达 `edition` 标签页（此规则之前创建的令牌被限制在其自身级别）。标签页只能被同级或更高级的标签页替换：仅查看会话重用 `edition` 标签页的 `tab_id` 会被以 4409 拒绝，超过每用户标签页上限时最低级别的标签页最先被移除。`status` 只列出该令牌能控制的标签页。
- 打开多个标签页时，使用最近获得焦点的那个，结果中的 `tab` 字段会说明。传入 `tab_id`（由 `status` 列出）可选择其他标签页。
- 标签页会拒绝其账户无权执行的操作（例如非编辑账户访问 `/culling`），工具会返回该拒绝信息。
- 标签页返回的内容不可信：深度、字符串长度和列表长度都有上限，整体还受 `max_bytes` 限制。
- 错误：`no_tab`（没有已连接的标签页，或桥接已关闭）、`tab_timeout`（在 `call_timeout_s` 内无响应）和 `tab_outdated`（已打开的标签页不认识该工具；升级 Facet 后请刷新页面）。
- 桥接先接受 WebSocket，再以关闭码而非 HTTP 状态码拒绝：端点或桥接关闭时为 4404，`Origin` 缺失或不被允许时为 4403，会话缺失或被拒绝时为 4401。
- 反向代理必须为 `/api/mcp/bridge` 转发 WebSocket 升级；参见[部署](DEPLOYMENT.md)。如果它改写了 `Host` 头，请把公开来源写入 `viewer.mcp.allowed_origins`（例如 `["https://photos.example.com"]`），因为页面的来源必须与主机匹配或在列表中。
- 标签页注册表按进程保存，因此桥接需要单个 worker（默认值）。

补充说明：

- 当打开的是其他页面时，`ui_set_gallery_filters` 会先跳转到图库，再应用补丁。如果补丁中包含标签页无法操作的筛选条件，整个补丁会被拒绝（`invalid_input`）；这类条件请使用 `search_photos`。
- `ui_get_gallery_view`、`ui_next_page` 以及带 `select_view` 的 `ui_select_photos` 要求当前打开的页面是图库（或相册），否则返回 `no_active_view`；请先调用 `ui_navigate` 前往 `/`。`ui_select_photos` 必须恰好给出 `paths` 与 `select_view` 之一。
- `no_tab` 也表示没有打开任何 Facet 标签页：请在浏览器中打开 Facet 并登录。**连接助手**对话框中的**此标签页**会显示连接状态及标签页 id。
- 标签页的会话被拒绝后会停止重连（请重新登录）；如果您的另一个标签页接管了连接，它会等到您回到该标签页再重连。
- 仅当服务器声明桥接可用（端点已启用且 `viewer.mcp.bridge` 为 true）时，标签页桥接才会连接；桥接关闭时，标签页完全不会连接。
- `ui_set_gallery_filters` 会以 `invalid_input` 拒绝未知的筛选名称，也会拒绝同时给出 `category` 与 `type`、或同时给出 `person` 与 `person_id` 的补丁。它只提供图库能够显示的筛选条件；其他条件请使用 `search_photos`。
- `ui_navigate` 只打开应用自身的静态页面：登录页、共享页、外部 URL 和未知路径会被拒绝（`invalid_input`），仅限编辑的页面会对非编辑会话拒绝。
- 在整个视图被选中的状态下，`ui_select_photos` 的 `remove` 模式会忽略已加载视图之外的路径，并在结果中以 `not_in_view` 列出。

## 页面内 WebMCP（浏览器智能体）

除 `/mcp` 端点之外，已登录的标签页还会通过 W3C [WebMCP](https://webmachinelearning.github.io/webmcp/) API（`document.modelContext`）向运行在浏览器内部的智能体提供同一组 `ui_*` 工具。因此浏览器原生的助手看到的正是上文列出的工具，在您正在查看的标签页中执行，并且无需令牌。

- **仅限安全上下文。** Facet 只在 HTTPS 或 `localhost` 下注册这些工具。在普通 HTTP 下不会提供，**连接助手**对话框会提示这一点；上文基于令牌的连接仍可使用。
- 当 `viewer.mcp.enabled` 为 true 且您已登录时注册，退出登录时移除。
- 该对象是 `document.modelContext`（不提供已弃用的 `navigator.modelContext` 别名）。它是一个 polyfill，仅在浏览器没有原生实现时安装，且无法卸载：登录前它可能已存在但不含任何 Facet 工具，退出登录后它仍保留，工具列表为空。
- 这些工具的功能与上表相同，并受同一账户级别的限制。

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
| `create_album` | `edition` | 创建空相册（不幂等：调用两次会创建两个相册） | |
| `album_add_photos` | `edition` | 向相册添加照片（已有的会被忽略） | 1000 个路径 |
| `album_remove_photos` | `edition` | 从相册移除照片；照片本身不受影响 | 1000 个路径 |
| `junk_list` | `readonly` | 列出废片清理的候选，可只列某一种 `kind` | 每页 100 条 |
| `junk_reject` | `edition` | 淘汰废片清理的候选（与 `batch_set_rejected` 相同） | 1000 个路径 |
| `junk_clear` | `edition` | 保留候选：把它们标为已评估且无问题，使其离开队列 | 50 个路径 |
| `cull_apply` | `edition` | 复制保留的照片，或移动、移入回收站被淘汰的照片（[先预览再确认](#破坏性操作先预览再确认)） | 10000 个路径，或 `filters` |
| `delete_photos` | `edition` | 把文件移入回收站并删除其照片库记录（[先预览再确认](#破坏性操作先预览再确认)） | 1000 个路径 |

- **在单密码安装上，`user` 工具需要编辑令牌**，因为该模式没有中间级别（参见[权限级别](#权限级别)）。
- **设置语义。** 逐张照片的工具先读取当前状态，只写入有差异的部分，因此重复调用是无害的；每个路径会报告 `changed` 或 `already`。它们一次处理一个路径，遇到第一个 `library_busy`、`outcome_unknown` 或 `forbidden_level` 就停止，并报告 `affected`、每个路径的 `results` 和 `not_attempted`。批量工具设置的是同样的状态。
- **选择照片。** 批量、标签和 `cull_apply` 工具接受 `paths` 或 `filters`（`search_photos` 的筛选对象）二者之一，外加可选的 `exclude` 列表。`filters` 目标必须带有 `expected_count`，即应用 `exclude` 之前筛选条件的匹配数（`search_photos` 的 `total`）。Facet 会先重新统计，数字不一致时不写入任何内容（`invalid_input`，附带 `actual_count`）。
- **状态归谁。** 评分、收藏和淘汰都属于令牌所有者本人。
- **被跳过的文件。** 当 `cull_apply` 或 `delete_photos` 返回非空的 `skipped` 列表时，结果还会带有 `skipped_reason`：这些库路径在磁盘上没有可读文件（缺失、已移动或不在扫描目录内），对它们未执行任何操作。

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

## 暗房（选片分组）

暗房工具对应 `/culling` 页面。它们全部需要 `edition` 级别，包括只做列表的那些。

| 工具 | 作用 |
|------|------|
| `list_culling_groups` | 列出分组（`burst`、`similar`、`scene`、`bracket`、`panorama`、`hdr_panorama`）及其照片和分数，可排序，并可按相册或日期范围限定 |
| `culling_profiles` | 按题材划分的选片预设以及默认预设 |
| `suggest_culling_profile` | 指出适合某个相册或拍摄时间段的预设 |
| `keeper_hints` | 逐张照片的“这组连拍中有更好的一张”提示，最多 100 个路径（未训练保留者排序头时为空） |
| `auto_cull` | 在保留预算下对某个范围自动选片：先预览，再带 `confirm` 值应用 |
| `confirm_culling_groups` | 确认最多 20 个分组：保留其 `keep_paths`，淘汰 `paths` 中的其余照片 |

- **分组由 `(type, group_id)` 这一对标识**，绝不能只用 `group_id`：相似分组的 id 在与连拍合并时会被偏移。
- **默认的 `group_by: "all"` 只返回连拍和相似分组。** 如需 `scene`、`bracket`、`panorama` 或 `hdr_panorama`，请明确指定。
- **页面通过缩短每个分组的 `photos` 列表来适应 `max_bytes`，绝不会丢弃分组。** `photo_count` 仍是真实大小，`photos_truncated` 标记列表被截断的分组，`has_more` 表示后面是否还有一页。
- **包围曝光、全景和 HDR 全景整组保留。** 在 `confirm_culling_groups` 中，这些类型的 `keep_paths` 必须等于 `paths`（否则 `invalid_input`），`auto_cull` 也从不拆分它们。
- **空的 `keep_paths` 会淘汰该分组的每一帧。** 此时第一次调用返回 `confirmation_required` 并附带一个 `confirm` 值；先展示给用户，再带上该值重复调用。若批量调用在 `forbidden_level`、`library_busy` 或 `rate_limited` 处停止，会报告已完成的分组。
- **`auto_cull` 默认只预览**，返回每组的保留/淘汰划分，以及一个 `confirm` 值（仅当有照片会被淘汰时）。应用时会重新计算方案，若预览后发生变化，或方案太大无法作为一个集合确认，则以 `confirmation_required` 拒绝（用 `album_id`、`date_from` 和 `date_to` 或 `group_by` 缩小范围）。被淘汰的帧会像任何手动选片一样训练个人排序器。
- 调用 `ui_show_culling_group` 可在用户已打开的标签页中向其展示某个分组（参见[控制已打开的标签页](#控制已打开的标签页)）。

## 结果、限制与错误

每个结果都是一个 JSON 信封：`{"ok": true, "data": ...}` 或 `{"ok": false, "error": "<code>", "message": "..."}`。列表返回 `data.rows`（每张照片一组精简的固定字段）以及 `total`。

- **上限：** 最多 `max_rows` 行和 `max_bytes` 序列化字节。末尾的行会被丢弃并设置 `truncated: true`。没有行但超过 `max_bytes` 的结果会变成 `too_large` 错误。
- **速率限制：** 每个令牌每分钟 `rate_per_min` 次读取调用。写入工具使用单独的 `write_rate_per_min` 预算（默认 30），因此搜索不会挤占写入，反之亦然；`cull_apply` 和 `delete_photos` 的试运行算作写入，`auto_cull` 的预览算作读取。超出后返回 `rate_limited` 并附带 `retry_after_s`。同一地址每分钟十次失败的 bearer 尝试会收到 429。
- **错误码：** `forbidden_level`（端点已禁用、令牌失效或级别过低）、`invalid_input`、`not_found`、`rate_limited`、`library_busy`、`upstream_error`、`outcome_unknown`、`confirmation_required`、`too_large`、`no_tab`、`tab_timeout`、`tab_outdated`。
- **较新的错误码：** `confirmation_required`（破坏性调用没有针对这一确切集合的有效 `confirm` 值：重新试运行，把结果展示给用户，然后再试）、`outcome_unknown`（写入超时或连接中断，可能已生效也可能没有：重试前先重新读取状态，切勿盲目重试）、`library_busy`（照片库正忙于其他任务：稍后再试）。
- **入口处的 HTTP 状态码：** 令牌缺失或未知返回 401，跨源的浏览器请求或智能体自身凭据访问 `/api/mcp/tokens` 时返回 403，端点关闭时返回 404。标签页桥接则改用关闭码。

## 安全说明

- 说明文字、标签、文件名、路径以及相册和人物名称都来自你的照片库，可能包含专门用来操纵助手的文字（提示词注入）。每个工具都标有 `facet/untrusted_content`，并告诉模型把它们当作数据处理。不要让同时会读取不可信内容的助手有办法对这里找到的内容采取行动。
- 令牌永不过期。请吊销不再使用的令牌。
- 日志只记录令牌 id、工具、结果和行数，绝不记录参数或令牌本身。

## 已知限制

- 在开放安装（无密码）上，任何能访问查看器的人都可以创建和吊销共享的 `_anonymous` 令牌。在网络上启用该端点之前请先设置密码。标签页桥接会放大这一风险：非浏览器客户端可以发送伪造的 `Origin` 和空令牌，注册一个处于焦点的 `_anonymous` 标签页，用任意数据应答 `ui_*` 调用，并通过 8 个标签页的上限挤掉真实的标签页。
- 速率限制和认证失败计数器保存在各进程内存中；使用 `viewer.py --workers N` 时每个 worker 各自计数。
- 标签页注册表保存在单个进程的内存中。依赖 `ui_*` 工具时请使用单个 worker（`viewer.py --workers 1`，默认值）；有多个 worker 时，调用可能落到不认识你标签页的进程并返回 `no_tab`。
- 每位用户最多可同时连接 8 个标签页；打开第 9 个会关闭最旧的一个。
