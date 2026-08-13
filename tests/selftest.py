"""
自测脚本：验证核心链路，不操作真实电脑、不调用真实 API
  配置加载与校验 → 显式步骤执行 → AI 规划解析与执行 → 失败处理 → 报告生成

运行: python tests/selftest.py
"""

import sys
import os
import json
import shutil
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Windows 控制台默认 cp1252/GBK，中文输出会 UnicodeEncodeError（CI 上必崩）
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from PIL import Image
from loguru import logger
from core.config import load_config, resolve_text
from core.agent import TestAgent
from core.llm import DeepSeekClient

logger.remove()  # 静默日志，只看断言结果

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PASS = 0
FAIL = 0


def check(name: str, cond: bool, detail: str = ""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name} {detail}")


# ---------- 假平台：记录调用，不碰真实硬件 ----------

class FakePlatform:
    def __init__(self, ok_titles=()):
        self.calls = []
        self.ok_titles = set(ok_titles)

    def screenshot(self):
        return Image.new("RGB", (320, 200), "white")

    def wait(self, seconds):
        self.calls.append(("wait", seconds))

    def hotkey(self, *keys):
        self.calls.append(("hotkey", list(keys)))

    def type_text(self, text):
        self.calls.append(("type", text))

    def click(self, x, y):
        self.calls.append(("click", x, y))

    def double_click(self, x, y):
        self.calls.append(("double_click", x, y))

    def right_click(self, x, y):
        self.calls.append(("right_click", x, y))

    def scroll(self, x, y, clicks=3, direction="down"):
        self.calls.append(("scroll", x, y, clicks, direction))

    def drag(self, x1, y1, x2, y2):
        self.calls.append(("drag", x1, y1, x2, y2))

    def focus_window(self, title):
        self.calls.append(("focus_window", title))
        return title in self.ok_titles


# ---------- 假 LLM：复用真实的 JSON 解析/规范化逻辑 ----------

class FakeLLM:
    def __init__(self, plan_json: str = None, replan_json: str = None):
        self._parser = DeepSeekClient({"api_key": "sk-test"})
        self.plan_json = plan_json
        self.replan_json = replan_json
        self.plan_called_with = None
        self.replan_called_with = None
        self.replan_screen_info = None

    def plan(self, task_text, project_root):
        self.plan_called_with = task_text
        steps = self._parser._parse_json_array(self.plan_json)
        return self._parser._normalize_steps(steps, task_text)

    def replan(self, task_text, history, failed_step, error, screen_info=""):
        self.replan_called_with = error
        self.replan_screen_info = screen_info
        steps = self._parser._parse_json_array(self.replan_json)
        return self._parser._normalize_steps(steps, task_text)

    def chat(self, messages, max_tokens=300, thinking=None):
        return "综合判断结果：当前页面正常，下一步应点击搜索框。"


def make_agent(cfg: dict, fake_llm: FakeLLM = None, platform: FakePlatform = None):
    agent = TestAgent(cfg, platform=platform or FakePlatform())
    if fake_llm is not None:
        agent._llm = fake_llm  # 注入假 LLM
    return agent


# ---------- 测试 ----------

def test_config_validation():
    print("\n[1] 配置加载与校验")
    # 合法配置
    cfg = load_config(os.path.join(PROJECT_ROOT, "config", "example_steps.json"), PROJECT_ROOT)
    check("example_steps.json 加载成功", isinstance(cfg, dict) and len(cfg["tasks"]) == 2)
    # 非法动作类型
    bad = {"tasks": [{"name": "x", "steps": [{"action": "fly"}]}]}
    try:
        load_config.__globals__  # noqa
        from core.config import _validate
        _validate(bad)
        check("未知动作被拒绝", False)
    except ValueError:
        check("未知动作被拒绝", True)
    # 缺少 task 和 steps
    try:
        from core.config import _validate
        _validate({"tasks": [{"name": "x"}]})
        check("缺少 task/steps 被拒绝", False)
    except ValueError:
        check("缺少 task/steps 被拒绝", True)


def test_placeholder():
    print("\n[2] {project_root} 占位符替换")
    out = resolve_text("{project_root}\\results\\hello.txt", "C:\\proj")
    check("占位符替换", out == "C:\\proj\\results\\hello.txt", out)


