# Career Radar

**本地优先的官方招聘系统（ATS）增量雷达与证据可追溯求职工具箱**

[English](README.md) | 中文

`Python 3.9+` · `核心零第三方依赖` · `本地优先` · `MIT License`

---

## 为什么做 Career Radar？

市面上常见的求职工具往往落入两个坑：要么写脆爬虫去刷聚合招聘站；要么把简历丢给大模型“一键美化”，最后偷偷编造百分比指标和项目主导权。

**Career Radar** 的做法很克制：

1. **直接盯目标公司官方 ATS 公开接口**：基于 **SmartRecruiters / Greenhouse / Lever / Workday** 公开 JSON 接口，在本地 SQLite 中精确追踪 `NEW`（新开）、`UPDATED`（变更）、`UNCHANGED`、`CLOSED`（下架）；翻页截断的局部扫描绝不误标下架。
2. **每条简历断言必须有证据出处**：用私有的 `master_profile.md` + `project_library.md` 建立单一事实源，强制划分 `[Verified]` / `[Self-reported]` / `[Gap]`；`apply-match` 校验器会直接拦截未知项目编号和档案里不存在的指标数字。
3. **Bring Your Own Agent（零额外 API 费）**：`scan` 导出 `scan_digest.json` 与按需拉取的完整 JD 正文，配合 [skills/career-radar-matcher/SKILL.md](skills/career-radar-matcher/SKILL.md)，直接用你现有的 Antigravity / Claude Code / Codex 订阅跑匹配，不用额外花钱买 API 壳子。
4. **按 JD 挑项目 + 清爽双语简历**：根据 JD 关键词确定性选出最契合的 3–4 个项目（不改写原文），零依赖输出打印级 A4 中英双语 HTML（装上 `[pdf]` 可选依赖即可直接导出 PDF）。

---

## 与常见工具的对比

| 维度 | Career Radar | 普通抓岗爬虫 | 常见 AI 改简历工具 |
| :--- | :--- | :--- | :--- |
| **数据来源** | 官方 ATS 公开 JSON（SmartRecruiters / Greenhouse / Lever / Workday） | 第三方聚合站 / 易碎 HTML 解析 | 手动复制粘贴 |
| **增量追踪** | 本地 SQLite 状态机 + 截断保护防误标下架 | 常见为全量 CSV 覆盖 | 无 |
| **模型成本** | **BYOA**（复用已有 Agent 订阅 + Skill，额外成本 `$0`） | 无或付费平台 | 需另付会员或 API Key |
| **防幻觉护栏** | `apply-match` 确定性拦截未声明 ID 与虚构数字 | 不适用 | 经常自动补全虚构指标 |
| **隐私安全** | `workspace/` 与 `output/` 默认被 `.gitignore` 忽略 | 本地或云端 | 需把完整简历传给第三方服务器 |

---

## 30 秒快速体验（零第三方依赖）

仓库内置了 100% 虚构示例数据，拉下来直接可跑：

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m career_radar demo --out output/demo
```

### 日常盯目标公司官方岗位（完整 4 步闭环）

```bash
# 1. 初始化私有工作区（已被 .gitignore 忽略，不会误提交）
PYTHONPATH=src python3 -m career_radar init --dir workspace

# 2. 按目标配置执行增量扫描（可先用预设试跑 1 页）
PYTHONPATH=src python3 -m career_radar scan \
  --config presets/china-mnc-industrial.json \
  --db workspace/career_radar.db \
  --out output/scan \
  --max-pages 1

# 3. 查看活跃岗位数与最近扫描日志
PYTHONPATH=src python3 -m career_radar status --db workspace/career_radar.db
```

### 证据型匹配与双语简历生成

1. 让你的 AI 助手（Antigravity / Claude Code / Codex）按 [skills/career-radar-matcher/SKILL.md](skills/career-radar-matcher/SKILL.md) 对照 `output/scan/scan_digest.json` 和你的私有档案生成匹配 JSON；
2. 过确定性防幻觉校验并输出岗位卡（发现无依据指标或无效编号时以退出码 `2` 拦截）：

```bash
PYTHONPATH=src python3 -m career_radar apply-match \
  --match-json output/scan/match.json \
  --profile workspace/master_profile.md \
  --projects workspace/project_library.md \
  --out output/scan/jobs/verified-card.md
```

3. 按目标岗位选出最相关项目并导出中英双语 A4 简历（加 `--format pdf` 需先安装 `pip install "career-radar[pdf]"`）：

```bash
PYTHONPATH=src python3 -m career_radar resume \
  --resume workspace/resume.json \
  --out output/resumes \
  --lang both \
  --format html \
  --jd output/scan/jobs/verified-card.md \
  --max-projects 3
```

---

## 实跑输出示例

由 `career-radar apply-match` 基于虚构模板实际校验生成（完整示例见 [examples/sample_grounded_job_card.md](examples/sample_grounded_job_card.md)）：
- 包含 **Evidence Validation: `PASSED`** 徽章、每条亮点绑定的对应 `P1..Pn` 编号、显式能力缺口清单、投递前待核实问题，以及面向猎头/HR 转发的 **5 行 `Recruiter Brief`**。

---

## 当前进度与路线图（v0.1.0）

| 里程碑 | 状态 | 覆盖范围 |
| :--- | :--- | :--- |
| **M0 — 离线底座与模板** | ✅ 已完成 | 领域模型、确定性哈希、SQLite 增量库、规则初筛、双语 HTML 渲染、`init`/`demo` CLI |
| **M1 — 官方 ATS 实网适配器** | ✅ 已完成 | SmartRecruiters / Greenhouse / Lever / Workday 实网拉取、单站错误隔离、`scan`/`status` CLI |
| **M2 — 证据匹配与防幻觉校验** | ✅ 已完成 | ASCII 词边界过滤、按需完整 JD 补全、`apply-match` 校验器与 BYOA `SKILL.md` |
| **M3 — 截断保护与简历构建** | ✅ 已完成 | `FetchBatch` 截断不误标下架、JD 自动选材、可选 ReportLab PDF 导出、`resume` CLI |
| **M4 — v0.1 发布包装** | ✅ 已完成 | MIT `LICENSE`、CI 与每日定时 Actions 模板、双语 README 与真实校验样例卡 |
| **v0.2 — 下一阶段** | ⏳ 规划中 | 只读 MCP Server（方便在 IDE/对话里直接查询新岗与缺口）、可选无头 API 适配器 |

---

## 相关文档与隐私约定

- `workspace/`、`output/`、`*.db` 与 `.env` 均在 `.gitignore` 中排除；仓库内严禁存放真实个人信息或前雇主未公开资料。
- 详细文档：[docs/PRD.md](docs/PRD.md) · [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · [PROGRESS.md](PROGRESS.md) · [CHANGELOG.md](CHANGELOG.md)
