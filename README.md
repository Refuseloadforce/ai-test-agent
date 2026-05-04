# AI GUI Test Agent

基于 Qwen2-VL 视觉模型的 GUI 自动化测试框架，支持 PC 端屏幕理解和自动操作。

## 项目结构

```
ai-test-agent/
├── core/
│   └── agent.py          # 核心 Agent，任务循环
├── platforms/
│   └── desktop.py        # PC 端截图 + 鼠标键盘控制
├── models/
│   └── vision.py         # Qwen2-VL 视觉模型封装
├── screenshots/          # 执行截图（自动生成）
├── demo.py               # 快速体验入口
├── requirements.txt      # 依赖
└── README.md
```

## 环境要求

- Python 3.10+
- NVIDIA GPU，显存 8G+（用于 Qwen2-VL-7B AWQ 量化）
- CUDA 12.x 推荐

## 安装

```bash
# 1. 创建虚拟环境
python -m venv venv
venv\Scripts\activate  # Windows

# 2. 安装依赖
pip install -r requirements.txt

# 3. 下载模型（首次运行自动下载，也可提前手动下载）
# 模型约 8G，下载到 HuggingFace 缓存或指定本地路径
```

## 快速开始

### 只分析屏幕（安全，不操作电脑）

```bash
python demo.py --mode analyze
```

### 执行自动化任务（会控制鼠标键盘）

```bash
python demo.py --mode task
```

> ⚠️ 执行任务时，鼠标移到屏幕**左上角**可紧急停止
·
### 代码调用

```python
from core.agent import TestAgent

# 初始化（本地模型路径）
agent = TestAgent(
    model_path="D:/models/Qwen2-VL-7B-Instruct-AWQ",  # 改成你的路径
    max_steps=15,
)

# 执行任务
result = agent.run("打开浏览器，搜索 Python 教程，截图保存")
print(result["status"])  # success / failed / timeout

# 只分析屏幕
answer = agent.quick_analyze("当前页面显示的是什么？")
print(answer)
```

## 使用本地模型

如果已下载模型到本地，修改 `model_path`：

```python
# 改为本地路径
model_path = r"D:\models\Qwen2-VL-7B-Instruct-AWQ"
agent = TestAgent(model_path=model_path)
```

## 下一步计划

- [ ] Android 端支持（ADB）
- [ ] iOS 端支持（tidevice）
- [ ] FastAPI HTTP 服务
- [ ] 任务录制与回放
- [ ] HTML 测试报告（Allure）
- [ ] 并发多任务支持
