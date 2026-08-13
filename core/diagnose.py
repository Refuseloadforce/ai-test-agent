"""
屏幕状态诊断模块
遇到意外情况时：截图 + OCR + （浏览器）DOM 摘要 → 综合判断当前状态，供 AI 决定下一步

用法：
  - agent 失败自动诊断：capture(platform, browser, save_dir, name)
  - ocr_analyze 动作：ocr_analyze_action(...)
"""

from pathlib import Path
from loguru import logger
from core.ocr import ocr_screen


def format_ocr_words(words: list, max_len: int = 1000) -> str:
    """把 OCR 词表整理成可读的行文本"""
    lines = {}
    for w in words:
        key = round(w["y"] / 20)
        lines.setdefault(key, []).append(w)
    out = []
    for k in sorted(lines):
        ws = sorted(lines[k], key=lambda w: w["x"])
        out.append("".join(x["text"] for x in ws))
    text = "\n".join(out)
    return text[:max_len]


def ocr_text_of_image(image, max_len: int = 1000) -> str:
    """对 PIL 图像执行 OCR，返回行文本"""
    try:
        words = ocr_screen(image=image)
        return format_ocr_words(words, max_len)
    except Exception as e:
        logger.warning(f"OCR 失败: {e}")
        return f"(OCR 失败: {e})"


def browser_dom_summary(browser, max_len: int = 600) -> str:
    """浏览器 DOM 摘要（URL/标题/可见文字）"""
    if browser is None:
        return ""
    try:
        url = browser.eval_js("location.href")[:120]
        title = browser.eval_js("document.title")[:80]
        text = browser.eval_js("document.body.innerText.slice(0, 300)")
        return f"页面URL: {url}\n页面标题: {title}\n页面可见文字: {text}"
    except Exception as e:
        return f"(DOM 摘要失败: {e})"


def browser_window_image(platform, browser):
    """优先截取浏览器窗口区域（更聚焦），否则全屏"""
    img = platform.screenshot()
    if browser is None:
        return img
    try:
        rect = browser.window_rect()
        if rect:
            x, y, w, h = rect
            return img.crop((x, y, x + w, y + h))
    except Exception:
        pass
    return img


def capture(platform, browser=None, save_dir=None, name="diag") -> dict:
    """
    综合诊断当前状态
    :return: {ocr_text, dom, text_summary, screenshot_path, ocr_path}
    """
    diag = {"ocr_text": "", "dom": "", "text_summary": "", "screenshot_path": "", "ocr_path": ""}
    try:
        img = browser_window_image(platform, browser)
        ocr_text = ocr_text_of_image(img)
        diag["ocr_text"] = ocr_text
        logger.info(f"诊断 OCR 文字:\n{ocr_text[:400]}")
    except Exception as e:
        logger.warning(f"诊断截图/OCR 失败: {e}")

    dom = browser_dom_summary(browser)
    diag["dom"] = dom

    parts = [p for p in (dom, ocr_text) if p]
    diag["text_summary"] = "\n\n".join(parts)

    if save_dir:
        d = Path(save_dir)
        d.mkdir(parents=True, exist_ok=True)
        try:
            img = browser_window_image(platform, browser)
            ss_path = d / f"{name}_screen.png"
            img.save(str(ss_path))
            diag["screenshot_path"] = str(ss_path)
        except Exception as e:
            logger.warning(f"保存诊断截图失败: {e}")
        try:
            ocr_path = d / f"{name}_ocr.txt"
            ocr_path.write_text(diag["ocr_text"], encoding="utf-8")
            diag["ocr_path"] = str(ocr_path)
        except OSError as e:
            logger.warning(f"保存 OCR 文本失败: {e}")
    return diag