def test_explicit_steps():
    print("\n[3] 显式步骤模式（配置什么就执行什么）")
    with tempfile.TemporaryDirectory() as tmp:
        cfg = load_config(os.path.join(PROJECT_ROOT, "config", "example_steps.json"), tmp)
        platform = FakePlatform()
        agent = make_agent(cfg, platform=platform)
        results = agent.run_all()
        r1 = results[0]
        check("任务1成功", r1["status"] == "success", r1.get("reason", ""))
        check("步骤数=8", len(r1["steps"]) == 8, str(len(r1["steps"])))
        # 执行序列
        types = [c for c in platform.calls if c[0] == "type"]
        check("输入了 Hello World", any(c[1] == "Hello World" for c in types))
        check("输入了占位符解析后的路径",
              any(c[1] == os.path.join(tmp, "results", "hello_steps.txt") for c in types),
              str(types))
        check("按了 ctrl+s", ("hotkey", ["ctrl", "s"]) in platform.calls)
        check("按了 enter", ("hotkey", ["enter"]) in platform.calls)
        # 报告文件
        rdir = r1["task_dir"]
        check("report.json 生成", os.path.exists(os.path.join(rdir, "report.json")))
        check("report.md 生成", os.path.exists(os.path.join(rdir, "report.md")))
        check("截图生成", any(f.startswith("step_") and f.endswith(".png") for f in os.listdir(rdir)))
        check("summary.json 生成", os.path.exists(os.path.join(agent.run_dir, "summary.json")))
        # 任务2（快捷键）也成功
        check("任务2成功", results[1]["status"] == "success", results[1].get("reason", ""))


def test_ai_plan():
    print("\n[4] AI 规划模式（假 LLM）")
    plan_json = """```json
[{"action":"open","program":"记事本","description":"打开记事本"},
 {"action":"type","text":"Hello World","description":"输入"},
 {"action":"hotkey","keys":["ctrl","s"],"description":"保存"},
 {"action":"done","description":"完成"}]
```"""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = load_config(os.path.join(PROJECT_ROOT, "config", "config.example.json"), tmp)
        fake = FakeLLM(plan_json)
        platform = FakePlatform()
        agent = make_agent(cfg, fake, platform)
        results = agent.run_all()
        r = results[0]
        check("任务成功", r["status"] == "success", r.get("reason", ""))
        check("AI 收到自然语言任务", fake.plan_called_with == cfg["tasks"][0]["task"])
        check("步骤含 done", r["steps"][-1]["action"]["action"] == "done")
        check("open 动作被翻译为 win+搜索+enter",
              ("hotkey", ["win"]) in platform.calls and ("hotkey", ["enter"]) in platform.calls)


def test_failure_and_replan():
    print("\n[5] 失败处理 + AI 补救")
    steps = [
        {"action": "type", "text": "ok", "description": "正常"},
        {"action": "click", "x": 1, "y": 2, "description": "会失败的动作"},
        {"action": "done", "description": "完成"},
    ]
    with tempfile.TemporaryDirectory() as tmp:
        # 5.1 失败且不补救 → failed
        cfg = {"tasks": [{"name": "t", "steps": steps}],
               "execution": {"ai_replan": False, "screenshot": False}, "_project_root": tmp}
        class BoomPlatform(FakePlatform):
            def click(self, x, y):
                raise RuntimeError("boom")
        agent = make_agent(cfg, platform=BoomPlatform())
        r = agent.run_task(cfg["tasks"][0], 1)
        check("失败步骤导致任务 failed", r["status"] == "failed", r.get("reason", ""))
        check("失败原因含 boom", "boom" in r.get("reason", ""), r.get("reason", ""))

        # 5.2 失败后 AI 补救成功 → success
        replan_json = '[{"action":"hotkey","keys":["enter"],"description":"补救"},{"action":"done","description":"完成"}]'
        fake = FakeLLM(plan_json=None, replan_json=replan_json)
        cfg2 = {"tasks": [{"name": "t", "steps": steps}],
                "execution": {"ai_replan": True, "screenshot": False}, "_project_root": tmp}
        # 失败诊断的 OCR 打桩：返回假屏幕文字，验证传给 AI 的屏幕证据
        import core.diagnose as diagnose_mod
        orig_ocr = diagnose_mod.ocr_screen
        diagnose_mod.ocr_screen = lambda image, **kw: [{"text": "屏幕上有一个弹窗", "x": 10, "y": 10, "w": 60, "h": 20}]
        try:
            agent2 = make_agent(cfg2, fake, BoomPlatform())
            r2 = agent2.run_task(cfg2["tasks"][0], 1)
        finally:
            diagnose_mod.ocr_screen = orig_ocr
        check("AI 补救后任务成功", r2["status"] == "success", r2.get("reason", ""))
        check("补救收到了失败原因", fake.replan_called_with == "boom", str(fake.replan_called_with))
        check("补救收到了 OCR 屏幕证据", fake.replan_screen_info and "弹窗" in fake.replan_screen_info,
              str(fake.replan_screen_info)[:100])
        check("日志记录了 ocr_diagnose 事件",
              any(e.get("event") == "ocr_diagnose" for e in agent2.log), str(agent2.log)[:120])


