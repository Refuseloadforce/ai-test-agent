"""
AI 配置化桌面自动化 Agent - 入口

用法：
  python demo.py                             # 运行 config/config.json 中的所有任务
  python demo.py --config config/xxx.json    # 运行指定配置文件
  python demo.py --dry-run                   # 只预览将执行的步骤，不操作电脑

配置说明：所有配置（AI 模型、密钥、执行参数、任务列表）都在配置文件里，
改配置即可改行为，无需修改代码。
"""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from loguru import logger
from core.config import load_config
from core.agent import TestAgent


def preview(cfg: dict):
    """预览配置中所有任务将执行的步骤（不操作电脑）"""
    print("=" * 60)
    print("DRY-RUN 预览（不会操作电脑）")
    print("=" * 60)
    tasks = cfg["tasks"]
    for i, task in enumerate(tasks):
        print(f"\n[{i + 1}/{len(tasks)}] {task['name']}")
        steps = task.get("steps")
        if steps:
            print(f"  显式配置 {len(steps)} 步（直接执行，不经过 AI）:")
            for j, s in enumerate(steps):
                print(f"    {j + 1:2d}. [{s.get('action')}] {s.get('description', '')}")
        else:
            print(f"  自然语言任务（AI 规划）:")
            print(f"    task: {task['task']}")
            print(f"    → 将调用 DeepSeek ({cfg.get('llm', {}).get('model', 'deepseek-v4-flash')}) 规划步骤")
        print("-" * 60)
    print(f"\n共 {len(tasks)} 个任务。正式执行: python demo.py --config {cfg['_path']}")
    print("⚠️  正式执行会控制鼠标键盘，鼠标移到屏幕左上角可紧急停止")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="AI 配置化桌面自动化 Agent")
    parser.add_argument("--config", default=None, help="配置文件路径（默认 config/config.json）")
    parser.add_argument("--dry-run", action="store_true", help="只预览步骤，不操作电脑")
    args = parser.parse_args()

    project_root = os.path.dirname(os.path.abspath(__file__))
    cfg = load_config(args.config, project_root)

    if args.dry_run:
        preview(cfg)
        return

    print("[WARNING] 将控制你的鼠标和键盘！")
    print("  鼠标移到屏幕左上角可紧急停止 (FAILSAFE)")
    confirm = input("继续? (yes/no): ")
    if confirm.lower() not in ("yes", "y"):
        print("已取消")
        return

    agent = TestAgent(cfg)
    results = agent.run_all()

    # 汇总
    print("\n" + "=" * 60)
    print("运行总结")
    print("=" * 60)
    success = sum(1 for r in results if r["status"] == "success")
    print(f"任务: {success}/{len(results)} 成功")
    print(f"运行目录: {agent.run_dir}/")
    print(f"  summary.json - 运行总览")
    print(f"  <任务>/report.json + report.md - 每个任务的详细报告")
    print(f"  <任务>/*.png - 每步截图")
    sys.exit(0 if success == len(results) else 1)


if __name__ == "__main__":
    main()
