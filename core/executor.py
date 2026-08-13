"""
动作执行器
严格按配置/规划出的步骤执行，不做任何猜测、没有规则解析器回退。
配置里写什么动作，就执行什么动作。

支持的动作为（全部可通过配置文件配置）：
  open         打开程序（exe 路径直接启动，或开始菜单搜索） {"action":"open","program":"记事本","args":["--new-window","https://..." ]}
  focus_window 按标题置前窗口                 {"action":"focus_window","title":"百度"}
  hotkey       快捷键                     {"action":"hotkey","keys":["ctrl","s"]}
  type         输入文字                   {"action":"type","text":"Hello"}
  click        单击坐标                   {"action":"click","x":100,"y":200}
  double_click 双击坐标                   {"action":"double_click","x":100,"y":200}
  right_click  右键坐标                   {"action":"right_click","x":100,"y":200}
  scroll       滚动                       {"action":"scroll","x":500,"y":400,"direction":"down","clicks":3}
  drag         拖拽                       {"action":"drag","x1":100,"y1":200,"x2":300,"y2":400}
  wait         等待                       {"action":"wait","seconds":2}
  click_text   点击屏幕上指定的文字        {"action":"click_text","text":"百度一下","occurrence":0,"click":"click"}
  wait_text    等待文字出现（OCR 轮询）    {"action":"wait_text","text":"搜索结果","timeout":15}
  browser_open 浏览器打开网址（CDP，DOM 级） {"action":"browser_open","url":"https://www.baidu.com"}
  browser_click 按 CSS 选择器点击网页元素    {"action":"browser_click","selector":"#kw"}
  browser_click_text 按文字点击网页元素（无 OCR） {"action":"browser_click_text","text":"百度一下","occurrence":0}
  browser_type 向焦点元素输入文字          {"action":"browser_type","text":"Hello"}
  browser_press 按单个键                  {"action":"browser_press","key":"Enter"}
  browser_wait_text 等待网页出现文字（无 OCR） {"action":"browser_wait_text","text":"搜索结果","timeout":20}
  browser_eval 执行 JS 并返回结果         {"action":"browser_eval","expr":"document.title"}
  ocr_analyze   截图 OCR 综合诊断（可让 AI 判断下一步） {"action":"ocr_analyze","question":"屏幕上是什么？","ask_ai":true}
  done         任务完成                   {"action":"done"}
"""

import os
import subprocess
import time
from datetime import datetime
from loguru import logger
from core.config import resolve_text
from core.ocr import find_text, ocr_screen
from core.browser import BrowserManager
from core.diagnose import capture as diagnose_capture, format_ocr_words


