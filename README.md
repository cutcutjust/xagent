<div align="center">

# XAgent

**X 平台 AI 调研与操作 Agent**

纯 API 快速调研 · 综合评分筛选 · 交互式引导 · 发推互动

---

`explore` → `research` → `report` → `analyze` → `write` → `publish`

</div>

---

## 特性

- **交互式入口** — 直接输入 `xagent`，引导选择操作流程
- **模糊概念引导** — `xagent explore "mythos"` 自动拆解方向，选择后调研
- **综合评分** — 相关性(30%) + 互动热度(40%) + 时效性(30%)，不再仅靠 LLM 打分
- **纯 API 调研** — 无需浏览器/桌面权限，Bearer Token 直连 X API
- **视觉深度采集** — 可选 `--mode visual`，截图+视觉模型提取图片/完整正文
- **实时保存** — 每帖持久化到 SQLite + 本地 MD + Notion
- **下一步引导** — 每步操作后自动提示可用的后续命令

---

## 快速上手

```bash
# 1. 安装
python3.13 -m venv .venv && source .venv/bin/activate
pip install -e .

# 2. 全局可用（可选）
echo 'alias xagent="/Users/justyn/SightOps/xagent/.venv/bin/xagent"' >> ~/.zshrc
source ~/.zshrc

# 3. 配置 .env
#    LLM_API_KEY=sk-xxx                          # 必需
#    X_API_BEARER_TOKEN=xxx                       # API 模式必需
#    X_API_CONSUMER_KEY=xxx                       # OAuth 1.0a，互动功能必需

# 4. 初始化
xagent setup

# 5. 开始（三种方式）
xagent                    # 交互模式，引导选择
xagent explore "mythos"   # 模糊概念 → 拆解方向 → 调研
xagent research "AI agent" # 直接调研
```

> 纯 API 模式无需任何系统权限。`--mode visual` 需 macOS 屏幕录制 + 辅助功能授权。

---

## CLI 命令

| 命令 | 说明 |
|------|------|
| `xagent` | 交互模式 — 引导选择操作 |
| `xagent explore "概念"` | 模糊概念引导 — LLM 拆解方向 → 选择 → 调研 |
| `xagent research "主题"` | 调研 — `--mode api`（默认）或 `--mode visual` |
| `xagent report "主题"` | 报告 — `--type research\|article\|summary`，带引用 |
| `xagent analyze` | 分析 — 爆款风格：钩子类型 / 叙事结构 / 风格分布 |
| `xagent write` | 写作 — 提取风格 → 通用草稿 → 平台适配 |
| `xagent publish` | 发布 — 视觉操作发布到 X |
| `xagent status` | 总览 — 采集统计 / 草稿 / 排行 |
| `xagent setup` | 初始化 — 检查环境 / 配置 / 权限 / 数据库 |
| `xagent observe` | 观察 — 实时截图 + LLM 分析 |

---

## 使用流程

### 交互模式

```bash
$ xagent

  XAgent — X 平台 AI 调研与操作 Agent

  1  🔍 探索    输入模糊概念，引导拆解方向后调研
  2  📡 调研    直接搜索 X 上的热门话题和帖子
  3  📊 分析    分析已采集内容的爆款风格
  4  ✍️  写作    基于调研生成草稿
  5  📋 总览    查看数据统计
  6  🚀 完整流程 调研 → 报告 → 分析 → 写作

  选择: 6
```

### 模糊概念引导

```bash
$ xagent explore "mythos"

  「mythos」可拆解为以下方向：

  1  Claude Mythos     Anthropic 即将发布的 Claude 新版本
  2  Mythos 品牌IP     Batman/漫威周边艺术
  3  Greek Mythos      希腊神话相关讨论
  4  Mythos 游戏       独立游戏/桌游

  选择方向（多选用逗号，0=全部）: 1
```

### 直接调研

```bash
# 纯 API（默认，无需权限）
xagent research "AI agent" --limit 50

# 视觉深度采集（需 macOS 权限）
xagent research "AI agent" --mode visual
```

### 综合评分

每个帖子按三维综合评分，不再仅靠 LLM 相关性：

```
final_score = relevance × 0.3 + engagement × 0.4 + freshness × 0.3
              ─────────────     ──────────────     ──────────────
              LLM 打分 1-5     互动归一化 0-5      时效性 0-5
```

