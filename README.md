# SightOps

全屏视觉 AI 调研 Agent — 像真人一样操作你的 Mac，通过屏幕截图理解界面，用键鼠完成调研、写作、发布全流程。

**核心能力**：模型看截图 → 分析当前状态 → 决定下一步 → 执行键鼠 → 截图验证 → 循环。无硬编码导航序列，无 API 依赖，纯视觉闭环。

**技术栈**：Qwen3.6-Plus（视觉）· PyAutoGUI（全局控制）· Notion API · SQLite · Rich CLI

---

## 快速上手

```bash
# 1. 安装
pip install -e .

# 2. 初始化项目
sightops setup

# 3. 编辑 .env，填入 LLM API Key
#    LLM_API_KEY=sk-xxx

# 4. 开始调研
sightops research "AI agent"

# 5. 查看状态
sightops status
```

> **系统授权**：系统设置 → 隐私与安全性 → 屏幕录制 + 辅助功能 → 启用终端 → 重启 Terminal

---

## CLI 命令

| 命令 | 说明 |
|------|------|
| `sightops setup` | 初始化项目（首次使用）— 检查 Python/配置/权限/数据库 |
| `sightops research "主题"` | 全屏视觉调研 — 搜索 → 逐篇点开 → 正文/图片/评论/指标 → Notion 同步 |
| `sightops analyze` | 爆款风格分析 — 对已采集内容做钩子/结构/叙事模式统计 |
| `sightops write` | 根据调研生成草稿 — 提取风格 → 通用草稿 → 平台适配 |
| `sightops publish` | 发布草稿到 X — 纯视觉操作 |
| `sightops status` | 数据总览 — 采集统计 / 待发布草稿 / 内容排行榜 |
| `sightops observe` | 实时屏幕观察器 — 全屏截图 + LLM 分析 |

---

## 使用流程

### Step 0 — 初始化

```bash
sightops setup
```

自动完成：检查 Python 环境 → 验证 LLM 配置 → 创建目录结构 → 初始化 SQLite → 检查 macOS 权限。

### Step 1 — 调研

```bash
# 搜索关键词
sightops research "AI agent" "vibe coding" --limit 20

# 使用 topics.yaml 默认关键词
sightops research
```

**深度调研流程**：

```
打开 Safari → x.com → 搜索关键词
  ↓
滚动识别当前屏幕帖子
  ↓
逐一点开 → 聚焦浏览器 → 提取正文/指标
  ↓
有图片？点开分析 · 有评论？滚动读取
  ↓
相关性打分 → 摘要 + 标签 → 保存 SQLite
  ↓
同步 Notion → 返回搜索结果
  ↓
继续滚动 → 下一个帖子
```

每个帖子完整采集：
- **正文**：完整文本 + 外部链接
- **图片**：点击打开 → 视觉分析 → 提取洞察
- **评论**：3 轮滚动 → 提取评论内容 + 点赞数
- **指标**：点赞/转发/评论/阅读/收藏
- **链接**：分享按钮 → Copy Link → 精确 URL
- **Notion 同步**：自动同步到 Research 数据库

> **紧急终止**：鼠标移到屏幕左上角（PyAutoGUI FAILSAFE）

### Step 2 — 分析

```bash
# 分析最近 7 天的爆款风格
sightops analyze

# 分析最近 30 天
sightops analyze --days 30
```

统计热门开头类型、叙事结构模式、内容风格分布。

### Step 3 — 写作

```bash
# 生成长文
sightops write --type article --topic "AI Agent 趋势"

# 生成 Thread
sightops write --type thread

# 生成短帖
sightops write --type short_post
```

流程：提取 Top K 来源风格 → 生成通用草稿 → 适配平台格式 → 预览保存。

### Step 4 — 发布

```bash
# 查看状态和草稿
sightops status

# 发布最新草稿
sightops publish
```

---

## 配置

### `.env` 文件

