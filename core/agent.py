"""
AI 测试 Agent 核心
负责任务规划和循环执行
"""

import time
from pathlib import Path
from loguru import logger
from models.vision import VisionModel
from platforms.desktop import DesktopPlatform


class TestAgent:
    def __init__(
        self,
        model_path: str = "Qwen/Qwen2-VL-7B-Instruct-AWQ",
        max_steps: int = 20,
        screenshot_dir: str = "screenshots",
    ):
        """
        :param model_path: 视觉模型路径（本地路径 或 HF 模型名）
        :param max_steps: 最大执行步数，防止死循环
        :param screenshot_dir: 截图保存目录
        """
        self.model = VisionModel(model_path)
        self.platform = DesktopPlatform()
        self.max_steps = max_steps
        self.screenshot_dir = Path(screenshot_dir)
        self.screenshot_dir.mkdir(exist_ok=True)
        logger.info("TestAgent initialized")

    def run(self, task: str) -> dict:
        """
        执行一个测试任务
        :param task: 自然语言任务描述，如 "打开浏览器，搜索 Python 教程"
        :return: 执行结果 dict
        """
        logger.info(f"Starting task: {task}")
        steps = []
        start_time = time.time()

        for step_idx in range(self.max_steps):
            logger.info(f"=== Step {step_idx + 1} / {self.max_steps} ===")

            # 1. 截图
            screenshot = self.platform.screenshot()
            screenshot_path = self.screenshot_dir / f"step_{step_idx:03d}.png"
            screenshot.save(str(screenshot_path))

            # 2. AI 分析，规划下一步
            action = self.model.plan_action(screenshot, task)
            logger.info(f"AI decision: {action}")

            steps.append({
                "step": step_idx + 1,
                "screenshot": str(screenshot_path),
                "action": action,
            })

            # 3. 判断任务是否完成或失败
            if action.get("action") == "done":
                logger.success(f"Task completed in {step_idx + 1} steps!")
                return {
                    "status": "success",
                    "task": task,
                    "steps": steps,
                    "duration": time.time() - start_time,
                }

            if action.get("action") == "failed":
                logger.error("Task failed by AI decision")
                return {
                    "status": "failed",
                    "task": task,
                    "steps": steps,
                    "duration": time.time() - start_time,
                    "reason": action.get("reason", "unknown"),
                }

            # 4. 执行动作
            success = self.platform.execute_action(action)
            if not success:
                logger.warning(f"Action execution failed at step {step_idx + 1}")

            # 5. 等待界面响应
            self.platform.wait(1.0)

        # 超出最大步数
        logger.warning(f"Max steps ({self.max_steps}) reached without completion")
        return {
            "status": "timeout",
            "task": task,
            "steps": steps,
            "duration": time.time() - start_time,
        }

    def quick_analyze(self, question: str) -> str:
        """
        快速分析当前屏幕（不执行操作）
        :param question: 问题，如 "当前页面是什么？"
        :return: AI 回答
        """
        screenshot = self.platform.screenshot()
        return self.model.analyze(screenshot, question)
