"""
DeepSeek API 客户端（OpenAI 兼容接口）
模型名、API 密钥、接口地址全部从配置文件读取，改配置即可切换模型：
  - deepseek-v4-flash   （默认，快速）
  - deepseek-v4-pro     （旗舰）
  - deepseek-chat / deepseek-reasoner （如账号不支持 v4 系列可回退）
"""

import json
import os
import re
import requests
from loguru import logger

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-flash"


class DeepSeekClient:
    def __init__(self, llm_cfg: dict):
        """
        :param llm_cfg: 配置文件的 llm 节点
            {api_key, base_url, model, temperature, max_tokens}
        """
        self.api_key = (llm_cfg or {}).get("api_key") or os.environ.get("DEEPSEEK_API_KEY", "")
        if not self.api_key:
            raise RuntimeError(
                "未配置 DeepSeek API 密钥: 请在配置文件的 llm.api_key 中填写，"
                "或设置环境变量 DEEPSEEK_API_KEY"
            )
        self.base_url = (llm_cfg or {}).get("base_url", DEFAULT_BASE_URL).rstrip("/")
        self.model = (llm_cfg or {}).get("model", DEFAULT_MODEL)
        self.temperature = float((llm_cfg or {}).get("temperature", 0.2))
        self.max_tokens = int((llm_cfg or {}).get("max_tokens", 4096))
        logger.info(f"DeepSeek 客户端就绪: model={self.model} base_url={self.base_url}")

    # ---------- 基础调用 ----------

    def chat(self, messages: list[dict], max_tokens: int = None, json_mode: bool = False,
             thinking: bool = None) -> str:
        """
        调用 DeepSeek 对话接口
        :param messages: [{"role": "system"|"user"|"assistant", "content": "..."}]
        :param max_tokens: 单次回复最大 token 数
        :param json_mode: 是否要求 JSON 结构化输出
        :param thinking: 是否开启思考模式（None=使用 API 默认；False=显式关闭，
            用于需要直接回答的场景；思考模式下答复可能在 reasoning_content 里）
        :return: 模型回复文本
        """
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": max_tokens or self.max_tokens,
            "stream": False,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if thinking is not None:
            payload["thinking"] = {"type": "enabled" if thinking else "disabled"}

        resp = requests.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=180,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"DeepSeek API 错误 (HTTP {resp.status_code}): {resp.text[:500]}")
        data = resp.json()
        try:
            message = data["choices"][0]["message"]
            content = message.get("content") or ""
            if not content:
                # 思考模式：答复可能在 reasoning_content 中
                content = message.get("reasoning_content") or ""
            if not content:
                raise RuntimeError(f"DeepSeek API 返回空内容: {json.dumps(message, ensure_ascii=False)[:300]}")
            return content.strip()
        except (KeyError, IndexError, TypeError) as e:
            raise RuntimeError(f"DeepSeek API 响应格式异常: {data}") from e

    # ---------- 任务规划 ----------

    def plan(self, task_text: str, project_root: str) -> list[dict]:
        """
        将自然语言任务分解为动作步骤（JSON 数组）
        :param task_text: 用户任务描述（来自配置 task 字段）
        :param project_root: 项目根目录（注入提示词，要求用 {project_root} 占位符）
        :return: 动作步骤列表
        """
        prompt = f"""你是一个 Windows 桌面自动化专家。请把用户的任务分解为一步步可执行的操作。

用户任务：{task_text}

项目根目录：{project_root}
规则：涉及文件路径时，必须用 {{project_root}} 占位符代替项目根目录，禁止写出具体绝对路径。

只输出一个 JSON 数组，每步一个操作，可用操作类型：
1. hotkey 快捷键: {{"action":"hotkey","keys":["ctrl","s"],"description":"保存"}}
   （单个键如 [\"win\"]、[\"enter\"]；组合键如 [\"ctrl\",\"s\"]、[\"alt\",\"f4\"]）
2. type 输入文字: {{"action":"type","text":"Hello World","description":"输入内容"}}
   （注意：路径、程序名搜索等也用它）
3. wait 等待: {{"action":"wait","seconds":2,"description":"等待2秒"}}
4. click 点击坐标: {{"action":"click","x":100,"y":200,"description":"点击"}}
5. double_click 双击: {{"action":"double_click","x":100,"y":200,"description":"双击"}}
6. right_click 右键: {{"action":"right_click","x":100,"y":200,"description":"右键"}}
7. scroll 滚动: {{"action":"scroll","x":500,"y":400,"direction":"down","clicks":3,"description":"向下滚动"}}
8. drag 拖拽: {{"action":"drag","x1":100,"y1":200,"x2":300,"y2":400,"description":"拖拽"}}
9. open 打开程序: {{"action":"open","program":"记事本","description":"打开记事本"}}
10. done 任务完成: {{"action":"done","description":"任务完成"}}

规则：
- 打开程序用 open 动作（会通过开始菜单搜索），不要拆成 win/type/enter
- 保存文件：先 ctrl+s 打开保存对话框，再用 type 输入完整保存路径（含文件名，用 {{project_root}} 占位符），最后 enter 确认
- 每步只做一个操作，操作要具体
- 最后一步必须是 done
- 不要输出任何解释，只输出 JSON 数组"""

        content = self.chat(
            [
                {"role": "system", "content": "你是一个 Windows 自动化专家，只输出 JSON 格式的操作步骤。"},
                {"role": "user", "content": prompt},
            ],
            max_tokens=4096,
            json_mode=True,
        )
        logger.debug(f"AI 规划原始结果:\n{content}")
        steps = self._parse_json_array(content)
        if not steps:
            raise ValueError(f"AI 规划结果无法解析为步骤列表: {content[:300]}")
        steps = self._normalize_steps(steps, task_text)
        logger.info(f"AI 规划完成: {len(steps)} 步")
        return steps

    def replan(self, task_text: str, history: list[dict], failed_step: dict, error: str,
               screen_info: str = "") -> list[dict]:
        """
        某一步执行失败时，让 AI 根据失败原因与屏幕证据给出补救步骤
        :param task_text: 原始任务
        :param history: 已成功执行的步骤
        :param failed_step: 失败的步骤
        :param error: 失败原因
        :param screen_info: 屏幕证据（OCR 文字 + DOM 摘要），让 AI 综合判断当前状态
        :return: 补救步骤列表（替换失败步骤及其后续）
        """
        done_lines = "\n".join(
            f"  {i + 1}. [{h.get('action', {}).get('action', '?')}] {h.get('action', {}).get('description', '')}"
            for i, h in enumerate(history)
        )
        prompt = f"""你是一个 Windows 桌面/网页自动化专家。执行任务时某一步失败了，请综合屏幕信息判断当前状态并给出补救步骤。

原始任务：{task_text}

已成功执行的步骤：
{done_lines or "（无）"}

失败的步骤：{json.dumps(failed_step, ensure_ascii=False)}
失败原因：{error}

当前屏幕状态（OCR 识别文字 + 浏览器页面信息）：
{screen_info or "（无法获取屏幕信息）"}

要求：
- 先根据屏幕信息判断当前实际处于什么状态（是否弹窗/报错/页面未加载/布局变化等）
- 只输出一个 JSON 数组，格式与规划相同（hotkey/type/wait/click/double_click/right_click/scroll/drag/open/click_text/wait_text/browser_open/browser_click/browser_click_text/browser_type/browser_press/browser_wait_text/browser_eval/done）
- 路径仍用 {{project_root}} 占位符
- 从当前状态出发，输出接下来的补救步骤（可以重试、换方式、或放弃并 done）
- 不要输出任何解释，只输出 JSON 数组"""

        content = self.chat(
            [
                {"role": "system", "content": "你是一个 Windows 自动化专家，只输出 JSON 格式的操作步骤。"},
                {"role": "user", "content": prompt},
            ],
            max_tokens=2048,
            json_mode=True,
        )
        logger.debug(f"AI 补救规划原始结果:\n{content}")
        steps = self._parse_json_array(content)
        if not steps:
            raise ValueError(f"AI 补救规划结果无法解析: {content[:300]}")
        return self._normalize_steps(steps, task_text)

    # ---------- 解析与规范化 ----------

    def _parse_json_array(self, text: str) -> list | None:
        """从模型回复中提取 JSON 数组"""
        # 1. 代码块
        m = re.search(r"```(?:json)?\s*(\[[\s\S]*?\])\s*```", text)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass
        # 2. 第一个 [...] 
        m = re.search(r"(\[[\s\S]*\])", text)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass
        # 3. 修复单引号后重试
        try:
            return json.loads(text.replace("'", '"'))
        except json.JSONDecodeError:
            return None

    def _normalize_steps(self, steps: list, task_text: str) -> list[dict]:
        """规范化步骤：过滤未知动作、确保以 done 结尾"""
        valid = []
        for s in steps:
            if not isinstance(s, dict) or not s.get("action"):
                continue
            if s["action"] == "done":
                valid.append({"action": "done", "description": s.get("description", "任务完成")})
                break  # done 之后的步骤丢弃
            valid.append(s)
        if not valid:
            raise ValueError(f"AI 未规划出任何有效步骤 (任务: {task_text[:50]})")
        if valid[-1]["action"] != "done":
            valid.append({"action": "done", "description": "任务完成"})
        return valid