- **relevance**: LLM 对帖子与 AI/创业/科技的相关性打分
- **engagement**: 批次内互动分归一化（likes + reposts×1.5 + replies×2 + views×0.01）
- **freshness**: 7天内=5，30天内=3，更久=1

### 分析 → 写作 → 发布

```bash
xagent report "AI Agent 趋势"                    # 调研报告
xagent analyze --days 7                          # 爆款风格分析
xagent write --type article --topic "AI Agent"   # 生成草稿
xagent publish                                   # 发布到 X
```

---

## 配置

### `.env`

```bash
# ── LLM（必需）─
LLM_API_KEY=sk-xxx
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen3.6-plus
LLM_VISION_MODEL=qwen3.6-plus

# ── X API（API 模式必需）─
X_API_BEARER_TOKEN=xxx          # App-Only Auth，搜索/评论
X_API_CONSUMER_KEY=xxx          # OAuth 1.0a，发推/点赞/关注
X_API_CONSUMER_SECRET=xxx
X_API_ACCESS_TOKEN=xxx
X_API_ACCESS_TOKEN_SECRET=xxx

# ── Notion（可选）─
NOTION_TOKEN=ntn_xxx
NOTION_RESEARCH_DB_ID=xxx
NOTION_TEMPLATE_DB_ID=xxx
NOTION_DRAFT_DB_ID=xxx

# ── 其他 ─
LOG_LEVEL=INFO
DATA_DIR=./data
DESKTOP_MAX_CYCLES=20
```

### Notion 数据库

1. 创建数据库，包含属性：`名称`（标题）、`Platform`（单选）、`URL`（链接）、`Relevance`（数字）、`Likes`（数字）、`Tags`（多选）、`Collected`（日期）、`Status`（单选）、`Author`（文本）
2. 将 Integration 分享到该数据库
3. 填入 `.env`

> 属性不匹配？运行 `python scripts/notion_editor.py fix` 自动修复。

### configs/

**topics.yaml** — 默认搜索关键词

```yaml
keywords:
  - "AI agent"
  - "vibe coding"
  - "LLM"
```

**app.yaml** — 调研/写作参数

```yaml
research:
  topics_per_run: 10
  posts_per_topic: 30
  relevance_threshold: 2.0    # 综合评分阈值（原 3.0，现综合评分后可降低）
writing:
  top_k_sources: 5
```

---

## 架构

### 双模式调研

```
APIXResearcher (--mode api)          DesktopXResearcher (--mode visual)
  │                                      │
  ├─ search_tweets() [Bearer]           ├─ search_tweets() [OAuth 1.0a]
  ├─ _collect_tweet() ×N                ├─ _collect_and_save_tweet()
  │   ├─ API 取正文/指标/媒体           │   ├─ 视觉提取正文/指标
  │   ├─ fetch_tweet_replies()          │   ├─ fetch_tweet_replies()
  │   └─ LLM 相关性打分                │   ├─ 视觉图片分析
  │                                      │   └─ LLM 打分 + 摘要
  ├─ score_batch()                      │
  │   └─ relevance×0.3 + engagement×0.4 + freshness×0.3
  ├─ 筛选保存                           │
  │   └─ save → SQLite + MD + Notion    └─ save → SQLite + MD + Notion
  │
  └─ 无需浏览器/权限                     └─ 需 macOS 权限
```

### 数据流

```
CollectedContent ──→ SQLite ──→ analyze / report / write
      │                │
      ├── 本地 MD       └── PlatformDraft ──→ publish
      └── Notion
```

---

## 项目结构

```
app/
  cli/               Typer CLI（交互入口 + Rich 美化）
  core/              配置 · 错误 · 日志
  schemas/           数据模型（CollectedContent 含 final_score）
  llm/               LLM 客户端（OpenAI 兼容）
  research/          纯 API 调研
    api_researcher.py    APIXResearcher
    scorer.py            综合评分（relevance + engagement + freshness）
  desktop/           视觉桌面控制
    computer_agent.py    see-think-act-verify 循环
    executor.py          拟人执行器
    research_agent.py    DesktopXResearcher + 公共 LLM 函数
    publisher.py         X 发布器
  analysis/          爆款风格挖掘 + 报告生成
  writing/           内容生成
  integrations/      X API · Notion API
  memory/            SQLite 存储
configs/             YAML 配置
prompts/             LLM 模板
data/                运行时数据
```

---

## 扩展

添加 `app/platforms/<name>/` 目录实现平台规则。核心视觉循环和 API 调研器无需修改。
