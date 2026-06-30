<p align="center">
  <img src="./logo.png" width="112" alt="猪猪派对">
</p>

<h1 align="center">猪猪派对</h1>

<p align="center">
  <a href="https://github.com/Mitsukikis/astrbot_plugin_pig_party"><img alt="Repository" src="https://img.shields.io/badge/GitHub-astrbot__plugin__pig__party-24292f?logo=github"></a>
  <img alt="AstrBot" src="https://img.shields.io/badge/AstrBot-%3E%3D%204.16.0-2f81f7">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.10%2B-3776ab?logo=python&logoColor=white">
  <img alt="License" src="https://img.shields.io/badge/License-MIT-0f766e">
</p>

<p align="center">
  一个为 AstrBot 打磨的猪猪表情插件：今日小猪、随机猪图、含猪字自动回复，以及来自 PigHub 的大规模表情池。
</p>

---

## 为什么是它

`猪猪派对` 把两个常见玩法收束成一个干净的 AstrBot 插件：

- `今日小猪`：每个用户每天抽取一张属于自己的小猪，并生成带标题、短描述和性格注解的图文卡片。
- `随机小猪`：从 PigHub 表情池随机发送原图，支持静态图和 GIF。
- 普通消息触发：用户消息里包含 `猪`、`🐷`、`🐖`、`🐽` 等关键词时自动回复随机猪图。
- 资源自动更新：优先从 PigHub 官方接口刷新索引，失败时使用 PigHub-DB 同步仓库兜底，再失败才回退旧资源目录。
- 稳定去重：同一群聊内尽量避开最近发送过的图片，减少短时间重复刷屏。

它的目标不是把功能堆满，而是把一个小而高频的群聊娱乐动作做稳、做顺、做得有一点审美。

## 功能一览

| 能力 | 说明 |
| --- | --- |
| 今日小猪 | 每个用户每日固定一只，重复查询不会变 |
| 今日注解 | 根据图片标题生成差异化描述，不再千图一面 |
| 随机猪图 | 直接发送 PigHub 原图，GIF 会以 GIF 形式发送 |
| 含猪触发 | 普通消息带关键词时自动发送随机猪图 |
| 远程索引 | 默认每 12 小时刷新一次 PigHub 图片索引 |
| 本地缓存 | 图片按需下载到本地缓存，后续发送更快 |
| 降级发送 | 合成图失败时回退为原图加文字说明 |

## 指令

| 指令或消息 | 行为 |
| --- | --- |
| `/今日小猪` | 抽取或查看自己的今日小猪 |
| `/抽小猪` | `/今日小猪` 的别名 |
| `/我的小猪` | `/今日小猪` 的别名 |
| `/随机小猪` | 随机发送一张猪猪表情 |
| `/随机猪猪` | `/随机小猪` 的别名 |
| `/猪猪` | `/随机小猪` 的别名 |
| 普通消息包含 `猪` | 自动发送随机猪图 |

> AstrBot 的命令前缀由你的实例配置决定。上表以默认 `/` 为例。

## 安装

### 通过 AstrBot 插件市场

插件上架后，可在 AstrBot WebUI 的插件市场中搜索 `猪猪派对` 或 `astrbot_plugin_pig_party`，安装后启用即可。

### 通过 GitHub 仓库

将仓库克隆到 AstrBot 插件目录：

```bash
cd /path/to/AstrBot/data/plugins
git clone https://github.com/Mitsukikis/astrbot_plugin_pig_party.git
```

安装依赖：

```bash
pip install -r astrbot_plugin_pig_party/requirements.txt
```

然后在 AstrBot WebUI 中重载或重启 AstrBot。

## 配置项

| 配置 | 默认值 | 说明 |
| --- | --- | --- |
| `auto_reply_pig_messages` | `true` | 是否开启普通消息含猪自动回复 |
| `pig_trigger_keywords` | `猪,🐷,🐖,🐽` | 随机猪图触发关键词，支持中英文逗号分隔 |
| `random_recent_limit` | `8` | 同一会话内随机猪图的最近去重数量 |
| `at_view_pig` | `false` | 是否允许通过艾特查看他人的今日小猪 |
| `enable_remote_resource` | `true` | 是否启用 PigHub 远程索引和图片下载 |
| `remote_refresh_hours` | `12` | PigHub 索引刷新间隔，设为 `0` 可关闭 |
| `remote_resource_base` | 旧版资源地址 | PigHub 失败后的最终兜底资源目录 |

## 数据源与缓存策略

插件默认使用三层资源策略：

1. PigHub 官方接口：`https://pighub.top/api/images?sort=2`
2. PigHub-DB 同步仓库：`https://github.com/BadFish-HSrui/PigHub-DB`
3. 旧版 rollpig 资源目录：作为最终兜底

`resource/pig.json` 是随仓库提供的索引快照。插件启动后会按配置刷新索引；发送图片时才下载具体图片，并缓存到 `resource/image/`。该目录不会进入 Git 仓库，避免仓库体积膨胀。

## 设计取舍

### 合并而不是叠加

旧的“今日小猪”和“随机猪图”分别处理触发和资源，容易出现抢触发、重复回复、某个插件资源损坏导致另一个插件看起来也异常的问题。`猪猪派对` 把它们合并成一个状态清晰的入口，减少冲突面。

### 注解来自规则，不依赖大模型

今日小猪的注解按标题关键词和稳定哈希生成。这样做有三个好处：

- 同一张图片总是同一套解释。
- 不需要调用模型，成本和延迟都可控。
- 审核和运行时更透明，不会因为外部模型返回异常导致插件不可用。

### 远程资源只做增量

插件不会在启动时下载全部图片，只刷新索引。真正发送某张图片时才下载原图。这样既能使用 PigHub 的完整表情池，又不会让服务器在安装后立刻承受大量网络和磁盘压力。

## 安全与可靠性

- 不执行远程代码，只读取 JSON 索引和图片资源。
- 对下载大小设置上限，避免异常大文件拖垮进程。
- 对远程接口返回值做结构校验，错误 JSON 不会覆盖可用索引。
- 今日小猪数据和随机历史保存在 AstrBot 插件数据目录中，更新插件时不丢失。
- 合成图片使用临时文件，发送后自动清理。

## 插件市场信息

提交 AstrBot 插件市场时可使用以下信息：

```json
{
  "name": "astrbot_plugin_pig_party",
  "display_name": "猪猪派对",
  "desc": "将今日小猪、随机猪图和含猪字自动回复合并为一个稳定的 PigHub 表情插件。",
  "author": "Mitsukikis",
  "repo": "https://github.com/Mitsukikis/astrbot_plugin_pig_party",
  "tags": ["娱乐", "表情包", "PigHub"],
  "social_link": "https://github.com/Mitsukikis"
}
```

## 开发

运行测试：

```bash
python -B tests/test_pighub_client.py
```

做语法检查：

```bash
python -B -m py_compile main.py pighub_client.py
```

## 鸣谢

- PigHub：提供高质量猪猪表情池。
- BadFish-HSrui/PigHub-DB：提供 PigHub 图片同步仓库。
- Bear_lele、MegSopern：早期今日小猪与猪图玩法来源。
- AstrBot：提供插件运行时与市场生态。

## License

MIT License. See [LICENSE](./LICENSE).
