"""
浏览器控制模块（Chrome DevTools Protocol，DOM 级操作，无需 OCR）
参考 DSH 社区插件 dsh-browser-control 的 CDP 方案（登录态复用思路见 README 注释）

原理：
  1. 用独立 user-data-dir + --remote-debugging-port 启动 Chrome（不影响日常浏览器）
  2. 通过 WebSocket 连接页面目标，用 Runtime.evaluate 执行 JS 定位元素（按文字/占位符）
  3. 用 Input.dispatchMouseEvent / Input.insertText 执行真实点击和输入

依赖: requests + websocket-client
"""

import json
import os
import subprocess
import time
import ctypes
import requests
from websocket import create_connection, WebSocketTimeoutException
from loguru import logger

_PID_FILE = "dsh-browser.pid"


def find_chrome() -> str:
    """常见路径自动探测 Chrome"""
    candidates = [
        os.environ.get("LOCALAPPDATA", "") + r"\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.environ.get("PROGRAMFILES", "") + r"\Google\Chrome\Application\chrome.exe",
    ]
    for p in candidates:
        if p and os.path.exists(p):
            return p
    raise RuntimeError("未找到 Chrome，请在配置 browser.chrome_path 指定路径")


# 元素定位 JS：按可见文字/占位符找元素并返回屏幕中心坐标
_FIND_ELEMENT_JS = r"""
(function(text, occ) {
  var wanted = String(text).toLowerCase();
  var all = document.querySelectorAll(
    'button, a, input, textarea, select, [role="button"], [role="link"], [role="textbox"], label, span, div, li, h1, h2, h3');
  var cands = [];
  for (var i = 0; i < all.length; i++) {
    var el = all[i];
    if (el.children.length > 4) continue;  // 跳过大容器
    var t = (el.innerText || el.textContent || el.getAttribute('placeholder') || el.value || '').trim();
    if (t && t.toLowerCase().indexOf(wanted) >= 0 && t.length <= wanted.length + 40) {
      var r = el.getBoundingClientRect();
      if (r.width > 0 && r.height > 0 && r.bottom > 0 && r.top < window.innerHeight) {
        cands.push(el);
      }
    }
  }
  if (!cands.length) return {found: false};
  var idx = occ < 0 ? cands.length + occ : occ;
  if (idx < 0 || idx >= cands.length) return {found: false, reason: 'occurrence out of range'};
  var el = cands[idx];
  el.scrollIntoView({block: 'center'});
  var r = el.getBoundingClientRect();
  return {found: true, x: r.x + r.width / 2, y: r.y + r.height / 2,
          tag: el.tagName, text: (el.innerText || el.getAttribute('placeholder') || '').trim().slice(0, 40)};
})('%s', %d)
"""

_WAIT_TEXT_JS = r"""
(function(text) {
  var wanted = String(text).toLowerCase();
  var body = document.body ? document.body.innerText : '';
  if (body.toLowerCase().indexOf(wanted) >= 0) return true;
  var phs = document.querySelectorAll('[placeholder]');
  for (var i = 0; i < phs.length; i++) {
    if ((phs[i].getAttribute('placeholder') || '').toLowerCase().indexOf(wanted) >= 0) return true;
  }
  var inputs = document.querySelectorAll('input');
  for (var j = 0; j < inputs.length; j++) {
    if ((inputs[j].value || '').toLowerCase().indexOf(wanted) >= 0) return true;
  }
  return false;
})('%s')
"""

# 元素定位 JS：按 CSS 选择器找元素并返回屏幕中心坐标
_FIND_SELECTOR_JS = r"""
(function(sel) {
  var el;
  try { el = document.querySelector(sel); } catch (e) { return {found: false, reason: 'bad selector'}; }
  if (!el) return {found: false};
  el.scrollIntoView({block: 'center'});
  var r = el.getBoundingClientRect();
  if (!(r.width > 0 && r.height > 0)) return {found: false, reason: 'not visible'};
  return {found: true, x: r.x + r.width / 2, y: r.y + r.height / 2,
          tag: el.tagName, text: (el.innerText || el.getAttribute('placeholder') || '').trim().slice(0, 40)};
})('%s')
"""


_KEYS = {
    "enter": (13, "Enter", "Enter"), "tab": (9, "Tab", "Tab"), "escape": (27, "Escape", "Escape"),
    "backspace": (8, "Backspace", "Backspace"), "delete": (46, "Delete", "Delete"),
    "space": (32, " ", "Space"), "arrowup": (38, "ArrowUp", "ArrowUp"),
    "arrowdown": (40, "ArrowDown", "ArrowDown"), "arrowleft": (37, "ArrowLeft", "ArrowLeft"),
    "arrowright": (39, "ArrowRight", "ArrowRight"),
}


