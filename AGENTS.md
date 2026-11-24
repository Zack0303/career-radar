# Repository Working Rules (`AGENTS.md`)

本文件供所有在本仓库协作的 AI Agent（Antigravity、Claude Code、Codex、Cursor 等）与开发者共同遵守。

## 1. 先读文档再动手
开始任何功能开发、架构调整或发布前，必须先阅读：
1. [docs/PRD.md](docs/PRD.md) — 功能范围、非目标（Non-Goals）与验收标准。
2. [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — 领域模型、ATS 接口规范、SQLite Schema 与防幻觉规则。
3. [PROGRESS.md](PROGRESS.md) — 当前已完成里程碑与下一步计划。

## 2. 隐私与合成数据红线（严格执行）
- 仓库内所有模板、测试、Preset、示例数据必须使用**完全虚构/合成数据**。
- **严禁**将任何真实个人姓名、电话、邮箱、住址、个人求职档案或前雇主敏感信息写入仓库源码、测试、文档或 Commit 中。
- 用户的真实配置文件、简历数据、SQLite 数据库与输出产物只能存放在 `workspace/` 或 `output/`（均已在 `.gitignore` 中忽略）。

## 3. 工程质量与诚实汇报原则
- **Python 3.9+ 兼容**：所有源码文件顶部保留 `from __future__ import annotations`，核心包保持仅依赖标准库（可选能力通过 `pyproject.toml` Extras 引入）。
- **禁止夸大完成度**：未实现的里程碑能力（如 M1 实网抓取、M2 LLM 匹配、M3 ReportLab PDF）不得在文档或测试中伪装成已完成。
- **证明其有效**：每次代码改动后，必须运行 `PYTHONPATH=src python3 -m unittest discover -s tests -v` 并确认全部通过，才能声称任务完成。
