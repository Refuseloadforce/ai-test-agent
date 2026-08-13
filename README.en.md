# AI Config-Driven Desktop Automation Agent

[简体中文](README.md) | English

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Platform Windows](https://img.shields.io/badge/Platform-Windows%2010%2F11-lightgrey.svg)]()
[![CI](https://github.com/Refuseloadforce/ai-test-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/Refuseloadforce/ai-test-agent/actions)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

**Configure it, and it runs.** Everything — AI model, API key, execution parameters, task steps — lives in config files. Change the config, change the behavior; no code edits required.

- AI model: **DeepSeek API (`deepseek-v4-flash` by default)**, key configured in a file
- Web automation via **CDP DOM-level control** (no OCR needed); desktop apps located via **built-in Windows OCR**
- When something unexpected happens: automatic **screenshot + OCR + DOM diagnosis** so the AI can decide the next step
- No local LLMs (torch/transformers/Qwen2-VL removed) — no GPU, no model downloads

## Features

- 🧩 **Pure config-driven**: tasks, execution params, and credentials in `config/*.json`
- 🤖 **DeepSeek planning**: natural-language tasks → AI step planning; AI recovery with screen evidence on failure
- 🌐 **Web automation**: CDP-driven isolated Chrome instance, locate by CSS selector or visible text, Chinese text input
- 🖥️ **Desktop automation**: 15+ actions (launch apps, hotkeys, click, type, scroll, window focus…)
- 👁️ **OCR diagnosis**: screenshot reading + DOM snapshot, on-demand (`ocr_analyze`) or automatic on failure
- 📊 **Full reports**: per-step screenshots, JSON/Markdown reports, archived diagnosis evidence

## Quick Start

```bash
# 1. Install dependencies (ASCII-only comments; no GBK decoding issues on Windows pip)
pip install -r requirements.txt

# 2. Copy the config template and fill in your DeepSeek API key
copy config\config.example.json config\config.json
#    edit config/config.json → llm.api_key (or set the DEEPSEEK_API_KEY env var)

# 3. Preview the steps to be executed (does not touch your machine)
python demo.py --dry-run

# 4. Run for real (controls mouse & keyboard; move the mouse to the
#    top-left corner to emergency-stop)
python demo.py

# Run other example configs
python demo.py --config config/chrome_bing.json      # web: Bing search (CDP, no OCR)
python demo.py --config config/example_steps.json    # desktop: explicit steps only
python demo.py --config config/ocr_analyze.json      # OCR diagnosis example
```

## Configuration

Config files are JSON (template: `config/config.example.json`):

```jsonc
{
  "llm": {                          // AI model
    "api_key": "sk-your-key",       // DeepSeek API key (or env var DEEPSEEK_API_KEY)
    "base_url": "https://api.deepseek.com",
    "model": "deepseek-v4-flash",   // deepseek-v4-flash / deepseek-v4-pro / deepseek-chat / deepseek-reasoner
    "temperature": 0.2,
    "max_tokens": 4096
  },
  "browser": {                      // CDP browser (browser_* actions)
    "chrome_path": "",              // auto-detected when empty
    "debug_port": 9222,
    "profile_dir": "{project_root}\\.chrome-profile",
    "headless": false
  },
  "execution": {                    // execution parameters
    "max_steps": 50,
    "max_retries": 2,
    "wait_after_action": 0.8,
    "ai_plan": true,                // plan natural-language tasks with AI
    "ai_replan": true,              // AI recovery with screen evidence on failure
    "screenshot": true
  },
  "tasks": [                        // one or more tasks, executed in order
    {
      "name": "Task name",
      "task": "Natural-language description (AI plans it into steps)"
      // or explicit steps (configure what to execute):
      // "steps": [
      //   {"action": "open", "program": "notepad", "description": "Open Notepad"},
      //   {"action": "type", "text": "Hello World", "description": "Type"},
      //   {"action": "done", "description": "Finish"}
      // ]
    }
  ]
}
```

### Two task modes

| Mode | Config | Behavior |
|------|--------|----------|
| **Explicit steps** | `steps` array | Run exactly what is configured — deterministic, no AI, no API cost |
| **AI planning** | `task` string | DeepSeek plans the natural language into steps, then executes (`ai_plan=false` disables) |

### Available actions

| Action | Params | Description |
|--------|--------|-------------|
| `open` | `program`, `args` | Launch app: exe path (with args) or Start-menu search |
| `focus_window` | `title` | Bring a window to front by title (substring) |
| `hotkey` | `keys` | e.g. `["ctrl","s"]`, `["win","d"]` |
| `type` | `text` | Type text (Chinese via clipboard paste) |
| `click` / `double_click` / `right_click` | `x, y` | Mouse clicks at coordinates |
| `scroll` | `x, y, direction, clicks` | Scroll |
| `drag` | `x1, y1, x2, y2` | Drag |
| `wait` | `seconds` | Wait |
| `click_text` | `text`, `occurrence` | **OCR-locate text and click** (built-in Windows OCR) |
| `wait_text` | `text`, `timeout` | Poll OCR until text appears |
| `browser_open` | `url` | Open URL in the CDP Chrome instance |
| `browser_click` | `selector` | Click element by CSS selector (e.g. `#sb_form_q`) |
| `browser_click_text` | `text`, `occurrence` | Click page element by visible text (DOM, no OCR) |
| `browser_type` | `text` | Type into the focused input (auto-focus, Chinese OK) |
| `browser_press` | `key` | Press a key (enter/tab/escape/arrows…) |
| `browser_wait_text` | `text`, `timeout` | Wait until text appears in the DOM (no OCR) |
| `browser_eval` | `expr` | Evaluate JS and return the result |
| `ocr_analyze` | `question`, `ask_ai` | **OCR diagnosis**: screenshot → OCR → (optional) AI judges state and next step |
| `done` | - | Mark task finished |

> `click_text` / `wait_text` require `winsdk` (Windows only, already in requirements.txt).
> Note: low-contrast text (e.g. white on blue buttons) may not OCR reliably —
> use coordinate clicks or press Enter instead.

### Path placeholder

`{project_root}` in config values is replaced with the project root:

```json
{"action": "type", "text": "{project_root}\\results\\hello.txt", "description": "Type save path"}
```

## Web Automation (CDP, no OCR — verified end-to-end)

`config/chrome_bing.json`: open Bing → click the search box → type → Enter → verify:

```bash
python demo.py --config config/chrome_bing.json
```

Verified run (2026-08, Windows): 8 steps in **8 seconds**, DOM-level operation,
**zero OCR, zero hard-coded coordinates**: `#sb_form_q` click → type
"DeepSeek V4 自动化测试" → Enter → DOM detects the query on the results page →
JS reads the page title and counts 14 results.

How it works (`core/browser.py`, inspired by the DSH community plugin `dsh-browser-control`):

```
browser_* actions ──▶ CDP (Chrome DevTools Protocol)
                        ├─ Runtime.evaluate        locate (CSS selector / text)
                        ├─ Input.dispatchMouseEvent click
                        ├─ Input.insertText        type (Chinese OK)
                        └─ Page.navigate           navigate
```

- Runs an isolated Chrome instance (own user-data-dir, `--remote-debugging-port`) —
  never touches your daily browser; input is auto-routed to the foreground window
- More reliable than OCR: DOM is immune to fonts, colors, and screenshot scaling
- Advanced: reuse your daily Chrome login state by copying the profile (see dsh-browser-control's approach)

## When Things Go Wrong: OCR Diagnosis

On failure or unexpected states the framework **uses OCR to figure out the next step** (`core/diagnose.py`).

### 1. Automatic failure diagnosis (on by default)

When a step fails (with `execution.ai_replan: true`):

```
step fails → screenshot + OCR + DOM snapshot
          → evidence archived (diag_step_N_screen.png / _ocr.txt, logged)
          → AI judges from "failure reason + screen evidence" → recovery steps → executed
```

Verified (2026-08): an intentionally bogus selector failed → automatic diagnosis read the
Bing homepage → AI recovered with "click search box → type → Enter → verify" → recovery
steps executed → task succeeded.

### 2. On-demand `ocr_analyze`

Stop and look whenever the config needs to:

```json
{ "action": "ocr_analyze",
  "question": "What is on screen right now? What should the next step be?",
  "ask_ai": true }
```

Screenshot → OCR → logged to the report; with `ask_ai: true` the AI judges and records
its verdict (verified example: "Next step: press Enter to confirm the search, or click the
'deepseek' suggestion in the dropdown.").

> Without an API key, `ocr_analyze` and automatic diagnosis still write the OCR screen
> text into the report for human review.

## About AI Vision (Image Input)

**Verified finding**: the official DeepSeek API does **not** accept image input for
`deepseek-v4-pro` or `deepseek-v4-flash` — the call returns
`HTTP 400: unknown variant 'image_url', expected 'text'`. Third-party gateways may claim
vision support, but the official chat API does not expose it.

So this project "sees" screens two ways:
- **Desktop apps**: built-in Windows OCR (`core/ocr.py`) — screenshot → text → click center
- **Web pages**: CDP reads the DOM directly (`core/browser.py`, preferred) — no OCR at all

When the official API gains image support, upgrade to
"model sees screenshot → outputs control coordinates → click" (architecture already
reserves a swappable locator).

## Project Structure

```
ai-test-agent/
├── config/                     # example configs (copy config.example.json → config.json)
├── core/
│   ├── config.py               # config loading & validation
│   ├── llm.py                  # DeepSeek API client (plan / replan)
│   ├── executor.py             # action executor (runs exactly what is configured)
│   ├── ocr.py                  # Windows OCR wrapper (desktop click_text / wait_text)
│   ├── browser.py              # CDP browser control (browser_* actions, no OCR)
│   ├── diagnose.py             # screenshot + OCR + DOM diagnosis
│   └── agent.py                # task orchestration & reports
├── platforms/desktop.py        # screenshot + mouse/keyboard + window focus
├── tests/selftest.py           # 53 self-tests (fake platform / fake LLM / headless Chrome)
├── .github/                    # issue/PR templates + CI
├── results/                    # run artifacts (auto-generated, gitignored)
├── demo.py                     # entry point
├── requirements.txt
├── LICENSE                     # MIT
├── CHANGELOG.md
└── CONTRIBUTING.md
```

## FAQ

- **HTTP 401 key error**: check `llm.api_key` or the `DEEPSEEK_API_KEY` env var
- **HTTP 404 model not found**: switch `llm.model` to a model your account supports (e.g. `deepseek-chat`)
- **Execution too fast / flaky**: increase `execution.wait_after_action`
- **Don't want AI recovery**: set `execution.ai_replan = false`
- **Plan/step quality**: tweak the prompts in `llm.plan` / `llm.replan`, or use explicit `steps`

## Roadmap

- [x] Config-driven desktop automation (DeepSeek planning + explicit steps)
- [x] CDP web automation (selector/text locating, no OCR)
- [x] OCR diagnosis & automatic failure recovery
- [ ] Debug instance reusing the daily Chrome login state (profile copy)
- [ ] More browsers (Edge/Firefox)
- [ ] Vision-driven clicking once the official API supports images
- [ ] HTML test reports (Allure style)
- [ ] Scheduled & conditional triggers (file/HTTP/webhook)

## Contributing

Issues and PRs are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).
Run `python tests\selftest.py` before submitting (no real desktop or API key required).

## Acknowledgments

- CDP browser-control approach inspired by the DSH community plugin [dsh-browser-control](https://github.com/PangYiMing/dsh-browser-control)
- DeepSeek API integration follows the [official DeepSeek docs](https://api-docs.deepseek.com/)

## License

[MIT](LICENSE) © 2026 luffsama
