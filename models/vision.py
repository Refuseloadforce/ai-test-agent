"""
视觉模型统一接口
支持 Qwen2-VL-7B 量化版本（AWQ/GPTQ）
"""

from transformers import Qwen2VLForConditionalGeneration, AutoProcessor
from qwen_vl_utils import process_vision_info
import torch
from PIL import Image
from loguru import logger


class VisionModel:
    def __init__(self, model_path: str = "Qwen/Qwen2-VL-7B-Instruct-AWQ"):
        """
        model_path: 本地模型路径 或 HuggingFace 模型名
        量化版推荐：
          - Qwen/Qwen2-VL-7B-Instruct-AWQ  (AWQ 量化，约 8G 显存)
          - Qwen/Qwen2-VL-7B-Instruct-GPTQ-Int4 (GPTQ 量化)
        """
        logger.info(f"Loading vision model from: {model_path}")
        self.model = Qwen2VLForConditionalGeneration.from_pretrained(
            model_path,
            torch_dtype=torch.float16,
            device_map="cuda",  # 自动分配到 GPU
        )
        self.processor = AutoProcessor.from_pretrained(model_path)
        logger.info("Vision model loaded successfully")

    def analyze(self, image: Image.Image, prompt: str) -> str:
        """
        分析截图，返回 AI 的回答
        :param image: PIL Image 截图
        :param prompt: 分析指令，如 "屏幕上有哪些可点击的按钮？"
        :return: AI 回答文本
        """
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": image},
                    {"type": "text", "text": prompt},
                ],
            }
        ]

        text = self.processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        image_inputs, video_inputs = process_vision_info(messages)

        inputs = self.processor(
            text=[text],
            images=image_inputs,
            videos=video_inputs,
            padding=True,
            return_tensors="pt",
        ).to("cuda")

        with torch.no_grad():
            generated_ids = self.model.generate(
                **inputs,
                max_new_tokens=512,
                temperature=0.1,
            )

        generated_ids_trimmed = [
            out_ids[len(in_ids):]
            for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
        ]
        output_text = self.processor.batch_decode(
            generated_ids_trimmed,
            skip_special_tokens=True,
            clean_up_tokenization_spaces=False,
        )
        return output_text[0]

    def plan_action(self, image: Image.Image, task: str) -> dict:
        """
        根据截图和任务，规划下一步动作
        返回结构化的动作指令
        """
        prompt = f"""你是一个 GUI 自动化测试助手。请分析当前屏幕截图，针对以下任务规划下一步操作。

任务：{task}

请用 JSON 格式回答，包含以下字段：
- action: 动作类型 (click/type/scroll/drag/hotkey/wait/done/failed)
- x: 点击的 X 坐标（如果是 click/drag）
- y: 点击的 Y 坐标（如果是 click/drag）
- text: 输入的文字（如果是 type）
- keys: 按键组合（如果是 hotkey，例如 ["ctrl", "c"]）
- description: 这一步在做什么（中文描述）
- reason: 为什么这样做

只输出 JSON，不要其他内容。"""

        response = self.analyze(image, prompt)

        # 解析 JSON
        import json
        import re
        # 提取 JSON 块
        json_match = re.search(r'\{.*\}', response, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass

        # 解析失败返回默认
        return {"action": "failed", "description": "AI 响应解析失败", "raw": response}
