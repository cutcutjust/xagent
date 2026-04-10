<div align="center">

# XAgent

**X 平台智能调研 Agent — 方向驱动的深度内容挖掘**

需求轮询 · 方向驱动打分 · 循环补采至40+引用 · 视觉精读 · 发推互动

---

`research` → `report` → `analyze` → `write` → `publish`

</div>

---

## 特性

- **需求轮询** — 模糊关键词自动拆解方向，用户确认后再搜索
- **方向驱动打分** — LLM 按用户确认的调研方向评分，不是通用标准
- **循环补采** — 低权重舍弃，不足40个有效引用时自动扩展搜索词继续补采
- **综合评分** — 相关性(30%) + 互动热度(40%) + 时效性(30%)
- **纯 API 调研** — 无需浏览器/桌面权限，Bearer Token 直连 X API
- **视觉精读** — API 调研后用 `--deep-read` 精读高权重帖子，提取图片/视频
- **实时保存** — 每帖持久化到 SQLite + 本地 MD + Notion

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

# 5. 开始
xagent research "mythos"   # 模糊概念 → 拆解方向 → 循环采集 → 视觉精读
```

> 纯 API 模式无需任何系统权限。`--mode visual` 和 `--deep-read` 需 macOS 屏幕录制 + 辅助功能授权。

---

## CLI 命令

| 命令 | 说明 |
|------|------|
| `xagent` | 交互模式 — 引导选择操作 |
| `xagent research "主题"` | 调研 — 需求轮询 → 循环补采至 `--min-refs`(默认40) → 视觉精读 |
| `xagent report "主题"` | 报告 — `--type research\|article\|summary`，带引用 |
| `xagent analyze` | 分析 — 爆款风格：钩子类型 / 叙事结构 / 风格分布 |
| `xagent write` | 写作 — 提取风格 → 通用草稿 → 平台适配 |
| `xagent publish` | 发布 — 视觉操作发布到 X |
| `xagent status` | 总览 — 采集统计 / 草稿 / 排行 |
| `xagent setup` | 初始化 — 检查环境 / 配置 / 权限 / 数据库 |
| `xagent observe` | 观察 — 实时截图 + LLM 分析 |

---

## 使用流程

### 需求轮询

```bash
$ xagent research "mythos"

  ▶ 分析「mythos」的调研方向...

  「mythos」可拆解为以下方向：

  1  Claude Mythos     Anthropic 即将发布的 Claude 新版本
  2  Mythos 品牌IP     Batman/漫威周边艺术
  3  Greek Mythos      希腊神话相关讨论
  4  Mythos 游戏       独立游戏/桌游

  选择方向（多选用逗号，0=全部）: 1
```

选择后，调研方向用于：
1. **API 搜索** — 用方向的 keywords 发起搜索
2. **相关性打分** — LLM 按确认的方向评估每条帖子的相关性
3. **循环补采** — 不足40个有效引用时扩展搜索词继续搜索

### 调研参数

```bash
# 默认: 循环补采至40个有效引用 + 视觉精读 Top 3
xagent research "AI agent"

# 自定义最少引用数
xagent research "AI agent" --min-refs 60

# 关闭视觉精读
xagent research "AI agent" --deep-read 0

# 精读 Top 5 高权重帖子
xagent research "AI agent" --deep-read 5

# 视觉深度采集模式（需 macOS 权限）
xagent research "AI agent" --mode visual
```

### 综合评分

```
final_score = relevance × 0.3 + engagement × 0.4 + freshness × 0.3
              ─────────────     ──────────────     ──────────────
              方向驱动 1-5     互动归一化 0-5      时效性 0-5
```

- **relevance**: LLM 按用户确认的调研方向打分（5=直击要点，3=间接相关，1=不相关）
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
  relevance_threshold: 2.0
writing:
  top_k_sources: 5
```

---

## 架构

```
用户输入模糊概念
  │
  ├─ _clarify_topics()  → LLM 拆解方向 → 用户确认 → research_context
  │
  ▼
APIXResearcher.discover()
  │
  ├─ search_tweets() [Bearer]  ×  N 个关键词
  ├─ _collect_tweet()
  │   ├─ API 取正文/指标/媒体
  │   ├─ fetch_tweet_replies()
  │   └─ score_relevance(research_context)  ← 按用户确认的方向打分
  │
  ├─ score_batch()  →  relevance×0.3 + engagement×0.4 + freshness×0.3
  ├─ 筛选: final_score >= threshold → 保存,  < threshold → 舍弃
  │
  ├─ 有效引用 < 40?
  │   └─ _expand_keywords()  → LLM 生成新搜索词 → 继续搜索
  │
  └─ deep_read_posts()  → Top N 高权重帖子 → 视觉提取图片/视频/完整正文
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
  cli/               Typer CLI（交互入口 + Rich 终端美化）
  core/              配置 · 错误 · 日志
  schemas/           数据模型（CollectedContent 含 final_score）
  llm/               LLM 客户端（OpenAI 兼容）
  research/          纯 API 调研
    api_researcher.py    APIXResearcher（循环补采 + 方向驱动打分）
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