class Executor:
    def __init__(self, platform, cfg: dict, diag: list = None, llm_provider=None):
        """
        :param platform: 平台操作对象（DesktopPlatform）
        :param cfg: 完整配置（含 _project_root 内部字段）
        :param diag: 共享诊断事件列表（agent 的 log），ocr_analyze 会追加事件
        :param llm_provider: 返回 LLM 客户端的零参函数（用于 ask_ai 综合判断）
        """
        self.platform = platform
        self.project_root = cfg.get("_project_root", "")
        exec_cfg = cfg.get("execution") or {}
        self.wait_after = float(exec_cfg.get("wait_after_action", 0.8))
        self._cfg = cfg
        self._browser = None
        self._diag = diag
        self._llm_provider = llm_provider

    def get_browser(self):
        """当前浏览器管理器（未使用浏览器时为 None）"""
        return self._browser

    def _get_browser(self) -> BrowserManager:
        if self._browser is None:
            self._browser = BrowserManager(self._cfg)
        return self._browser

    def execute_step(self, action: dict) -> tuple[bool, str]:
        """
        执行一个动作
        :param action: 动作 dict，如 {"action":"hotkey","keys":["ctrl","s"],"description":"保存"}
        :return: (是否成功, 错误信息或空串)
        """
        action = dict(action)  # 拷贝，避免修改配置/计划
        atype = action.get("action", "")
        desc = action.get("description", "")
        logger.info(f"执行: [{atype}] {desc}")

        try:
            # 防 FAILSAFE 熔断：鼠标在角落时先移开
            premove = getattr(self.platform, "_safe_premove", None)
            if premove:
                premove()

            if atype == "open":
                self._do_open(action)
            elif atype == "focus_window":
                title = resolve_text(str(action.get("title", "")), self.project_root)
                if not title:
                    return False, "focus_window 动作缺少 title"
                if not self.platform.focus_window(title):
                    return False, f"找不到窗口: {title}"
            elif atype == "click_text":
                ok, err = self._do_click_text(action)
                if not ok:
                    return False, err
            elif atype == "wait_text":
                ok, err = self._do_wait_text(action)
                if not ok:
                    return False, err
            elif atype == "browser_open":
                url = resolve_text(str(action.get("url", "")), self.project_root)
                if not url:
                    return False, "browser_open 动作缺少 url"
                self._get_browser().navigate(url)
            elif atype == "browser_click_text":
                text = resolve_text(str(action.get("text", "")), self.project_root)
                if not text:
                    return False, "browser_click_text 动作缺少 text"
                if not self._get_browser().click_text(
                        text, occurrence=int(action.get("occurrence", 0)),
                        dbl=bool(action.get("double", False))):
                    return False, f"页面中未找到文字元素: {text}"
            elif atype == "browser_click":
                sel = str(action.get("selector", ""))
                if not sel:
                    return False, "browser_click 动作缺少 selector"
                if not self._get_browser().click_selector(sel, dbl=bool(action.get("double", False))):
                    return False, f"页面中未找到选择器元素: {sel}"
            elif atype == "browser_type":
                text = resolve_text(str(action.get("text", "")), self.project_root)
                if not text:
                    return False, "browser_type 动作缺少 text"
                self._get_browser().type_text(text)
            elif atype == "browser_press":
                key = str(action.get("key", ""))
                if not self._get_browser().press(key):
                    return False, f"不支持的按键: {key}（支持: enter/tab/escape/backspace/delete/space/方向键）"
            elif atype == "browser_wait_text":
                text = resolve_text(str(action.get("text", "")), self.project_root)
                if not text:
                    return False, "browser_wait_text 动作缺少 text"
                timeout = float(action.get("timeout", 20))
                if not self._get_browser().wait_text(text, timeout=timeout,
                                                     interval=float(action.get("interval", 1.5))):
                    return False, f"等待超时，页面未出现文字: {text}"
            elif atype == "browser_eval":
                expr = str(action.get("expr", ""))
                if not expr:
                    return False, "browser_eval 动作缺少 expr"
                result = self._get_browser().eval_js(expr)
                logger.info(f"browser_eval 结果: {result[:300]}")
            elif atype == "ocr_analyze":
                ok, err = self._do_ocr_analyze(action)
                if not ok:
                    return False, err
            elif atype == "hotkey":
                keys = action.get("keys") or []
                if not keys:
                    return False, "hotkey 动作缺少 keys"
                self.platform.hotkey(*keys)
            elif atype == "type":
                text = resolve_text(str(action.get("text", "")), self.project_root)
                if not text:
                    return False, "type 动作缺少 text"
                self.platform.type_text(text)
            elif atype == "click":
                self.platform.click(int(action["x"]), int(action["y"]))
            elif atype == "double_click":
                self.platform.double_click(int(action["x"]), int(action["y"]))
            elif atype == "right_click":
                self.platform.right_click(int(action["x"]), int(action["y"]))
            elif atype == "scroll":
                self.platform.scroll(
                    int(action.get("x", 0)), int(action.get("y", 0)),
                    clicks=int(action.get("clicks", 3)),
                    direction=action.get("direction", "down"),
                )
            elif atype == "drag":
                self.platform.drag(
                    int(action["x1"]), int(action["y1"]),
                    int(action["x2"]), int(action["y2"]),
                )
            elif atype == "wait":
                self.platform.wait(float(action.get("seconds", 1.0)))
            elif atype == "done":
                logger.success("任务完成")
                return True, ""
            else:
                return False, f"未知动作类型: {atype}"

            # 动作后稳定等待（可从配置 execution.wait_after_action 调整）
            if atype != "wait":
                self.platform.wait(self.wait_after)
            return True, ""

        except Exception as e:
            logger.error(f"动作执行失败 [{atype}] {desc}: {e}")
            return False, str(e)

    def _do_open(self, action: dict):
        """打开程序：
        1. program 为 exe 路径（绝对路径或相对项目根目录）→ 直接启动（可带 args），最可靠
        2. 否则通过开始菜单搜索打开
        """
        program = resolve_text(str(action.get("program", "")), self.project_root)
        if not program:
            raise ValueError("open 动作缺少 program 字段（程序名或 exe 路径）")

        # 方式1: exe 路径直接启动
        if program.lower().endswith(".exe"):
            path = program if os.path.isabs(program) else os.path.join(self.project_root, program)
            if os.path.exists(path):
                args = action.get("args") or []
                if args:
                    logger.info(f"直接启动: {path} {' '.join(str(a) for a in args)}")
                    subprocess.Popen([path] + [str(a) for a in args])
                else:
                    logger.info(f"直接启动: {path}")
                    os.startfile(path)
                self.platform.wait(1.0)
                return
            logger.warning(f"exe 路径不存在: {path}，回退到开始菜单搜索")

        # 方式2: 开始菜单搜索
        self.platform.hotkey("win")
        self.platform.wait(0.6)
        self.platform.type_text(program)
        self.platform.hotkey("enter")

    def _do_click_text(self, action: dict) -> tuple[bool, str]:
        """OCR 定位文字并点击（网页/桌面通用）"""
        text = resolve_text(str(action.get("text", "")), self.project_root)
        if not text:
            return False, "click_text 动作缺少 text"
        loc = find_text(text, image=self.platform.screenshot(),
                        occurrence=int(action.get("occurrence", 0)))
        if loc is None:
            return False, f"屏幕上未找到文字: {text}"
        click_type = action.get("click", "click")
        cx, cy = int(loc["cx"]), int(loc["cy"])
        logger.info(f"OCR 定位 '{text}' → 点击 ({cx}, {cy})")
        if click_type == "double_click":
            self.platform.double_click(cx, cy)
        elif click_type == "right_click":
            self.platform.right_click(cx, cy)
        else:
            self.platform.click(cx, cy)
        return True, ""

    def _do_wait_text(self, action: dict) -> tuple[bool, str]:
        """轮询 OCR 直到文字出现或超时"""
        text = resolve_text(str(action.get("text", "")), self.project_root)
        if not text:
            return False, "wait_text 动作缺少 text"
        timeout = float(action.get("timeout", 15))
        interval = float(action.get("interval", 2.0))
        deadline = time.time() + timeout
        logger.info(f"等待文字出现: '{text}' (最长 {timeout}s)")
        while time.time() < deadline:
            if find_text(text, image=self.platform.screenshot()) is not None:
                logger.success(f"文字已出现: '{text}'")
                return True, ""
            self.platform.wait(interval)
        return False, f"等待超时（{timeout}s），屏幕未出现文字: {text}"

    def _do_ocr_analyze(self, action: dict) -> tuple[bool, str]:
        """
        OCR 综合诊断：截图 → OCR → （可选）AI 综合判断当前状态和下一步
        {"action":"ocr_analyze","question":"...","ask_ai":true}
        """
        question = str(action.get("question", "")).strip() or "请综合判断：当前屏幕处于什么状态？下一步应该执行什么动作？"
        # 1. 截图 + OCR（浏览器模式优先裁窗口区域）
        diag = diagnose_capture(self.platform, browser=self.get_browser())
        ocr_text = diag["ocr_text"] or "(OCR 未识别到文字)"
        logger.info(f"OCR 屏幕内容: {ocr_text[:300]}")

        entry = {
            "time": datetime.now().isoformat(),
            "event": "ocr_analyze",
            "data": {"question": question, "ocr_text": ocr_text[:500], "dom": diag["dom"][:300]},
        }

        # 2. 可选：AI 综合判断
        judgment = ""
        if bool(action.get("ask_ai", False)) and self._llm_provider is not None:
            try:
                llm = self._llm_provider()
                prompt = (
                    f"你是一个桌面/网页自动化专家。现在执行任务时遇到不确定的情况，"
                    f"需要用屏幕信息综合判断。\n\n"
                    f"屏幕 OCR 识别文字：\n{ocr_text[:1500]}\n"
                )
                if diag["dom"]:
                    prompt += f"\n当前浏览器页面信息：\n{diag['dom']}\n"
                prompt += (
                    f"\n问题：{question}\n"
                    f"请判断：1) 当前处于什么状态；2) 下一步应该执行什么操作"
                    f"（可用的动作类型：hotkey/type/click/click_text/wait_text/browser_open/"
                    f"browser_click/browser_click_text/browser_type/browser_press/browser_wait_text/browser_eval/done）。"
                    f"简要回答，不要输出 JSON。"
                )
                judgment = llm.chat([
                    {"role": "system", "content": "你是一个谨慎的自动化专家，基于屏幕信息做判断。"},
                    {"role": "user", "content": prompt},
                ], max_tokens=300, thinking=False)
                logger.info(f"AI 综合判断: {judgment[:400]}")
                entry["data"]["ai_judgment"] = judgment[:500]
            except Exception as e:
                logger.warning(f"AI 综合判断失败: {e}")
                entry["data"]["ai_error"] = str(e)[:200]

        if self._diag is not None:
            self._diag.append(entry)
        return True, judgment[:300] if judgment else ""
