# AI 配置化桌面自动化 Agent

[English](README.en.md) | 简体中文

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Platform Windows](https://img.shields.io/badge/Platform-Windows%2010%2F11-lightgrey.svg)]()
[![CI](https://github.com/Refuseloadforce/ai-test-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/Refuseloadforce/ai-test-agent/actions)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

**配置什么就执行什么**：所有行为（AI 模型、密钥、执行参数、任务步骤）都在配置文件里，改配置即可，无需改代码。

- AI 模型：**DeepSeek API（默认 `deepseek-v4-flash`）**，密钥在配置文件里填
- 网页自动化走 **CDP DOM 级控制**（无需 OCR）；桌面应用走 **Windows 自带 OCR** 定位
- 遇到"不会的情况"：自动**截图 + OCR + DOM 综合诊断**，让 AI 判断下一步
- 不再依赖本地大模型（已移除 torch/transformers/Qwen2-VL），无需 GPU、无需下载模型

## 功能特性

- 🧩 **纯配置驱动**：任务列表、执行参数、模型密钥全部在 `config/*.json`，零代码改动
- 🤖 **DeepSeek 规划**：自然语言任务 → AI 分解为步骤；失败时 AI 带屏幕证据补救
- 🌐 **网页自动化**：CDP 控制独立 Chrome 实例，按 CSS 选择器/页面文字定位，中文输入
- 🖥️ **桌面自动化**：15+ 种动作（打开程序/快捷键/点击/输入/滚动/窗口置前…）
- 👁️ **OCR 综合诊断**：截图读屏 + DOM 摘要，`ocr_analyze` 主动诊断或失败自动诊断
- 📊 **完整报告**：每步截图、JSON/Markdown 报告、诊断证据存档

## 快速开始

```bash
# 1. 安装依赖（纯 ASCII 注释，Windows 下不会再有编码报错）
pip install -r requirements.txt

# 2. 复制配置模板，填入你的 DeepSeek API 密钥
copy config\config.example.json config\config.json
#    编辑 config/config.json → llm.api_key（或设置环境变量 DEEPSEEK_API_KEY）

# 3. 预览将执行的步骤（不操作电脑）
python demo.py --dry-run

# 4. 正式执行（会控制鼠标键盘，鼠标移到屏幕左上角可紧急停止）
python demo.py

# 运行其他示例配置
python demo.py --config config/chrome_bing.json      # 网页：必应搜索（CDP 无 OCR）
python demo.py --config config/example_steps.json    # 桌面：纯配置显式步骤
python demo.py --config config/ocr_analyze.json      # OCR 综合诊断示例
```

## 配置文件

配置文件是 JSON，结构如下（`config/config.json`，模板见 `config/config.example.json`）：

```jsonc
{
  "llm": {                        // AI 模型配置
    "api_key": "sk-你的密钥",      // DeepSeek API 密钥（也可用环境变量 DEEPSEEK_API_KEY）
    "base_url": "https://api.deepseek.com",  // API 地址，可改成代理
    "model": "deepseek-v4-flash", // 模型名：deepseek-v4-flash / deepseek-v4-pro / deepseek-chat / deepseek-reasoner
    "temperature": 0.2,
    "max_tokens": 4096
  },
  "execution": {                  // 执行参数
    "max_steps": 50,              // 单任务最大步骤数
    "max_retries": 2,             // 每步失败重试次数
    "wait_after_action": 0.8,     // 每步执行后等待秒数（稳定性）
    "ai_plan": true,              // 自然语言任务是否用 AI 规划
    "ai_replan": true,            // 步骤失败后是否让 AI 补救规划
    "screenshot": true            // 每步截图存档
  },
  "tasks": [                      // 任务列表（可配置任意多个，按顺序执行）
    {
      "name": "任务名",
      "task": "自然语言任务描述（AI 规划成步骤）"
      // 或显式步骤（配置什么就执行什么）：
      // "steps": [
      //   {"action": "open", "program": "记事本", "description": "打开记事本"},
      //   {"action": "type", "text": "Hello World", "description": "输入内容"},
      //   {"action": "done", "description": "完成"}
      // ]
    }
  ]
}
```

### 两种任务模式

| 模式 | 配置方式 | 行为 |
|------|----------|------|
| **显式步骤** | `steps` 数组 | 配置什么就执行什么，完全确定性，不需要 AI、不消耗 API 额度 |
| **AI 规划** | `task` 字符串 | DeepSeek 把自然语言规划为步骤后执行（`ai_plan=false` 时禁用） |

### 可用动作（steps 里可配置的全部动作）

| 动作 | 参数 | 说明 |
|------|------|------|
| `open` | `program`, `args` | 打开程序：exe 路径直接启动（可带参数，如 `["--new-window","https://..."]`），否则开始菜单搜索 |
| `focus_window` | `title` | 按窗口标题（子串匹配）将窗口置前、恢复最小化（防止被其他窗口遮挡） |
| `hotkey` | `keys` | 快捷键，如 `["ctrl","s"]`、`["win","d"]` |
| `type` | `text` | 输入文字（支持中文，走剪贴板粘贴） |
| `click` | `x, y` | 单击坐标 |
| `double_click` | `x, y` | 双击坐标 |
| `right_click` | `x, y` | 右键坐标 |
| `scroll` | `x, y, direction, clicks` | 滚动 |
| `drag` | `x1, y1, x2, y2` | 拖拽 |
| `wait` | `seconds` | 等待 |
| `click_text` | `text`, `occurrence`, `click` | **OCR 定位文字并点击**（Windows 自带 OCR，无需装服务）：屏幕截图 → 找到文字 → 点击其中心 |
| `wait_text` | `text`, `timeout` | **轮询 OCR 直到文字出现**（用于验证页面加载、结果出现等） |
| `browser_open` | `url` | **浏览器打开网址**（CDP 驱动独立 Chrome 实例，DOM 级） |
| `browser_click` | `selector` | **按 CSS 选择器点击网页元素**（如 `#sb_form_q`） |
| `browser_click_text` | `text`, `occurrence` | **按页面文字点击网页元素**（DOM 匹配，无 OCR） |
| `browser_type` | `text` | 向网页输入框输入文字（自动聚焦，支持中文） |
| `browser_press` | `key` | 按单个键（enter/tab/escape/方向键等） |
| `browser_wait_text` | `text`, `timeout` | **等待网页出现文字**（DOM 轮询，无 OCR） |
| `browser_eval` | `expr` | 执行 JS 并返回结果（如统计结果数、读标题） |
| `ocr_analyze` | `question`, `ask_ai` | **OCR 综合诊断**：截图 → OCR 读屏 →（可选）AI 综合判断当前状态和下一步 |
| `done` | - | 标记任务完成 |

> `click_text` / `wait_text` 依赖 `winsdk`（requirements.txt 已包含，仅 Windows 生效）。
> 提示：界面上的文字如果颜色对比度低（如白字蓝底按钮），OCR 可能识别不到，
> 可改用坐标点击或回车键提交。

### 路径占位符

配置中的 `{project_root}` 会被替换为项目根目录（如 `C:\workspace\ai-test-agent`），
保存文件、打开路径等场景直接写：

```json
{"action": "type", "text": "{project_root}\\results\\hello.txt", "description": "输入保存路径"}
```

### 密钥配置

- 方式一（推荐）：`config/config.json` → `llm.api_key`
- 方式二：环境变量 `DEEPSEEK_API_KEY`（配置里留空时生效）

> 只有任务需要 AI（自然语言规划/失败补救）时才必须填密钥；纯 `steps` 任务不需要。

## 项目结构

```
ai-test-agent/
├── config/
│   ├── config.example.json    # 配置模板（复制为 config.json 后填写密钥）
│   ├── example_steps.json     # 显式步骤模式示例
│   ├── chrome_bing.json       # 网页自动化示例：Chrome + 必应搜索（CDP 无 OCR）
│   ├── ocr_analyze.json       # OCR 综合诊断示例
│   └── netease.json           # 打开网易云音乐示例
├── core/
│   ├── config.py              # 配置加载与校验
│   ├── llm.py                 # DeepSeek API 客户端（规划/补救）
│   ├── executor.py            # 动作执行器（严格按配置执行）
│   ├── ocr.py                 # Windows OCR 封装（桌面 click_text/wait_text）
│   ├── browser.py             # CDP 浏览器控制（网页 browser_* 动作，无 OCR）
│   ├── diagnose.py            # 截图+OCR+DOM 综合诊断（失败自动诊断/ocr_analyze）
│   └── agent.py               # 任务编排 + 报告
├── platforms/
│   └── desktop.py             # PC 端截图 + 鼠标键盘控制 + 窗口置前
├── tests/
│   └── selftest.py            # 自测（假平台/假 LLM/headless Chrome，不碰真实硬件）
├── .github/                   # Issue/PR 模板 + CI
├── results/                   # 运行结果（自动生成，已 gitignore）
├── demo.py                    # 入口
├── requirements.txt           # 依赖（已去除本地模型依赖）
├── LICENSE                    # MIT
├── CHANGELOG.md
└── CONTRIBUTING.md
```

## 网页自动化（CDP 直控，无 OCR，已实测通过）

`config/chrome_bing.json`：打开 Chrome → 必应 → 点搜索框 → 输入 → 回车 → 验证结果：

```bash
python demo.py --config config/chrome_bing.json
```

实测流程（2026-08 本机）：8 步全过，**8 秒完成**，全程 DOM 级操作、**零 OCR、零硬编码坐标**：
选择器点击 `#sb_form_q` → 输入"DeepSeek V4 自动化测试" → 回车 → DOM 检测到查询词出现在结果页
→ JS 读取页面标题（`DeepSeek V4 自动化测试 - 搜索`）和结果条数（14 条）。

原理（`core/browser.py`，参考 DSH 社区插件 dsh-browser-control 的 CDP 方案）：

```
浏览器_* 动作 ──▶ CDP (Chrome DevTools Protocol)
                      ├─ Runtime.evaluate  定位元素（CSS 选择器 / 页面文字）
                      ├─ Input.dispatchMouseEvent  点击
                      ├─ Input.insertText   输入（支持中文）
                      └─ Page.navigate      导航
```

要点：
- 用**独立 user-data-dir**（`.chrome-profile/`）+ `--remote-debugging-port=9222` 启动调试实例，
  不干扰日常浏览器；窗口被其他窗口遮挡时输入会被忽略，框架会自动把调试窗口置前
- **比 OCR 更可靠**：`browser_click_text`/`browser_wait_text` 直接读 DOM，不受字体、
  颜色、截图分辨率影响（百度首页占位符是轮播热词、新会话不渲染搜索框——OCR 和固定文字
  都会踩坑，所以示例用必应）
- 可选进阶：复用日常 Chrome 登录态（把默认 profile 复制为调试 profile，见 dsh-browser-control 思路）

## 遇到"不会的情况"：OCR 综合诊断

当步骤失败、页面状态看不懂时，框架会**自动用 OCR 综合判断下一步**（`core/diagnose.py`）：

### 1. 失败自动诊断（无需配置，开箱即用）

步骤执行失败后（`execution.ai_replan: true` 时）：

```
步骤失败 → 截图 + OCR 读屏 + DOM 摘要（浏览器场景）
        → 诊断证据存档（diag_step_N_screen.png / _ocr.txt，写入日志）
        → AI 基于"失败原因 + 屏幕证据"综合判断 → 输出补救步骤 → 自动执行
```

实测（2026-08）：故意配置不存在的选择器 → 自动诊断看到必应首页 →
AI 补救为"点击搜索框→输入→回车→验证结果页" → 补救步骤被执行 → 任务恢复成功。

### 2. 主动诊断动作 `ocr_analyze`

配置里随时可以在不确定的时候"停下来看一眼"：

```json
{ "action": "ocr_analyze",
  "question": "当前页面处于什么状态？要完成搜索任务，下一步应该做什么？",
  "ask_ai": true }
```

截图 → OCR → 写入诊断日志（报告里可见）→ `ask_ai: true` 时 AI 综合判断并记录。
实测判断示例："下一步：直接按回车键确认搜索，或点击下拉建议中的 deepseek 选项。"

> 即使不配置 AI 密钥，`ocr_analyze` 和失败自动诊断也会把 OCR 屏幕文字写进报告，
> 供人工判断。

## 关于 AI 视觉（图片识别）

**当前结论（已实测）**：DeepSeek 官方 API 的 `deepseek-v4-pro` 和 `deepseek-v4-flash`
**都不支持图片输入**——直接调用返回 `HTTP 400: unknown variant 'image_url', expected 'text'`。
网上声称"V4 Pro 有图像能力"的是第三方代理/网关，官方 chat API 未开放。

因此本项目"看屏幕"有两条路：
- **桌面应用**：Windows 自带 OCR（`core/ocr.py`）——截图 → OCR 识别文字 → 点击中心
- **网页**：CDP 直接读 DOM（`core/browser.py`，首选）——按选择器/文字定位元素，**完全不需要 OCR**

等官方 API 支持图片后，可以升级为"模型看截图 → 输出控件坐标 → 点击"（架构已预留，只需替换定位器）。

## 运行结果

每次运行生成 `results/<时间戳>/`：

```
results/20260505_123000/
├── summary.json              # 运行总览（所有任务）
├── 01_任务名/
│   ├── report.json           # 结构化报告
│   ├── report.md             # 可读报告
│   └── step_01_try_01.png    # 每步截图
└── 02_另一个任务/...
```

## 常见问题

- **401 密钥错误**：检查 `llm.api_key` 或环境变量 `DEEPSEEK_API_KEY`
- **404 模型不存在**：`llm.model` 改成你的账号支持的模型（如 `deepseek-chat`）
- **执行太快要慢一点**：调大 `execution.wait_after_action`
- **不想让 AI 补救**：`execution.ai_replan = false`
- **提示词/步骤不理想**：直接改 `llm.plan` / `llm.replan` 里的提示词，或改用显式 `steps`

## 路线图

- [x] 配置驱动的桌面自动化（DeepSeek 规划 + 显式步骤）
- [x] CDP 网页自动化（选择器/文字定位，无 OCR）
- [x] OCR 综合诊断与失败自动补救
- [ ] 复用日常 Chrome 登录态的调试实例（profile 复制方案）
- [ ] 更多浏览器支持（Edge/Firefox）
- [ ] 官方 API 支持图片后：模型看截图 → 输出控件坐标 → 点击
- [ ] HTML 测试报告（Allure 风格）
- [ ] 定时任务与条件触发（文件/HTTP/webhook 监听）

## 如何贡献

欢迎提交 Issue 和 Pull Request！详见 [贡献指南](CONTRIBUTING.md)。

- 新增动作实现清单见 CONTRIBUTING.md
- 自测：`python tests\selftest.py`（53 项，无需真实桌面与 API 密钥）

## 致谢

- 浏览器控制方案参考 DSH 社区插件 [dsh-browser-control](https://github.com/PangYiMing/dsh-browser-control) 的 CDP 思路
- DeepSeek API 集成参考 [DeepSeek 官方文档](https://api-docs.deepseek.com/)

## License

[MIT](LICENSE) © 2026 luffsama
