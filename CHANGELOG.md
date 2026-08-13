# 更新日志 / Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 格式，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [0.1.0] - 2026-08-14

首个开源版本。从"本地大模型（Qwen2-VL）GUI 测试框架"重构为
**配置驱动的桌面/网页自动化框架**（DeepSeek API + CDP + OCR）。

### Added

- 配置驱动架构：`config/*.json` 定义一切（密钥、模型、执行参数、任务），改配置即可改行为
- 两种任务模式：显式 `steps`（配置什么就执行什么）与自然语言 `task`（DeepSeek 规划）
- DeepSeek API 客户端（`core/llm.py`）：规划 / 补救规划 / 思考模式处理
- 桌面动作 16 种：open（exe 直启/开始菜单）、focus_window、hotkey、type、click 系列、
  scroll、drag、wait、click_text / wait_text（Windows OCR 定位）
- 网页动作 8 种：browser_open / browser_click / browser_click_text / browser_type /
  browser_press / browser_wait_text / browser_eval（CDP DOM 级控制，无 OCR）
- `ocr_analyze` 动作与失败自动诊断：截图 + OCR + DOM 摘要 → AI 综合判断下一步
- 运行报告：每任务 report.json / report.md + 每步截图 + 诊断证据存档
- 自测套件 `tests/selftest.py`（53 项：假平台、假 LLM、headless Chrome）
- 开源基建：MIT License、中英双语 README、贡献指南、CI（GitHub Actions）

### Removed

- 本地大模型依赖（torch / transformers / Qwen2-VL / Qwen2.5-7B），无需 GPU 与模型下载
- 规则解析器 `core/task_parser.py`（由配置驱动 + AI 规划取代）

### Fixed

- `requirements.txt` 纯 ASCII 化，解决 Windows pip 的 GBK 解码报错
- headful Chrome 忽略非前台窗口输入事件的坑（自动窗口置前）
- DeepSeek 思考模式下回复在 `reasoning_content` 导致空 content 的坑
