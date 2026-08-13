# 贡献指南 / Contributing

感谢你有兴趣为 ai-test-agent 做贡献！欢迎提交 Bug 报告、功能建议和代码。

## 报告问题

- 使用 [Bug 报告模板](https://github.com/Refuseloadforce/ai-test-agent/issues/new?template=bug_report.md)
- 尽量包含：运行环境（Windows 版本、Python 版本）、复现步骤、期望/实际行为
- 把失败的运行报告（`results/<时间戳>/` 里的 `report.json`）作为附件附上，会非常有帮助

## 提出功能建议

- 使用 [功能建议模板](https://github.com/Refuseloadforce/ai-test-agent/issues/new?template=feature_request.md)
- 描述你的使用场景：想自动做什么、现在卡在哪里

## 开发环境

```bash
git clone https://github.com/Refuseloadforce/ai-test-agent.git
cd ai-test-agent
python -m venv venv
venv\Scripts\activate      # Windows
pip install -r requirements.txt

# 复制配置模板
copy config\config.example.json config\config.json

# 自测（不操作真实电脑、不调用真实 API）
python tests\selftest.py
```

## 提交代码

1. Fork 本仓库并创建分支：`git checkout -b feat/你的特性`
2. 修改后跑一遍自测：`python tests\selftest.py`（应全部通过）
3. 提交信息参考 [Conventional Commits](https://www.conventionalcommits.org/)：
   `feat: ...` / `fix: ...` / `docs: ...`
4. 推送分支并发起 Pull Request

## 代码风格

- Python 代码用 4 空格缩进，UTF-8 编码，注释/文档用中文
- 新增动作类型时，同步更新：`core/executor.py`（动作实现）、`core/config.py`
  （KNOWN_ACTIONS 白名单与校验）、`tests/selftest.py`（测试）、`README.md`（文档）
- `requirements.txt` 必须保持纯 ASCII（Windows pip 用 GBK 解码，中文注释会报错）

## 新动作实现清单

```
1. core/executor.py   execute_step 里加分发 + 实现方法
2. core/config.py     KNOWN_ACTIONS 白名单 + 参数校验
3. tests/selftest.py  至少覆盖成功和失败两条路径（用 FakePlatform / mock）
4. README.md          动作表格加一行 + 示例说明
```