def test_dry_run():
    print("\n[6] dry-run 预览")
    import contextlib
    import io
    from demo import preview
    with tempfile.TemporaryDirectory() as tmp:
        cfg = load_config(os.path.join(PROJECT_ROOT, "config", "config.example.json"), tmp)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            preview(cfg)
        out = buf.getvalue()
        check("dry-run 输出任务名", "记事本输入并保存" in out)
        check("dry-run 提示 AI 规划", "AI 规划" in out)


def test_click_text_and_wait_text():
    print("\n[7] click_text / wait_text（mock OCR）")
    import core.executor as executor_mod
    from core.executor import Executor

    def make_executor():
        cfg = {"execution": {"wait_after_action": 0.1}, "_project_root": "C:\\proj"}
        return Executor(FakePlatform(), cfg), cfg

    # 7.1 click_text 找到文字 → 点击中心坐标
    ex, _ = make_executor()
    executor_mod.find_text = lambda text, occurrence=0, **kw: {
        "text": text, "cx": 100, "cy": 200, "x": 90, "y": 195, "w": 20, "h": 10}
    ok, err = ex.execute_step({"action": "click_text", "text": "百度一下"})
    check("click_text 成功", ok, err)
    check("click_text 点击了中心坐标", ("click", 100, 200) in ex.platform.calls, str(ex.platform.calls))

    # 7.2 click_text 找不到文字 → 失败
    ex, _ = make_executor()
    executor_mod.find_text = lambda text, occurrence=0, **kw: None
    ok, err = ex.execute_step({"action": "click_text", "text": "不存在的东西"})
    check("click_text 找不到文字时失败", not ok and "未找到" in err, err)

    # 7.3 wait_text 轮询直到出现
    ex, _ = make_executor()
    calls = {"n": 0}
    def flaky(text, occurrence=0, **kw):
        calls["n"] += 1
        return {"cx": 1, "cy": 1} if calls["n"] >= 3 else None
    executor_mod.find_text = flaky
    ok, err = ex.execute_step({"action": "wait_text", "text": "目标", "timeout": 5, "interval": 0.1})
    check("wait_text 等到文字出现", ok, err)
    check("wait_text 轮询了多次", calls["n"] >= 3, str(calls["n"]))

    # 7.4 wait_text 超时 → 失败
    ex, _ = make_executor()
    executor_mod.find_text = lambda text, occurrence=0, **kw: None
    ok, err = ex.execute_step({"action": "wait_text", "text": "永不出现", "timeout": 0.5, "interval": 0.1})
    check("wait_text 超时失败", not ok and "超时" in err, err)

    # 7.5 open 带 args（exe 路径）
    ex, _ = make_executor()
    import os
    exe = os.path.join(tempfile.gettempdir(), "fake_prog.exe")
    with open(exe, "w") as f:
        f.write("")  # 只需要存在
    recorded = {}
    orig_popen = executor_mod.subprocess.Popen
    executor_mod.subprocess.Popen = lambda cmd, **kw: recorded.update(cmd=cmd) or True
    try:
        ok, err = ex.execute_step({"action": "open", "program": exe, "args": ["--new-window", "https://x.com"]})
        check("open 带 args 启动成功", ok, err)
        check("open 传入了 args", recorded.get("cmd") == [exe, "--new-window", "https://x.com"], str(recorded.get("cmd")))
    finally:
        executor_mod.subprocess.Popen = orig_popen
        os.unlink(exe)


    # 7.6 focus_window 成功/失败
    from core.executor import Executor
    cfg7 = {"execution": {"wait_after_action": 0.1}, "_project_root": "C:\\proj"}
    ex = Executor(FakePlatform(ok_titles=["百度"]), cfg7)
    ok, err = ex.execute_step({"action": "focus_window", "title": "百度"})
    check("focus_window 成功", ok, err)
    check("focus_window 调用了平台", ("focus_window", "百度") in ex.platform.calls)
    ok, err = ex.execute_step({"action": "focus_window", "title": "不存在的窗口"})
    check("focus_window 找不到窗口时失败", not ok and "找不到窗口" in err, err)