class BrowserManager:
    """管理一个 CDP 调试 Chrome 实例"""

    def __init__(self, cfg: dict):
        bcfg = cfg.get("browser") or {}
        project_root = cfg.get("_project_root", "")
        self.chrome_path = bcfg.get("chrome_path") or find_chrome()
        self.port = int(bcfg.get("debug_port", 9222))
        self.headless = bool(bcfg.get("headless", False))
        profile = bcfg.get("profile_dir") or "{project_root}\\.chrome-profile"
        self.profile_dir = profile.replace("{project_root}", project_root)
        self._proc = None
        self._ws = None
        self._next_id = 1
        self._url = None

    # ---------- 生命周期 ----------

    def _ensure(self):
        """确保 Chrome 调试实例运行并连接页面目标"""
        if self._ws is not None:
            return
        if not self._debug_port_alive():
            self._launch()
        targets = self._list_targets()
        page = None
        for t in targets:
            if t.get("type") == "page":
                page = t
                break
        if page is None:
            page = self._new_target()
        ws_url = page["webSocketDebuggerUrl"]
        self._ws = create_connection(ws_url, timeout=60)
        self._ws.settimeout(60)
        self._call("Page.enable")
        self._call("Runtime.enable")
        logger.info(f"已连接浏览器目标: {page.get('url', '')[:80]}")

    def _debug_port_alive(self) -> bool:
        try:
            r = requests.get(f"http://127.0.0.1:{self.port}/json/version", timeout=2)
            return r.status_code == 200
        except Exception:
            return False

    def _launch(self):
        args = [
            self.chrome_path,
            f"--remote-debugging-port={self.port}",
            f"--user-data-dir={self.profile_dir}",
            "--remote-allow-origins=*",
            "--no-first-run", "--no-default-browser-check",
            "--disable-popup-blocking", "--disable-session-crashed-bubble",
            "--disable-features=TranslateUI",
        ]
        if self.headless:
            args.append("--headless=new")
        args.append("about:blank")
        os.makedirs(self.profile_dir, exist_ok=True)
        self._proc = subprocess.Popen(args, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL)
        try:
            with open(os.path.join(self.profile_dir, _PID_FILE), "w") as f:
                f.write(str(self._proc.pid))
        except OSError:
            pass
        logger.info(f"启动 Chrome (port={self.port}, headless={self.headless}, pid={self._proc.pid})")
        for _ in range(60):
            if self._debug_port_alive():
                return
            if self._proc.poll() is not None:
                break  # Chrome 已退出，读 stderr 报错
            time.sleep(0.5)
        if self._proc.poll() is not None:
            err = ""
            try:
                err = self._proc.stderr.read().decode("utf-8", errors="replace")[:1200]
            except Exception:
                pass
            raise RuntimeError(f"Chrome 启动失败 (退出码 {self._proc.returncode}): {err}")
        raise RuntimeError("Chrome 调试端口未就绪")

    def _list_targets(self) -> list:
        r = requests.get(f"http://127.0.0.1:{self.port}/json/list", timeout=5)
        return r.json()

    def _new_target(self) -> dict:
        r = requests.put(f"http://127.0.0.1:{self.port}/json/new?about:blank", timeout=5)
        return r.json()

    def close(self):
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:
                pass
            self._ws = None
        if self._proc is not None:
            self._proc.terminate()
            self._proc = None
            logger.info("已关闭测试 Chrome 实例")

    # ---------- CDP 调用 ----------

    def _call(self, method: str, params: dict = None, timeout: float = 30) -> dict:
        mid = self._next_id
        self._next_id += 1
        self._ws.settimeout(timeout)
        self._ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        while True:
            try:
                msg = json.loads(self._ws.recv())
            except WebSocketTimeoutException:
                raise TimeoutError(f"CDP 调用超时: {method}")
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"CDP {method} 错误: {msg['error']}")
                return msg.get("result", {})

    def eval_js(self, expr: str) -> str:
        """执行 JS 表达式，返回字符串化结果"""
        result = self._call("Runtime.evaluate", {
            "expression": expr, "returnByValue": True, "awaitPromise": True,
        })
        if "exceptionDetails" in result:
            raise RuntimeError(f"JS 执行异常: {result['exceptionDetails'].get('text', '')}")
        value = result.get("result", {}).get("value")
        if isinstance(value, bool):
            return "true" if value else "false"
        if value is None:
            return "null"
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    # ---------- 窗口置前（headful 模式必须：Chrome 忽略非前台窗口的输入事件） ----------

    def _find_window_handle(self):
        """找到调试 Chrome 实例的窗口句柄（通过记录在 profile 目录的 PID）"""
        pid = None
        if self._proc is not None:
            pid = self._proc.pid
        else:
            try:
                with open(os.path.join(self.profile_dir, _PID_FILE)) as f:
                    pid = int(f.read().strip())
            except (OSError, ValueError):
                return None
        if not pid:
            return None
        user32 = ctypes.windll.user32
        found = []

        def enum_proc(h, lp):
            length = user32.GetWindowTextLengthW(h)
            if length > 0 and user32.IsWindowVisible(h):
                wpid = ctypes.c_ulong()
                user32.GetWindowThreadProcessId(h, ctypes.byref(wpid))
                if wpid.value == pid:
                    found.append(h)
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        user32.EnumWindows(WNDENUMPROC(enum_proc), 0)
        return found[0] if found else None

    def window_rect(self):
        """调试窗口的屏幕矩形 (x, y, w, h)，找不到返回 None"""
        hwnd = self._find_window_handle()
        if not hwnd:
            return None
        user32 = ctypes.windll.user32
        class RECT(ctypes.Structure):
            _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                        ("right", ctypes.c_long), ("bottom", ctypes.c_long)]
        r = RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(r)):
            return None
        return (r.left, r.top, r.right - r.left, r.bottom - r.top)

    def _ensure_foreground(self):
        """操作前把调试 Chrome 窗口恢复并置前（headless 模式跳过）"""
        if self.headless:
            return
        hwnd = self._find_window_handle()
        if not hwnd:
            return
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        cur_tid = kernel32.GetCurrentThreadId()
        fg = user32.GetForegroundWindow()
        fg_tid = user32.GetWindowThreadProcessId(fg, None)
        attached = False
        if fg_tid != cur_tid and fg_tid != 0:
            user32.AttachThreadInput(cur_tid, fg_tid, True)
            attached = True
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        if attached:
            user32.AttachThreadInput(cur_tid, fg_tid, False)
        time.sleep(0.15)

    # ---------- 页面操作 ----------

    def navigate(self, url: str, wait_load: float = 15):
        self._ensure()
        self._call("Page.navigate", {"url": url})
        deadline = time.time() + wait_load
        while time.time() < deadline:
            state = self.eval_js("document.readyState")
            if state == "complete":
                break
            time.sleep(0.4)
        self._url = url
        logger.info(f"页面加载完成: {url}")

    def find_element(self, text: str, occurrence: int = 0) -> dict | None:
        """按文字/占位符定位元素，返回 {x,y,found,...}（屏幕坐标）"""
        expr = _FIND_ELEMENT_JS % (text.replace("\\", "\\\\").replace("'", "\\'"), occurrence)
        try:
            raw = self.eval_js(expr)
        except RuntimeError:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    def click_text(self, text: str, occurrence: int = 0, dbl: bool = False) -> bool:
        """点击包含指定文字的元素（无 OCR）"""
        loc = self.find_element(text, occurrence)
        if not loc or not loc.get("found"):
            logger.warning(f"页面中未找到文字元素: {text}")
            return False
        x, y = float(loc["x"]), float(loc["y"])
        logger.info(f"DOM 定位 '{text}' [{loc.get('tag', '')}] → 点击 ({x:.0f}, {y:.0f})")
        return self._dispatch_click(x, y, dbl)

    def click_selector(self, selector: str, dbl: bool = False) -> bool:
        """按 CSS 选择器点击元素（如 '#kw'、'button.primary'）"""
        expr = _FIND_SELECTOR_JS % selector.replace("\\", "\\\\").replace("'", "\\'")
        try:
            raw = self.eval_js(expr)
            loc = json.loads(raw)
        except (RuntimeError, json.JSONDecodeError):
            loc = None
        if not loc or not loc.get("found"):
            logger.warning(f"页面中未找到选择器元素: {selector}")
            return False
        x, y = float(loc["x"]), float(loc["y"])
        logger.info(f"DOM 定位选择器 '{selector}' [{loc.get('tag', '')}] → 点击 ({x:.0f}, {y:.0f})")
        return self._dispatch_click(x, y, dbl)

    def _dispatch_click(self, x: float, y: float, dbl: bool = False) -> bool:
        self._ensure_foreground()
        clicks = 2 if dbl else 1
        self._call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
        for _ in range(clicks):
            self._call("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": clicks})
            self._call("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": clicks})
        return True

    def type_text(self, text: str):
        """向输入框输入文字（自动聚焦页面上第一个可编辑元素；Input.insertText 支持中文）"""
        self._ensure_foreground()
        focused = self.eval_js(
            "var a = document.activeElement; "
            "a && (a.tagName === 'INPUT' || a.tagName === 'TEXTAREA' || a.isContentEditable)")
        if focused != "true":
            self.eval_js(
                "var el = document.querySelector('input[type=text], input:not([type]), textarea, [contenteditable]'); "
                "if (el) { el.focus(); el.select(); }")
        self._call("Input.insertText", {"text": text})
        logger.info(f"已输入: {text[:50]}")

    def press(self, key: str) -> bool:
        """按单个键（enter/tab/escape/...）"""
        k = _KEYS.get(str(key).strip().lower())
        if not k:
            return False
        self._ensure_foreground()
        vk, name, code = k
        for typ, up in (("keyDown", False), ("keyUp", True)):
            params = {
                "type": typ, "key": name, "code": code,
                "windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk,
            }
            if not up and name == "Enter":
                params["text"] = "\r"
            self._call("Input.dispatchKeyEvent", params)
        return True

    def wait_text(self, text: str, timeout: float = 20, interval: float = 1.5) -> bool:
        """轮询页面 DOM 直到出现指定文字（无 OCR）"""
        expr = _WAIT_TEXT_JS % text.replace("\\", "\\\\").replace("'", "\\'")
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if self.eval_js(expr) == "true":
                    logger.success(f"页面出现文字: {text}")
                    return True
            except Exception:
                pass
            time.sleep(interval)
        return False
