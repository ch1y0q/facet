# AI 智能体（MCP）

> 🌐 [English](../AGENTS.md) · [Français](../fr/AGENTS.md) · [Deutsch](../de/AGENTS.md) · [Italiano](../it/AGENTS.md) · [Español](../es/AGENTS.md) · [Português](../pt/AGENTS.md) · **简体中文**

Facet 可以作为 [Model Context Protocol](https://modelcontextprotocol.io/)（MCP）服务器运行，让 Claude Code 之类的 AI 助手用与图库相同的筛选条件搜索和查看你的照片库。它提供九个不会改动照片库的读取工具，另有九个 `ui_*` 工具，用来控制你已经打开的浏览器标签页（页面、筛选、选择），且从不写入照片库数据。

## 启用

该端点**默认关闭**。在 `scoring_config.json` 中把 `viewer.mcp.enabled` 设为 `true`（参见 [智能体端点（MCP）](CONFIGURATION.md#智能体端点mcp)），然后重启查看器或重新加载配置。关闭期间，`/mcp` 和所有 `/api/mcp/*` 路由都返回 404。

端点是查看器自身端口上的 `POST /mcp`：Streamable HTTP、无状态、纯 JSON 响应。`GET` 返回 405。只有标签页桥接 `/api/mcp/bridge` 是 WebSocket，参见[控制已打开的标签页](#控制已打开的标签页)。

## 创建令牌

最简单的方式是在浏览器中操作。启用 `viewer.mcp.enabled` 后，打开账户菜单并选择**连接助手**。在**创建令牌**下输入**名称**，并选择**助手可执行的操作**：**仅读取和操作界面**；若当前会话具备相应级别，还可选择**代表我操作**或**完全编辑**（令牌的级别不能高于创建它的会话）。点击**创建令牌**：令牌只会在**您的新令牌**下显示一次，请立即复制。**访问令牌**列出您的令牌及其最近使用时间，并可撤销其中一个。**添加到 Claude Code**给出可直接粘贴的 Claude Code 命令（见下文），**此标签页**则说明此标签页是否已连接、能否被助手操控。 级别列表仅限服务器会授予的范围：开放安装只提供**仅读取和操作界面**，**代表我操作**仅出现在多用户安装中，**完全编辑**仅在编辑会话中提供。创建后，对话框会说明实际授予的级别（“已授予的权限：{level}”）。

通过脚本创建（curl）：

助手使用以 `fct_` 开头的个人令牌进行认证。用一个已认证的请求创建它（令牌**只返回一次**；Facet 只保存它的 SHA-256 哈希）：

```bash
TOKEN=$(curl -s -X POST http://localhost:5000/api/auth/login -H 'Content-Type: application/json' -d '{"password": "YOUR_VIEWER_PASSWORD"}' | jq -r .access_token)
curl -s -X POST http://localhost:5000/api/mcp/tokens -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"name": "claude-code", "level": "readonly"}'
```

响应的 `token` 字段包含明文令牌。`GET /api/mcp/tokens` 列出你的令牌（绝不包含密钥本身），`DELETE /api/mcp/tokens/{id}` 吊销其中一个。超级管理员可以用 `?all=1` 列出所有所有者的令牌并吊销任意一个。每位所有者最多持有 20 个有效令牌（超出返回 412）。这些路由会拒绝智能体自己的凭据，因此助手永远无法创建、列出或吊销令牌。

## 连接 Claude Code

```bash
claude mcp add --transport http facet http://localhost:5000/mcp --header "Authorization: Bearer fct_YOUR_TOKEN"
```

之后工具会以 `mcp__facet__search_photos` 等名称出现。只要查看器可以从你自己的机器之外访问，就请使用 HTTPS，因为每次调用令牌都会放在请求头里传输。

## 权限级别

令牌创建时被授予一个级别：`readonly`、`user` 或 `edition`。**有效**级别在每次调用时重新计算，取令牌授予级别与其所有者当前级别中较低的一个：

- 单密码安装：`user` 在创建时被限制为 `readonly`，因为该模式没有中间级别。`edition` 令牌需要编辑会话，且只在编辑密码未变更期间有效。
- 多用户安装：之后被降级的用户的 `edition` 令牌会降为 `user`；升级绝不会让令牌超过其授予级别。
- 开放安装（未设置密码）：令牌始终为 `readonly`，并归属于共享所有者 `_anonymous`。

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
| `status` | 令牌是谁、它的有效级别以及服务器标志 |

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
- 工具只能到达令牌所有者的标签页。单密码安装中所有会话是同一个用户；开放安装中每个标签页都属于共享用户 `_anonymous`。
- 打开多个标签页时，使用最近获得焦点的那个，结果中的 `tab` 字段会说明。传入 `tab_id`（由 `status` 列出）可选择其他标签页。
- 标签页会拒绝其账户无权执行的操作（例如非编辑账户访问 `/culling`），工具会返回该拒绝信息。
- 标签页返回的内容不可信：深度、字符串长度和列表长度都有上限，整体还受 `max_bytes` 限制。
- 错误：`no_tab`（没有已连接的标签页，或桥接已关闭）、`tab_timeout`（在 `call_timeout_s` 内无响应）和 `tab_outdated`（已打开的标签页不认识该工具；升级 Facet 后请刷新页面）。
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

除 `/mcp` 端点之外，已登录的标签页还会通过 W3C [WebMCP](https://webmachinelearning.github.io/webmcp/) API（`navigator.modelContext`）向运行在浏览器内部的智能体提供同一组 `ui_*` 工具。因此浏览器原生的助手看到的正是上文列出的工具，在您正在查看的标签页中执行，并且无需令牌。

- **仅限安全上下文。** Facet 只在 HTTPS 或 `localhost` 下注册这些工具。在普通 HTTP 下不会提供，**连接助手**对话框会提示这一点；上文基于令牌的连接仍可使用。
- 当 `viewer.mcp.enabled` 为 true 且您已登录时注册，退出登录时移除。
- 这些工具的功能与上表相同，并受同一账户级别的限制。

## 结果、限制与错误

每个结果都是一个 JSON 信封：`{"ok": true, "data": ...}` 或 `{"ok": false, "error": "<code>", "message": "..."}`。列表返回 `data.rows`（每张照片一组精简的固定字段）以及 `total`。

- **上限：** 最多 `max_rows` 行和 `max_bytes` 序列化字节。末尾的行会被丢弃并设置 `truncated: true`。没有行但超过 `max_bytes` 的结果会变成 `too_large` 错误。
- **速率限制：** 每个令牌每分钟 `rate_per_min` 次调用（写入调用另有独立的 `write_rate_per_min` 额度）。超出后返回带 `retry_after_s` 的 `rate_limited`。同一地址每分钟 Bearer 认证失败十次会返回 429。
- **错误码：** `forbidden_level`（端点已关闭、令牌失效或级别过低）、`invalid_input`、`not_found`、`rate_limited`、`library_busy`、`upstream_error`、`outcome_unknown`、`too_large`、`no_tab`、`tab_timeout`、`tab_outdated`。
- **入口处的 HTTP 状态码：** 令牌缺失或未知返回 401，跨源的浏览器请求返回 403，端点关闭时返回 404。

## 安全说明

- 说明文字、标签、文件名、路径以及相册和人物名称都来自你的照片库，可能包含专门用来操纵助手的文字（提示词注入）。每个工具都标有 `facet/untrusted_content`，并告诉模型把它们当作数据处理。不要让同时会读取不可信内容的助手有办法对这里找到的内容采取行动。
- 令牌永不过期。请吊销不再使用的令牌。
- 日志只记录令牌 id、工具、结果和行数，绝不记录参数或令牌本身。

## 已知限制

- 在开放安装（无密码）上，任何能访问查看器的人都可以创建和吊销共享的 `_anonymous` 令牌。在网络上启用该端点之前请先设置密码。标签页桥接会放大这一风险：非浏览器客户端可以发送伪造的 `Origin` 和空令牌，注册一个处于焦点的 `_anonymous` 标签页，用任意数据应答 `ui_*` 调用，并通过 8 个标签页的上限挤掉真实的标签页。
- 速率限制和认证失败计数器保存在各进程内存中；使用 `viewer.py --workers N` 时每个 worker 各自计数。
- 标签页注册表保存在单个进程的内存中。依赖 `ui_*` 工具时请使用单个 worker（`viewer.py --workers 1`，默认值）；有多个 worker 时，调用可能落到不认识你标签页的进程并返回 `no_tab`。
- 每位用户最多可同时连接 8 个标签页；打开第 9 个会关闭最旧的一个。
