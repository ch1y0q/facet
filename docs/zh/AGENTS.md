# AI 智能体（MCP）

> 🌐 [English](../AGENTS.md) · [Français](../fr/AGENTS.md) · [Deutsch](../de/AGENTS.md) · [Italiano](../it/AGENTS.md) · [Español](../es/AGENTS.md) · [Português](../pt/AGENTS.md) · **简体中文**

Facet 可以作为 [Model Context Protocol](https://modelcontextprotocol.io/)（MCP）服务器运行，让 Claude Code 之类的 AI 助手用与图库相同的筛选条件搜索和查看你的照片库。该端点是只读的：它提供九个读取工具，不会改动你的照片库。

## 启用

该端点**默认关闭**。在 `scoring_config.json` 中把 `viewer.mcp.enabled` 设为 `true`（参见 [智能体端点（MCP）](CONFIGURATION.md#智能体端点mcp)），然后重启查看器或重新加载配置。关闭期间，`/mcp` 和所有 `/api/mcp/*` 路由都返回 404。

端点是查看器自身端口上的 `POST /mcp`：Streamable HTTP、无状态、纯 JSON 响应。`GET` 返回 405。反向代理中不需要 WebSocket 头。

## 创建令牌

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

已注册的九个工具全部为只读：

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

## 结果、限制与错误

每个结果都是一个 JSON 信封：`{"ok": true, "data": ...}` 或 `{"ok": false, "error": "<code>", "message": "..."}`。列表返回 `data.rows`（每张照片一组精简的固定字段）以及 `total`。

- **上限：** 最多 `max_rows` 行和 `max_bytes` 序列化字节。末尾的行会被丢弃并设置 `truncated: true`。没有行但超过 `max_bytes` 的结果会变成 `too_large` 错误。
- **速率限制：** 每个令牌每分钟 `rate_per_min` 次调用（写入调用另有独立的 `write_rate_per_min` 额度）。超出后返回带 `retry_after_s` 的 `rate_limited`。同一地址每分钟 Bearer 认证失败十次会返回 429。
- **错误码：** `forbidden_level`（端点已关闭、令牌失效或级别过低）、`invalid_input`、`not_found`、`rate_limited`、`library_busy`、`upstream_error`、`outcome_unknown`、`too_large`。
- **入口处的 HTTP 状态码：** 令牌缺失或未知返回 401，跨源的浏览器请求返回 403，端点关闭时返回 404。

## 安全说明

- 说明文字、标签、文件名、路径以及相册和人物名称都来自你的照片库，可能包含专门用来操纵助手的文字（提示词注入）。每个工具都标有 `facet/untrusted_content`，并告诉模型把它们当作数据处理。不要让同时会读取不可信内容的助手有办法对这里找到的内容采取行动。
- 令牌永不过期。请吊销不再使用的令牌。
- 日志只记录令牌 id、工具、结果和行数，绝不记录参数或令牌本身。

## 已知限制

- 在开放安装（无密码）上，任何能访问查看器的人都可以创建和吊销共享的 `_anonymous` 令牌。在网络上启用该端点之前请先设置密码。
- 速率限制和认证失败计数器保存在各进程内存中；使用 `viewer.py --workers N` 时每个 worker 各自计数。
- `viewer.mcp.bridge` 由 `status` 工具读取，目前没有其他用途。
