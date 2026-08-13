"""
Windows 屏幕 OCR（WinRT Windows.Media.Ocr，系统自带，无需安装服务）
提供 find_text(): 在屏幕截图中定位文字 → 返回中心坐标，供 click_text 动作使用

依赖: pip install winsdk  （仅在 Windows 上可用；模块内延迟导入，不影响其他功能）
"""

import asyncio
import os
import tempfile
from loguru import logger


def _normalize(s: str) -> str:
    """去掉空白（中文 OCR 常在字间插入空格）"""
    return "".join(s.split())


async def _recognize_async(path: str) -> list[dict]:
    """对图片文件执行 OCR，返回词列表 [{text,x,y,w,h}]（坐标为图片像素坐标）"""
    import winsdk.windows.media.ocr as wocr
    import winsdk.windows.globalization as wglob
    import winsdk.windows.graphics.imaging as wimg
    import winsdk.windows.storage as wstore

    engine = wocr.OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        engine = wocr.OcrEngine.try_create_from_language(wglob.Language("zh-CN"))
    if engine is None:
        raise RuntimeError("系统没有可用的 OCR 语言包")

    file = await wstore.StorageFile.get_file_from_path_async(path)
    stream = await file.open_async(wstore.FileAccessMode.READ)
    decoder = await wimg.BitmapDecoder.create_async(stream)
    bitmap = await decoder.get_software_bitmap_async()
    result = await engine.recognize_async(bitmap)

    words = []
    for line in result.lines:
        for w in line.words:
            r = w.bounding_rect
            words.append({
                "text": w.text,
                "x": float(r.x), "y": float(r.y),
                "w": float(r.width), "h": float(r.height),
            })
    return words


def ocr_screen(image=None, path: str = None) -> list[dict]:
    """
    对屏幕截图执行 OCR
    :param image: PIL Image（推荐，会自动截图）或 None
    :param path: 截图文件路径（image 为 None 时使用）
    :return: 词列表 [{text,x,y,w,h}]
    """
    if image is not None:
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp.close()
        image.save(tmp.name)
        try:
            return asyncio.run(_recognize_async(tmp.name))
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass
    if not path:
        raise ValueError("ocr_screen 需要提供 image 或 path")
    return asyncio.run(_recognize_async(path))


def _group_lines(words: list[dict]) -> list[dict]:
    """把 OCR 词按行合并（中文 OCR 常把一句话拆成单个字）"""
    lines = []
    for w in sorted(words, key=lambda w: (w["y"], w["x"])):
        placed = False
        for ln in lines:
            if abs(w["y"] - ln["y"]) < max(6, w["h"] * 0.4):
                ln["words"].append(w)
                placed = True
                break
        if not placed:
            lines.append({"y": w["y"], "words": [w]})
    out = []
    for ln in lines:
        ln["words"].sort(key=lambda w: w["x"])
        text = "".join(_normalize(w["text"]) for w in ln["words"])
        if not text:
            continue
        xs = [w["x"] for w in ln["words"]]
        ys = [w["y"] for w in ln["words"]]
        ws = [w["x"] + w["w"] for w in ln["words"]]
        hs = [w["y"] + w["h"] for w in ln["words"]]
        out.append({
            "text": text,
            "x": min(xs), "y": min(ys),
            "w": max(ws) - min(xs), "h": max(hs) - min(ys),
            "cx": (min(xs) + max(ws)) / 2, "cy": (min(ys) + max(hs)) / 2,
            "words": ln["words"],
        })
    out.sort(key=lambda ln: (ln["y"], ln["x"]))
    return out


def _match_span(words: list[dict], norm: str) -> list[dict] | None:
    """返回行内覆盖目标子串的词列表（按字符跨度定位，避免整行中心偏移）"""
    acc = ""
    spans = []  # (start, end, word)
    for w in sorted(words, key=lambda w: w["x"]):
        wt = _normalize(w["text"])
        spans.append((len(acc), len(acc) + len(wt), w))
        acc += wt
    start = acc.find(norm)
    if start < 0:
        return None
    end = start + len(norm)
    return [w for s, e, w in spans if not (e <= start or s >= end)]


def find_text(target: str, words: list[dict] = None, image=None,
              occurrence: int = 0) -> dict | None:
    """
    在屏幕 OCR 结果中查找目标文字（忽略空白，子串匹配）
    :param target: 要找的文字，如 "百度一下"
    :param words: 已有 OCR 词表（避免重复 OCR）；None 则自动截屏识别
    :param image: 指定截图（默认截取当前屏幕）
    :param occurrence: 第几个匹配（0 开始）；负数为倒数第 |occurrence+1| 个
    :return: {"text","x","y","w","h","cx","cy"}（点击中心取覆盖目标的词，精确）或 None
    """
    if words is None:
        words = ocr_screen(image=image)
    norm = _normalize(target)
    if not norm:
        return None
    matches = []
    for ln in _group_lines(words):
        if norm in ln["text"]:
            span = _match_span(ln["words"], norm)
            if span:
                xs = [w["x"] for w in span]
                ys = [w["y"] for w in span]
                xe = [w["x"] + w["w"] for w in span]
                ye = [w["y"] + w["h"] for w in span]
                matches.append({
                    "text": ln["text"],
                    "x": min(xs), "y": min(ys),
                    "w": max(xe) - min(xs), "h": max(ye) - min(ys),
                    "cx": (min(xs) + max(xe)) / 2, "cy": (min(ys) + max(ye)) / 2,
                })
    if not matches:
        return None
    m = matches[occurrence]
    logger.debug(f"OCR 找到 '{target}' → ({m['cx']:.0f}, {m['cy']:.0f}) [{m['text']}]")
    return m
