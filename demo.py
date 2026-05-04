"""
快速 Demo 入口
运行前请先安装依赖：pip install -r requirements.txt
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from loguru import logger
from core.agent import TestAgent


def demo_analyze():
    """Demo 1: 只分析当前屏幕，不执行操作"""
    logger.info("Demo: 分析当前屏幕")

    # 如果你有本地模型，改成本地路径，如：
    # model_path = "D:/models/Qwen2-VL-7B-Instruct-AWQ"
    model_path = "Qwen/Qwen2-VL-7B-Instruct-AWQ"

    agent = TestAgent(model_path=model_path)
    result = agent.quick_analyze("请描述当前屏幕上显示的内容，列出所有可见的界面元素")
    print("\n=== AI 分析结果 ===")
    print(result)


def demo_task():
    """Demo 2: 执行一个完整任务（谨慎！会控制你的电脑）"""
    logger.info("Demo: 执行自动化任务")

    model_path = "Qwen/Qwen2-VL-7B-Instruct-AWQ"
    agent = TestAgent(model_path=model_path, max_steps=10)

    # 修改为你想测试的任务
    task = "打开记事本，输入 Hello World，然后保存文件"

    result = agent.run(task)
    print("\n=== 执行结果 ===")
    print(f"状态: {result['status']}")
    print(f"耗时: {result['duration']:.1f}s")
    print(f"步数: {len(result['steps'])}")
    for step in result['steps']:
        action = step['action']
        print(f"  Step {step['step']}: [{action.get('action')}] {action.get('description', '')}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="AI GUI Test Agent Demo")
    parser.add_argument(
        "--mode",
        choices=["analyze", "task"],
        default="analyze",
        help="analyze=只分析屏幕, task=执行任务（会控制电脑）"
    )
    args = parser.parse_args()

    if args.mode == "analyze":
        demo_analyze()
    else:
        print("⚠️  警告：task 模式会自动控制你的鼠标和键盘！")
        print("   鼠标移到屏幕左上角可紧急停止（pyautogui.FAILSAFE）")
        confirm = input("确认继续？(yes/no): ")
        if confirm.lower() == "yes":
            demo_task()
