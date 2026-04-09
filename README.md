# SightOps

全屏视觉 AI 调研 Agent — 像真人一样操作你的 Mac，通过屏幕截图理解界面，用键鼠完成调研、写作、发布全流程。

**核心能力**：模型看截图 → 分析当前状态 → 决定下一步操作 → 执行键鼠动作 → 截图验证 → 循环。无硬编码导航序列，无 API 依赖，纯视觉闭环。

**技术栈**：Qwen3.6-Plus（视觉）· PyAutoGUI（全局控制）· Notion API · SQLite · Python 3.13

---

## 快速上手

```bash
# 1. 安装
pip install -e .

# 2. 系统授权：系统设置 > 隐私与安全性 > 屏幕录制 + 辅助功能 → 启用 Terminal
#    （授权后重启 Terminal）

# 3. 初始化
sightops setup

# 4. 编辑 .env，填入 LLM API Key
#    LLM_API_KEY=sk-xxx

# 5. 观察屏幕（可选，用于调试）
sightops observe

# 6. 开始调研
sightops research "AI agent" -n 5
```

---

## 详细配置

编辑 `.env` 文件，配置以下参数：

### LLM（必需）
```
LLM_API_KEY=sk-xxx
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen3.6-plus
```

### Notion（可选，用于同步调研内容）

1. 在 Notion 创建三个数据库：Research / Templates / Drafts
2. 把 Integration Share 到这三个库
3. 数据库 ID 填入 `.env`：

```
NOTION_TOKEN=ntn_xxx
NOTION_RESEARCH_DB_ID=xxx
NOTION_TEMPLATE_DB_ID=xxx
NOTION_DRAFT_DB_ID=xxx
```

---

## 使用流程

### Step 0 — 实时屏幕观察

```bash
# 打开观察窗口 — 全屏截图 + LLM 分析 + 操作计划
sightops observe

# 自定义间隔（默认 8 秒）
sightops observe -i 5
```

打开一个小窗口，每 8 秒：
1. **截全屏** → base64 编码
2. **LLM 分析** → 描述当前屏幕状态
3. **生成计划** → 下一步操作建议
4. **实时更新** → 窗口自动刷新截图和分析

> 适合调试调研流程、观察 LLM 如何理解屏幕、验证视觉定位效果。

### Step 1 — 调研（纯视觉闭环，每条实时记录）

```bash
# 用 topics.yaml 关键词搜索 X
sightops research

# 指定主题和数量
sightops research "AI agent" "vibe coding" --limit 10
```

**工作流程**：
1. ComputerAgent 通过截图识别当前应用和页面状态
2. 模型决定如何打开浏览器、导航到 X、搜索关键词
3. 滚动加载帖子，视觉识别每条内容
4. 逐个点开帖子详情，提取完整文本和互动数据
5. 相关性打分、摘要、标签 → **立刻保存**到 SQLite + 同步 Notion

> 紧急终止：鼠标移到屏幕左上角（PyAutoGUI FAILSAFE）

### Step 2 — 分析

```bash
# 对最近 7 天采集的内容做爆款风格分析
sightops analyze
```

### Step 3 — 写作

```bash
# 生成 X 长文
sightops write --type article --topic "AI Agent 趋势"

# 生成 Thread
sightops write --type thread

# 生成短帖
sightops write --type short_post
```

### Step 4 — 发布

```bash
# 查看待发布草稿
sightops status

# 发布最新草稿（纯视觉操作 X 发布）
sightops publish
```

---

## 架构

### ComputerAgent — 纯视觉循环大脑

```
每次循环:
  1. SEE:   全屏截图 (macOS screencapture)
  2. THINK: LLM 分析截图 + 历史上下文 → 输出 JSON 动作计划
  3. ACT:   PyAutoGUI 执行动作（move/click/type/hotkey/scroll）
  4. VERIFY: 下一次循环的截图天然构成验证（与预期对比）
  5. 循环直到任务完成 / 卡住 / 达到最大循环数
```

- **observe + decide 合并为一次 LLM 调用**，减少 API 调用次数
- **验证融入下一轮观察**，自然形成反馈环
- **卡住检测**：连续 N 次相同动作 → 触发 HumanReviewRequired
- **紧急停止**：PyAutoGUI FAILSAFE（鼠标移到左上角）

### 执行器

- 人类化鼠标移动：随机偏移 + easeOutQuad 曲线
- 人类化输入：随机打字间隔 + 偶尔思考停顿
- 支持动作：move/click/double_click/triple_click/right_click/type/hotkey/drag/scroll/wait/done/human

### 提示词系统

所有 LLM prompt 模板存放在 `prompts/` 目录：
- `vision/decide_next_action.md` — 桌面视觉控制主提示词
- `vision/observe_page.md` — 页面状态理解
- `vision/verify_result.md` — 动作验证
- `research/` — 调研相关提示词
- `writing/` — 写作相关提示词
- `analysis/` — 风格分析提示词

---

## 项目结构

```
app/
  core/              配置、错误、日志
  schemas/           数据模型
  llm/               Qwen3.6-Plus 客户端（OpenAI 兼容）
  desktop/           桌面级纯视觉控制
    computer_agent.py    核心 see-think-act-verify 循环
    observer.py          screencapture 全屏截图
    executor.py          PyAutoGUI 全局鼠标/键盘（人类化行为）
    action_planner.py    视觉模型 → 屏幕坐标动作计划
    research_agent.py    X 调研 Agent（发现 + 采集 + 实时记录）
    publisher.py         X 发布器
    permissions.py       macOS 权限检查
  observer/          实时屏幕观察器
    viewer.py              pywebview 实时观察窗口
  analysis/          爆款风格挖掘
  writing/           内容生成
  integrations/      Notion API
  assets/            图片下载
  memory/            SQLite 本地存储
  platforms/         平台插件（可扩展）
    x/                     X 平台规则
    base/                  平台抽象基类
  cli/               Typer CLI 入口
prompts/           LLM prompt 模板
configs/           YAML 配置
data/              运行时数据（screenshots / drafts / cache / runs）
```

## 扩展到其他平台

只需添加 `app/platforms/<name>/` 目录，实现平台规则即可。核心视觉循环（ComputerAgent）无需修改。
