"""
AI 配置化桌面自动化 Agent（编排层）

架构（配置驱动，AI 只做规划和补救）：
  1. 从配置文件读取任务列表（config/*.json）
  2. 每个任务二选一：
     - 显式 steps   → 配置什么就执行什么，直接执行，不经过 AI
     - 自然语言 task → 调用 DeepSeek（deepseek-v4-flash）规划为步骤后执行
  3. 步骤失败 → 重试 → 可选 AI 补救规划
  4. 每步截图存档，生成 report.json / report.md

不再依赖本地大模型（torch/transformers），密钥、模型名、地址全部在配置文件中。
"""

import json
import time
from datetime import datetime
from pathlib import Path
from loguru import logger

from core.llm import DeepSeekClient
from core.executor import Executor
from core.diagnose import capture as diagnose_capture
from platforms.desktop import DesktopPlatform

MAX_REPLANS = 3  # 单任务最大 AI 补救次数


class TestAgent:
    def __init__(self, cfg: dict, platform=None):
        """
        :param cfg: load_config() 返回的完整配置
        :param platform: 平台操作对象，默认 DesktopPlatform（测试时可注入假平台）
        """
        self.cfg = cfg
        self.project_root = cfg["_project_root"]

        exec_cfg = cfg.get("execution") or {}
        self.max_steps = int(exec_cfg.get("max_steps", 50))
        self.max_retries = int(exec_cfg.get("max_retries", 2))
        self.ai_plan = bool(exec_cfg.get("ai_plan", True))
        self.ai_replan = bool(exec_cfg.get("ai_replan", True))
        self.screenshot = bool(exec_cfg.get("screenshot", True))

        # 事件日志（供报告使用；executor 的 ocr_analyze 也会追加事件）
        self.log = []

        self.platform = platform or DesktopPlatform()
        self.executor = Executor(self.platform, cfg, diag=self.log, llm_provider=self._get_llm)

        # LLM 懒加载：只有任务需要 AI（规划/补救）时才要求密钥
        self._llm = None

        self.run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.run_dir = Path(self.project_root) / "results" / self.run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"TestAgent 就绪 (run_dir={self.run_dir}, max_steps={self.max_steps})")

    # ---------- 入口 ----------

    def run_all(self) -> list[dict]:
        """执行配置中的所有任务，返回每个任务的结果"""
        results = []
        tasks = self.cfg["tasks"]
        for i, task_cfg in enumerate(tasks):
            logger.info(f"=== 任务 {i + 1}/{len(tasks)}: {task_cfg['name']} ===")
            result = self.run_task(task_cfg, i + 1)
            results.append(result)
            self._print_task_result(result)
        self._save_summary(results)
        return results

    def run_task(self, task_cfg: dict, index: int) -> dict:
        """执行单个任务"""
        name = task_cfg["name"]
        task_dir = self.run_dir / f"{index:02d}_{self._slug(name)}"
        task_dir.mkdir(parents=True, exist_ok=True)
        start = time.time()

        # 1. 确定步骤：显式 steps 直接执行；否则 AI 规划
        task_text = task_cfg.get("task", "")
        steps = task_cfg.get("steps")
        if steps is None:
            if not task_text:
                return self._fail_result(name, "任务未配置 task 或 steps", start, [], task_dir)
            if not self.ai_plan:
                return self._fail_result(
                    name, "执行配置 ai_plan=false 但任务没有显式 steps", start, [], task_dir
                )
            try:
                logger.info("AI 正在将任务规划为操作步骤...")
                steps = self._get_llm().plan(task_text, self.project_root)
                self._log("ai_plan", {"task": task_text, "steps": steps})
            except Exception as e:
                return self._fail_result(name, f"AI 规划失败: {e}", start, [], task_dir)

        # 2. 执行循环
        executed: list[dict] = []
        idx = 0
        replan_count = 0
        status, reason = "success", ""

        while idx < len(steps) and idx < self.max_steps:
            action = steps[idx]

            if action.get("action") == "done":
                executed.append(self._make_record(idx + 1, action, True, []))
                break

            record = self._execute_with_retry(action, idx + 1, task_dir)
            executed.append(record)

            if record["ok"]:
                idx += 1
                continue

            # 步骤最终失败 → OCR 综合诊断 + 可选 AI 补救
            if not self.ai_replan or replan_count >= MAX_REPLANS:
                status, reason = "failed", record.get("error") or "步骤执行失败"
                break
            replan_count += 1
            try:
                logger.warning(f"步骤 {idx + 1} 失败，正在截图 OCR 诊断...")
                diag = diagnose_capture(
                    self.platform, browser=self.executor.get_browser(),
                    save_dir=task_dir, name=f"diag_step_{idx + 1}",
                )
                self._log("ocr_diagnose", {
                    "step": idx + 1,
                    "error": record.get("error", "")[:200],
                    "ocr_text": diag["ocr_text"][:300],
                    "dom": diag["dom"][:300],
                    "screenshot": diag["screenshot_path"],
                })
                logger.warning(f"步骤 {idx + 1} 失败，AI 基于屏幕证据补救规划 (第{replan_count}次)...")
                remedy = self._get_llm().replan(
                    task_text or name, executed, action, record.get("error", ""),
                    screen_info=diag["text_summary"],
                )
                self._log("ai_replan", {"failed": action, "error": record["error"], "remedy": remedy})
                steps = remedy + steps[idx + 1:]
                idx = 0
            except Exception as e:
                status, reason = "failed", f"AI 补救规划失败: {e}"
                break

        if status == "success" and idx >= self.max_steps and idx < len(steps):
            status, reason = "timeout", f"执行超过最大步数限制 ({self.max_steps})"

        result = {
            "name": name,
            "status": status,
            "reason": reason,
            "steps": executed,
            "duration": time.time() - start,
            "task_dir": str(task_dir),
        }
        self._save_task_report(result, task_dir)
        return result

    # ---------- 步骤执行 ----------

    def _execute_with_retry(self, action: dict, step_idx: int, task_dir: Path) -> dict:
        """执行一步（含重试与截图存档），返回步骤记录"""
        attempts = []
        for attempt in range(self.max_retries + 1):
            ss_name = ""
            if self.screenshot:
                ss_name = f"step_{step_idx:02d}_try_{attempt + 1:02d}.png"
                try:
                    img = self.platform.screenshot()
                    img.save(str(task_dir / ss_name))
                except Exception as e:
                    logger.warning(f"截图失败: {e}")
                    ss_name = ""

            ok, err = self.executor.execute_step(action)
            attempts.append({
                "attempt": attempt + 1,
                "ok": ok,
                "error": err,
                "screenshot": ss_name,
            })
            if ok:
                return self._make_record(step_idx, action, True, attempts)

            logger.warning(f"Step {step_idx} 第{attempt + 1}次尝试失败: {err}")
            self.platform.wait(0.5)

        record = self._make_record(step_idx, action, False, attempts)
        record["error"] = err  # 最后一次尝试的错误信息
        return record

    @staticmethod
    def _make_record(step_idx: int, action: dict, ok: bool, attempts: list) -> dict:
        return {"step": step_idx, "action": action, "ok": ok, "attempts": attempts}

    # ---------- 工具 ----------

    def _get_llm(self) -> DeepSeekClient:
        if self._llm is None:
            self._llm = DeepSeekClient(self.cfg.get("llm") or {})
        return self._llm

    def _log(self, event: str, data: dict):
        self.log.append({"time": datetime.now().isoformat(), "event": event, "data": data})

    @staticmethod
    def _slug(name: str) -> str:
        """任务名 → 目录名（保留中英文与数字，其余替换为 _）"""
        out = "".join(c if c.isalnum() else "_" for c in name)
        return out.strip("_")[:30] or "task"

    @staticmethod
    def _fail_result(name, reason, start, steps, task_dir) -> dict:
        return {
            "name": name, "status": "failed", "reason": reason,
            "steps": steps, "duration": time.time() - start, "task_dir": str(task_dir),
        }

    # ---------- 报告 ----------

    def _save_summary(self, results: list[dict]):
        """运行总览（所有任务）"""
        summary = {
            "run_id": self.run_id,
            "run_dir": str(self.run_dir),
            "total_tasks": len(results),
            "success": sum(1 for r in results if r["status"] == "success"),
            "failed": sum(1 for r in results if r["status"] != "success"),
            "tasks": [
                {
                    "name": r["name"], "status": r["status"],
                    "duration": round(r["duration"], 1),
                    "steps": len(r["steps"]), "reason": r.get("reason", ""),
                    "task_dir": r["task_dir"],
                }
                for r in results
            ],
        }
        path = self.run_dir / "summary.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        logger.info(f"运行总结 → {path}")

    def _save_task_report(self, result: dict, task_dir: Path):
        report = {
            "run_id": self.run_id,
            "task": result["name"],
            "status": result["status"],
            "reason": result.get("reason", ""),
            "duration": round(result["duration"], 1),
            "steps": result["steps"],
            "log": self.log,
        }
        json_path = task_dir / "report.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        md_path = task_dir / "report.md"
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(self._generate_md_report(result))
        logger.info(f"任务报告 → {task_dir}")

    def _generate_md_report(self, result: dict) -> str:
        lines = [
            "# AI 配置化桌面自动化 - 任务报告",
            "",
            f"- **任务**: {result['name']}",
            f"- **状态**: {'✅ 成功' if result['status'] == 'success' else '❌ ' + result['status']}",
            f"- **耗时**: {result['duration']:.1f}s",
            f"- **步骤数**: {len(result['steps'])}",
        ]
        if result.get("reason"):
            lines.append(f"- **原因**: {result['reason']}")
        lines += ["", "## 执行过程", "", "| 步骤 | 动作 | 操作说明 | 结果 | 尝试 | 截图 |", "|------|------|----------|------|------|------|"]

        for step in result["steps"]:
            action = step["action"]
            atype = action.get("action", "?")
            desc = action.get("description", "")
            mark = "✅" if step["ok"] else "❌"
            attempts = step.get("attempts", [])
            n = len(attempts)
            ss = "-"
            if attempts:
                for a in reversed(attempts):
                    if a.get("screenshot"):
                        ss = f"![截图]({a['screenshot']})"
                        break
            lines.append(f"| {step['step']} | `{atype}` | {desc} | {mark} | {n} | {ss} |")

        if self.log:
            lines += ["", "## AI 事件日志", ""]
            for entry in self.log:
                lines.append(f"- **{entry['time'][11:19]}** `{entry['event']}`: {json.dumps(entry['data'], ensure_ascii=False)[:200]}")
        lines += ["", "---", "*由 AI 配置化桌面自动化 Agent 自动生成*"]
        return "\n".join(lines)

    def _print_task_result(self, result: dict):
        """控制台打印单个任务结果"""
        status_icon = "✅" if result["status"] == "success" else "❌"
        print(f"\n{status_icon} [{result['name']}] {result['status']} "
              f"({result['duration']:.1f}s, {len(result['steps'])}步)")
        if result.get("reason"):
            print(f"   原因: {result['reason']}")
        for step in result["steps"]:
            action = step["action"]
            atype = action.get("action", "?")
            desc = action.get("description", "")
            ok = "✓" if step["ok"] else "✗"
            n = len(step.get("attempts", []))
            print(f"   Step {step['step']}: [{atype}] {desc} {ok} (尝试{n}次)")
