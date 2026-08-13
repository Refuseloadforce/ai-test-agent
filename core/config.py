"""
配置加载模块
从 config/*.json 读取所有配置：AI 模型、执行参数、任务列表
实现"配置什么就执行什么"：所有行为都由配置文件决定，改配置不用改代码

支持 {project_root} 占位符：在配置中表示项目根目录，
执行时自动替换为真实路径（用于 type 动作和任务描述）。
"""

import json
import os
from pathlib import Path
from loguru import logger

DEFAULT_CONFIG_PATH = "config/config.json"

# 动作类型白名单（校验用）
KNOWN_ACTIONS = {
    "hotkey", "type", "click", "double_click", "right_click",
    "scroll", "drag", "wait", "open", "focus_window",
    "click_text", "wait_text",
    "browser_open", "browser_click", "browser_click_text", "browser_type",
    "browser_press", "browser_wait_text", "browser_eval",
    "ocr_analyze",
    "done",
}


def load_config(config_path: str = None, project_root: str = None) -> dict:
    """
    加载配置文件并校验
    :param config_path: 配置文件路径（相对项目根目录或绝对路径），默认 config/config.json
    :param project_root: 项目根目录，默认当前工作目录
    :return: 配置 dict，含 _project_root / _path 内部字段
    """
    project_root = project_root or str(Path.cwd())
    path = config_path or os.path.join(project_root, DEFAULT_CONFIG_PATH)
    if not os.path.isabs(path):
        path = os.path.join(project_root, path)

    if not Path(path).exists():
        raise FileNotFoundError(
            f"配置文件不存在: {path}\n"
            f"请复制 config/config.example.json 为 config/config.json 并填入你的配置"
        )

    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    if not isinstance(cfg, dict):
        raise ValueError(f"配置文件格式错误: {path}，顶层必须是 JSON 对象")

    cfg["_project_root"] = project_root
    cfg["_path"] = str(path)
    _validate(cfg)
    logger.info(f"已加载配置: {path}")
    return cfg


def _validate(cfg: dict):
    """校验配置结构，尽早暴露配置错误"""
    # 1. LLM 配置（可选：纯 steps 任务不需要密钥）
    llm = cfg.get("llm") or {}
    if not isinstance(llm, dict):
        raise ValueError("配置错误: llm 必须是对象 {api_key, base_url, model, ...}")
    api_key = llm.get("api_key") or os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        logger.warning(
            "未配置 LLM 密钥: 请在配置文件的 llm.api_key 或环境变量 DEEPSEEK_API_KEY 中配置。"
            "如果所有任务都使用显式 steps，则 AI 功能（规划/重规划）不可用"
        )

    # 2. 执行配置
    exec_cfg = cfg.get("execution") or {}
    if not isinstance(exec_cfg, dict):
        raise ValueError("配置错误: execution 必须是对象")

    # 3. 任务列表
    tasks = cfg.get("tasks")
    if not tasks:
        raise ValueError("配置错误: tasks 不能为空，至少配置一个任务")
    if not isinstance(tasks, list):
        raise ValueError("配置错误: tasks 必须是数组")

    for i, task in enumerate(tasks):
        if not isinstance(task, dict):
            raise ValueError(f"配置错误: tasks[{i}] 必须是对象 {{name, task 或 steps}}")
        if not task.get("name"):
            raise ValueError(f"配置错误: tasks[{i}] 缺少 name")
        has_task = bool(task.get("task"))
        has_steps = isinstance(task.get("steps"), list) and len(task["steps"]) > 0
        if not has_task and not has_steps:
            raise ValueError(
                f"配置错误: tasks[{i}].name='{task['name']}' 必须配置 task（自然语言，AI规划）"
                f"或 steps（显式动作列表，直接执行）"
            )
        if has_steps:
            _validate_steps(task["steps"], i)


def _validate_steps(steps: list, task_idx: int):
    """校验显式配置的动作步骤"""
    for j, step in enumerate(steps):
        if not isinstance(step, dict) or not step.get("action"):
            raise ValueError(f"配置错误: tasks[{task_idx}].steps[{j}] 缺少 action 字段")
        atype = step["action"]
        if atype not in KNOWN_ACTIONS:
            raise ValueError(
                f"配置错误: tasks[{task_idx}].steps[{j}] 的 action='{atype}' 不支持。"
                f"支持: {sorted(KNOWN_ACTIONS)}"
            )
        if atype in ("hotkey",) and not step.get("keys"):
            raise ValueError(f"配置错误: steps[{j}] hotkey 动作缺少 keys 字段（如 [\"ctrl\",\"s\"]）")
        if atype == "type" and not step.get("text"):
            raise ValueError(f"配置错误: steps[{j}] type 动作缺少 text 字段")
        if atype in ("click_text", "wait_text") and not step.get("text"):
            raise ValueError(f"配置错误: steps[{j}] {atype} 动作缺少 text 字段")
        if atype == "browser_open" and not step.get("url"):
            raise ValueError(f"配置错误: steps[{j}] browser_open 动作缺少 url 字段")
        if atype == "browser_click" and not step.get("selector"):
            raise ValueError(f"配置错误: steps[{j}] browser_click 动作缺少 selector 字段")
        if atype in ("browser_click_text", "browser_type", "browser_wait_text") and not step.get("text"):
            raise ValueError(f"配置错误: steps[{j}] {atype} 动作缺少 text 字段")
        if atype == "browser_eval" and not step.get("expr"):
            raise ValueError(f"配置错误: steps[{j}] browser_eval 动作缺少 expr 字段")
        if atype == "browser_press" and not step.get("key"):
            raise ValueError(f"配置错误: steps[{j}] browser_press 动作缺少 key 字段")
        if atype in ("click", "double_click", "right_click") and not (
            "x" in step and "y" in step
        ):
            raise ValueError(f"配置错误: steps[{j}] {atype} 动作缺少 x/y 坐标")
        if atype == "open" and not step.get("program"):
            raise ValueError(f"配置错误: steps[{j}] open 动作缺少 program 字段（程序名）")


def resolve_text(text: str, project_root: str) -> str:
    """替换文本中的 {project_root} 占位符为项目根目录"""
    if not text:
        return text
    return text.replace("{project_root}", project_root)
