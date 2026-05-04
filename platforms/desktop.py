"""
PC 端操作模块
截图 + 鼠标键盘控制
"""

import time
import pyautogui
import mss
import mss.tools
from PIL import Image
from loguru import logger


# 安全设置
pyautogui.FAILSAFE = True   # 鼠标移到左上角立即停止
pyautogui.PAUSE = 0.5       # 每次操作后暂停 0.5s，更稳定


class DesktopPlatform:
    def __init__(self):
        self.sct = mss.mss()
        logger.info("Desktop platform initialized")

    def screenshot(self, monitor_index: int = 1) -> Image.Image:
        """
        截取屏幕截图
        :param monitor_index: 显示器编号，1 = 主显示器
        :return: PIL Image
        """
        monitor = self.sct.monitors[monitor_index]
        sct_img = self.sct.grab(monitor)
        img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
        logger.debug(f"Screenshot taken: {img.size}")
        return img

    def save_screenshot(self, path: str, monitor_index: int = 1):
        """截图并保存到文件"""
        img = self.screenshot(monitor_index)
        img.save(path)
        logger.info(f"Screenshot saved to: {path}")
        return img

    def click(self, x: int, y: int, button: str = "left", clicks: int = 1):
        """点击指定坐标"""
        logger.info(f"Click: ({x}, {y}) button={button} clicks={clicks}")
        pyautogui.click(x, y, button=button, clicks=clicks, interval=0.2)

    def double_click(self, x: int, y: int):
        """双击"""
        self.click(x, y, clicks=2)

    def right_click(self, x: int, y: int):
        """右键点击"""
        self.click(x, y, button="right")

    def type_text(self, text: str, interval: float = 0.05):
        """输入文字"""
        logger.info(f"Type: {text[:50]}{'...' if len(text) > 50 else ''}")
        pyautogui.write(text, interval=interval)

    def hotkey(self, *keys):
        """按下快捷键，如 hotkey('ctrl', 'c')"""
        logger.info(f"Hotkey: {'+'.join(keys)}")
        pyautogui.hotkey(*keys)

    def scroll(self, x: int, y: int, clicks: int = 3, direction: str = "down"):
        """滚动鼠标"""
        logger.info(f"Scroll: ({x}, {y}) direction={direction} clicks={clicks}")
        scroll_clicks = -clicks if direction == "down" else clicks
        pyautogui.scroll(scroll_clicks, x=x, y=y)

    def drag(self, x1: int, y1: int, x2: int, y2: int, duration: float = 0.5):
        """拖拽"""
        logger.info(f"Drag: ({x1},{y1}) -> ({x2},{y2})")
        pyautogui.drag(x2 - x1, y2 - y1, duration=duration, button="left")

    def move_to(self, x: int, y: int):
        """移动鼠标（不点击）"""
        pyautogui.moveTo(x, y, duration=0.3)

    def wait(self, seconds: float = 1.0):
        """等待"""
        logger.debug(f"Wait: {seconds}s")
        time.sleep(seconds)

    def execute_action(self, action: dict) -> bool:
        """
        执行 AI 规划的动作
        :param action: vision.plan_action 返回的 dict
        :return: 是否执行成功
        """
        action_type = action.get("action", "")
        desc = action.get("description", "")
        logger.info(f"Execute: [{action_type}] {desc}")

        try:
            if action_type == "click":
                self.click(action["x"], action["y"])
            elif action_type == "double_click":
                self.double_click(action["x"], action["y"])
            elif action_type == "right_click":
                self.right_click(action["x"], action["y"])
            elif action_type == "type":
                self.type_text(action["text"])
            elif action_type == "hotkey":
                self.hotkey(*action["keys"])
            elif action_type == "scroll":
                direction = action.get("direction", "down")
                self.scroll(action["x"], action["y"], direction=direction)
            elif action_type == "drag":
                self.drag(action["x1"], action["y1"], action["x2"], action["y2"])
            elif action_type == "wait":
                self.wait(action.get("seconds", 1.0))
            elif action_type == "done":
                logger.success("Task completed!")
                return True
            elif action_type == "failed":
                logger.error(f"Task failed: {action.get('reason', 'unknown')}")
                return False
            else:
                logger.warning(f"Unknown action type: {action_type}")
                return False

            return True

        except Exception as e:
            logger.error(f"Execute action error: {e}")
            return False

    def get_screen_size(self) -> tuple:
        """获取屏幕分辨率"""
        return pyautogui.size()