def test_browser_cdp():
    print("\n[8] CDP 浏览器控制（headless Chrome，DOM 级无 OCR）")
    try:
        from core.browser import BrowserManager
    except ImportError as e:
        print(f"  ✗ 浏览器模块不可用: {e}")
        global FAIL
        FAIL += 1
        return

    import urllib.parse
    import random
    cfg = {
        "_project_root": tempfile.gettempdir(),
        "browser": {
            "headless": True,
            "debug_port": 9300 + random.randint(0, 200),
            "profile_dir": os.path.join(tempfile.gettempdir(), f"dsh_selftest_{random.randint(0, 99999)}"),
        },
    }
    html = """
    <html><body>
      <button onclick="document.title='CLICKED'">点我</button>
      <button id="btn2" onclick="this.textContent='已点击二号'">第二按钮</button>
      <input id="box" placeholder="请输入关键词">
      <div id="status">准备就绪</div>
    </body></html>
    """
    url = "data:text/html;charset=utf-8," + urllib.parse.quote(html)
    bm = BrowserManager(cfg)
    try:
        bm.navigate(url)
        check("browser_open 页面加载", True)
        check("browser_wait_text 找到文字", bm.wait_text("准备就绪", timeout=10))
        check("browser_click_text 点击按钮",
              bm.click_text("点我") and bm.eval_js("document.title") == "CLICKED",
              bm.eval_js("document.title"))
        check("browser_click_text 定位占位符输入框", bm.click_text("请输入关键词"))
        bm.type_text("你好世界")
        check("browser_type 输入中文", bm.eval_js("document.getElementById('box').value") == "你好世界",
              bm.eval_js("document.getElementById('box').value"))
        check("browser_click 按选择器点击",
              bm.click_selector("#btn2") and bm.eval_js("document.getElementById('btn2').innerText") == "已点击二号",
              bm.eval_js("document.getElementById('btn2').innerText"))
        check("browser_eval 执行 JS", bm.eval_js("1+1") == "2", bm.eval_js("1+1"))
        check("browser_press Enter", bm.press("Enter"))
        check("browser_wait_text 找不到时返回 False", not bm.wait_text("绝不存在的文字", timeout=2))
    finally:
        bm.close()


def test_ocr_analyze():
    print("\n[9] ocr_analyze 动作（OCR 综合诊断 + AI 判断）")
    from core.executor import Executor
    import core.diagnose as diagnose_mod

    cfg9 = {"execution": {"wait_after_action": 0.1}, "_project_root": "C:\\proj"}
    fake_words = [{"text": "页面显示：登录失败，请重试", "x": 10, "y": 10, "w": 100, "h": 20}]
    orig_ocr = diagnose_mod.ocr_screen

    # 9.1 不带 AI：只做 OCR 诊断并记录事件
    diag_log = []
    ex = Executor(FakePlatform(), cfg9, diag=diag_log)
    diagnose_mod.ocr_screen = lambda image, **kw: fake_words
    try:
        ok, err = ex.execute_step({"action": "ocr_analyze", "question": "当前状态？"})
        check("ocr_analyze 成功", ok, err)
        check("诊断事件已记录", len(diag_log) == 1 and diag_log[0]["event"] == "ocr_analyze", str(diag_log))
        check("诊断事件含 OCR 文字", "登录失败" in diag_log[0]["data"]["ocr_text"], str(diag_log[0]["data"])[:100])
        check("未配置 AI 时不调用", "ai_judgment" not in diag_log[0]["data"])

        # 9.2 带 ask_ai：AI 综合判断结果进入事件
        diag_log2 = []
        ex2 = Executor(FakePlatform(), cfg9, diag=diag_log2, llm_provider=lambda: FakeLLM())
        ok, err = ex2.execute_step({"action": "ocr_analyze", "question": "下一步怎么做？", "ask_ai": True})
        check("ocr_analyze + ask_ai 成功", ok, err)
        check("AI 判断已记录", "ai_judgment" in diag_log2[0]["data"]
              and "综合判断" in diag_log2[0]["data"]["ai_judgment"], str(diag_log2[0]["data"]).replace("'", "")[:120])
    finally:
        diagnose_mod.ocr_screen = orig_ocr


if __name__ == "__main__":
    test_config_validation()
    test_placeholder()
    test_explicit_steps()
    test_ai_plan()
    test_failure_and_replan()
    test_dry_run()
    test_click_text_and_wait_text()
    test_browser_cdp()
    test_ocr_analyze()
    print(f"\n结果: {PASS} 通过, {FAIL} 失败")
    sys.exit(1 if FAIL else 0)
