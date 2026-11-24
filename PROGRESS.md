# Project Progress (`career-radar`)

**最后更新**：2026-11-24 · **当前阶段**：v0.1.0 发布准备已完成（M0–M3 + Step C）

---

## 里程碑状态总览

| 里程碑 | 状态 | 交付摘要 |
| :--- | :--- | :--- |
| **M0 — 需求、架构与离线底座** | ✅ Done | `PRD.md`、`ARCHITECTURE.md`、脱敏模板与虚构样例、`models`、`SQLiteJobStore`、`FixtureAdapter`、`rule_matcher`、双语 HTML 渲染与 `init`/`demo` CLI。 |
| **M1 — 官方 ATS 实网适配器** | ✅ Done | SmartRecruiters / Greenhouse / Lever / Workday 实网拉取、单站错误隔离、`scan` / `status` CLI 与首批公开端点验证。 |
| **M2 — 证据型匹配（方案 A）** | ✅ Done | ASCII 词边界过滤、按需完整 JD 补全、`apply-match` 防幻觉校验器与 `skills/career-radar-matcher/SKILL.md`。 |
| **M3 — 截断保护与双语简历构建** | ✅ Done | `FetchBatch` 截断安全下架保护、`selector.py` 自动选材、可选 ReportLab PDF 导出与 `resume` CLI。 |
| **Step C — v0.1.0 开源发布包装** | ✅ Done | 新增 MIT `LICENSE`、`.github/workflows/ci.yml` 与 `daily-scan.yml`、实跑生成的 `examples/sample_grounded_job_card.md`、中英文 `README.md` / `README_ZH.md` 与 `CHANGELOG.md`。 |
| **v0.2 — 下一阶段规划** | ⏳ Planned | 只读 MCP Server（直接向 IDE/Agent 暴露新岗与缺口查询）及可选无头 API 匹配适配器。 |

---

## 下一步

- 持续改进文档、示例和自动化测试。
- 规划只读 MCP 接口及可选的自动化匹配能力。