```bash
# ── LLM（必需）─
LLM_API_KEY=sk-xxx
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen3.6-plus
LLM_VISION_MODEL=qwen3.6-plus

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

### Notion 数据库设置

1. 在 Notion 中创建一个数据库（或在 SightOps Research 页面中添加）
2. 确保包含以下属性：`名称`（标题）、`Platform`（单选）、`URL`（链接）、`Relevance`（数字）、`Likes`（数字）、`Tags`（多选）、`Collected`（日期）、`Status`（单选）、`Author`（文本）、`Published URL`（链接）
3. 将 Integration 分享到该数据库
4. 将数据库 ID 填入 `.env`

> 如果数据库属性不匹配，运行 `python scripts/notion_editor.py fix` 自动修复。

### `configs/topics.yaml`

配置默认搜索关键词：

```yaml
keywords:
  - "AI agent"
  - "vibe coding"
  - "LLM"
```

### `configs/app.yaml`

调整研究/写作参数：

```yaml
research:
  topics_per_run: 10
  posts_per_topic: 30
  relevance_threshold: 3.0
writing:
  top_k_sources: 5
```

---

## 架构

### ComputerAgent — 纯视觉循环大脑

```
每次循环:
  1. SEE:   全屏截图 (macOS screencapture)
  2. THINK: LLM 分析截图 + 历史上下文 → 输出 JSON 动作计划
  3. ACT:   PyAutoGUI 执行动作（move/click/type/hotkey/scroll）
  4. VERIFY: 下一次循环的截图天然构成验证
  5. 循环直到任务完成 / 卡住 / 达到最大循环数
```

- observe + decide 合并为一次 LLM 调用
- 对话历史上下文，模型能看到页面变化
- 卡住检测：连续 8 次相同动作 → 终止
- LLM 输出归一化：坐标提取、文本提取、快捷键映射

### 执行器

- **拟人鼠标**：贝塞尔曲线 + 随机抖动 + 自适应速度
- **拟人输入**：随机打字间隔 + 偶尔思考停顿
- **坐标系统**：1000×1000 归一化 → 自动映射到实际分辨率

### 研究流程

```
DesktopXResearcher
  ├── discover()      搜索 X + 逐帖深度采集（边发现边采集）
  │     ├── _focus_browser()     确保浏览器窗口聚焦
  │     ├── _copy_post_url()     分享按钮 → Copy Link
  │     ├── _extract_post_content()  视觉提取正文/指标
  │     ├── _analyze_images()    点击打开图片 → 视觉分析
  │     ├── _read_comments()     3 轮滚动 → 提取评论
  │     ├── _find_metrics()      滚动查找隐藏指标
  │     └── _sync_to_notion()    同步到 Notion
  └── _go_back()       返回搜索结果
```

### 数据流

```
SQLite 本地存储
  ├── CollectedContent  采集的帖子（正文/指标/图片/评论）
  ├── Comment           评论内容
  ├── Reference         浏览/跳过的 URL 记录
  ├── Task              任务记录
  ├── UniversalDraft    通用草稿
  └── PlatformDraft     平台适配草稿
```

---

## 项目结构

```
app/
  cli/               Typer CLI 入口（美化 Rich 界面）
  core/              配置 · 错误 · 日志
  schemas/           数据模型
  llm/               LLM 客户端（OpenAI 兼容）
  desktop/           桌面级纯视觉控制
    computer_agent.py    核心 see-think-act-verify 循环
    executor.py          PyAutoGUI 执行器（人类化行为）
    observer.py          screencapture 全屏截图
    research_agent.py    X 深度调研 Agent
    publisher.py         X 发布器
    permissions.py       macOS 权限检查
  observer/          实时屏幕观察器
  analysis/          爆款风格挖掘
  writing/           内容生成
  integrations/      Notion API
  memory/            SQLite 本地存储
  platforms/         平台插件（可扩展）
scripts/
  notion_editor.py   Notion 数据库管理（inspect/fix/create）
configs/           YAML 配置
prompts/           LLM prompt 模板
data/              运行时数据（screenshots / drafts / cache / runs）
```

---

## 扩展

只需添加 `app/platforms/<name>/` 目录实现平台规则即可。核心视觉循环（ComputerAgent）无需修改。
