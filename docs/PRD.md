# Career Radar — 产品需求文档（PRD）

> **版本**：v0.1 (M0) · **定位**：Local-First Official ATS Job Radar & Evidence-Grounded Resume Kit  
> **核心理念**：盯一手官方岗位增量、守住真实证据边界、输出克制清晰的求职材料。

---

## 1. 项目定位与核心痛点

### 1.1 我们解决哪两个真实痛点
1. **官方招聘信息分散且难追踪**：优质外企与科技公司通常将最新岗位第一时间发布在自家的官方 ATS（Applicant Tracking System，如 SmartRecruiters、Workday、Greenhouse、Lever）上，聚合平台往往滞后或信息失真；手动天天刷十几家官网既耗时又容易漏掉新开岗窗口期。
2. **主流 AI 求职工具容易“编造履历”**：多数 AI 简历工具直接把 JD 和简历丢进大模型“一键改写”，经常悄悄虚构指标、夸大主导权或套用模板空话，不仅经不起资深面试官追问，还存在把私人档案上传第三方平台的隐私风险。

### 1.2 双重价值目标
- **立即可用的个人提效系统**：零服务器成本、全本地运行，按候选人自定义的证据库自动筛岗、记录缺口并生成针对性求职材料。
- **清晰克制的开源工程标杆**：用干净的架构、开箱即用的双语简历模板与“证据溯源”机制吸引同样重视工程诚实度的开发者（目标：100+ GitHub Stars）。

---

## 2. 目标用户与明确非目标（Non-Goals）

### 2.1 目标用户
- 正在准备切换赛道或瞄准特定目标企业（外企、科技公司、研究机构等）的工程师、数据分析师与研究人员。
- 习惯用 Markdown / Git / 本地 AI 编程助手（Antigravity、Claude Code、Codex、Cursor 等）管理个人资料与项目证据的技术求职者。

### 2.2 v1 明确非目标（坚决不做）
- **不爬反爬严苛的国内第三方聚合站**（如 Boss 直聘、猎聘等）：避免维护易碎爬虫、账号封禁与合规风险。
- **不做猎头/HR 端 SaaS 或批量候选人筛选系统**：v1 坚持候选人视角与本地信任；猎头协作仅通过每条高匹配岗位自动导出的 **5 行 `Recruiter Brief`** 轻量化支持（见 `FR-04`）。
- **不做脱离证据的简历吹牛改写与自动海投**：系统不得无中生有地添加百分比指标、项目角色或未验证技术栈。
- **不强制依赖云端数据库、常驻后台服务或付费 API**：核心链路（抓岗、去重、规则初筛、双语 HTML 简历渲染）必须纯本地零付费可运行。

---

## 3. 核心用户旅程（4 步闭环）

```text
1. init   ──▶ 生成本地 workspace/（targets.json + master_profile.md + project_library.md）
2. scan   ──▶ 从官方 ATS 公开接口增量拉取岗位，写入本地 SQLite 识别 NEW / UPDATED / CLOSED
3. match  ──▶ 两级过滤：规则硬筛选（零 Token）→ 证据可追溯匹配，输出岗位评估卡 + Recruiter Brief
4. resume ──▶ 按目标岗位从 project_library 挑出 3–4 个真实项目，生成干净的中英双语 HTML/PDF 简历
```

---

## 4. 详细功能需求（Functional Requirements）

### `FR-01` 官方 ATS 适配器（Official ATS Adapters）— **P0**
- **描述**：通过标准化适配器接口拉取目标公司官方 ATS 公开列表与岗位详情，首期覆盖 `SmartRecruiters`、`Greenhouse`、`Lever`、`Workday` 四大主流系统，并提供离线 `FixtureAdapter` 用于本地测试与演示。
- **核心约束**：
  - 所有适配器统一输出标准化 `JobPosting` 数据模型（含 `company`、`external_id`、`title`、`location`、`department`、`url`、`description`、`content_hash`）。
  - 单家公司请求失败、超时或限流时必须隔离报错，不得中断同一批次其他公司的扫描。
  - 遵守礼貌请求间隔与可配置超时，显式处理 Workday 不同租户路径与分页结构差异。
- **验收标准**：
  - M0：`FixtureAdapter` 与 4 类适配器契约及 Endpoint 构造器全部就绪并通过单元测试。
  - M1：**已完成** — 4 类真实 HTTP 适配器、分页/限流与单站错误隔离已实现并通过录制响应单测；`BoschGroup`、`Anthropic`、`Scale AI`、`Philips`、`ABB` 完成首轮实网烟雾验证。

### `FR-02` 本地增量岗位存储（Incremental SQLite Job Store）— **P0**
- **描述**：使用本地 SQLite 存储扫描批次（`scan_runs`）、岗位快照（`jobs`）及变更事件（`job_events`）。
- **核心约束**：
  - 基于岗位规范化内容生成确定性 SHA-256 `content_hash`，精确区分 `NEW`（新开）、`UPDATED`（同 ID 内容变更）、`UNCHANGED`（无变化）、`CLOSED`（上次活跃但本次全量扫描不再出现）。
  - 同一份静态输入连续扫描两次时，第二次必须全部归为 `UNCHANGED`，实现严格幂等。
- **验收标准**：
  - M0：SQLite Schema 与增量状态机实现完成，自动化测试验证 `NEW → UPDATED / UNCHANGED / CLOSED` 全状态流转与幂等性。

### `FR-03` 证据分级档案与项目库模板（Evidence-First Profile & Project Library）— **P0**
- **描述**：提供脱敏可复用的 `master_profile.template.md` 与 `project_library.template.md`，引导用户建立个人唯一事实源（SSOT）。
- **核心约束**：
  - 强制使用三态证据标签：`[Verified]`（代码/报告/产出已验证）、`[Self-reported]`（自述经历但无公开佐证）、`[Gap]`（缺失或待补能力）。
  - 显式划分“仅限私人决策参考的内部注记”与“允许写入对外简历和沟通的公开口径”。
- **验收标准**：
  - M0：提供完整脱敏模板，且示例数据 100% 虚构，不含任何真实个人隐私。

### `FR-04` 两级过滤与证据可追溯匹配（Two-Stage Filter & Grounded Matcher）— **P1**
- **描述**：对新增或更新岗位先做零成本规则过滤，再做基于个人证据库的深度评估。
- **Stage 1 — 规则硬过滤（M0 已实现）**：
  - 按 `locations`（城市/远程）、`include_keywords`、`exclude_keywords` 过滤，输出透明的 `matched_reasons` 与 `excluded_reasons`。
- **Stage 2 — 证据匹配与 Recruiter Brief（M2 实现 · 采用方案 A 零额外 API 费为主路径）**：
  - **主路径（BYOA / MCP + Skill，零额外 API 费）**：`scan` 导出结构化 `scan_digest.json` 与初筛岗位卡后，直接由用户已有会员订阅的本地 AI 编程助手（Antigravity、Claude Code、Codex）通过 MCP / Skill 读取候选岗位与本地 `master_profile.md` / `project_library.md` 完成深度证据匹配并回写岗位卡，无需额外充开发者 API 费。
  - **可选回退路径（无人值守自动化）**：同时保留可插拔 OpenAI 兼容 API 客户端接口，供需要在 GitHub Actions 等无头环境全自动定时运行的开源用户选用。
  - **强制防幻觉输出约束**：每条匹配点必须绑定 `project_library` 真实编号，输出**匹配证据**、**真实缺口清单**、**投递前待核实问题**与 **5 行 `Recruiter Brief`**，并对未绑定编号的声明做确定性校验阻断。
- **验收标准**：
  - M0：规则匹配器与 Markdown 岗位评估卡（含 `Recruiter Brief` 槽位）可离线跑通并有完整测试。
  - M2：**已完成** — 词边界过滤、按需完整 JD 补全、确定性证据校验器（`evidence_validator.py`）、`apply-match` CLI 与配套 `skills/career-radar-matcher/SKILL.md` 均已实现并通过单元测试（含拦截未绑定编号和无依据百分比断言）。

### `FR-05` 双语简历生成器（Clean Bilingual Resume Builder）— **P1**
- **描述**：从结构化 `resume.json` 生成清爽、易读、可直接投递的中英双语 A4 简历。
- **设计要求**：
  - 信息结构清晰、适当留白、日期右对齐、浅灰细分隔线、悬挂缩进要点列表，简洁专业而不沉闷。
  - M0：纯 Python 标准库生成可直接浏览器打印/另存 PDF 的高质量 A4 HTML（零第三方依赖）。
  - M3：增加可选 ReportLab PDF 原生导出（`pip install "career-radar[pdf]"`）及按匹配项目自动筛选/排序能力。
- **验收标准**：
  - M0：`templates/resume.demo.json` 可一键输出 EN / CN 两份完整 HTML 简历并完成 HTML 转义与内容断言测试。

### `FR-06` 自动化与 Agent 接入（Automation & MCP Integration）— **P2**
- **描述**：降低每日使用门槛，并方便与现有 AI 编程助手联动。
- **能力范围（M4）**：
  - 提供 GitHub Actions 定时工作流模板，实现零服务器每日增量扫描与摘要推送。
  - 提供可选只读 MCP Server，让 Antigravity / Claude Code / Codex 可直接查询“今天有哪些高匹配新岗”“该岗和我的能力缺口在哪里”。

---

## 5. 非功能需求与隐私红线

1. **隐私默认不出本机**：`workspace/`、`*.db`、`*.sqlite*`、`output/`、`.env` 默认写入 `.gitignore`。仓库代码中禁止出现任何真实个人姓名、联系方式或前雇主未公开信息。
2. **运行环境友好**：核心代码兼容 **Python 3.9+**，M0 核心仅使用标准库，无需用户折腾复杂依赖即可运行演示与单测。
3. **诚实状态表达**：`README.md` 与 `PROGRESS.md` 必须如实区分“已实现并测试”与“规划待实现”的能力，不夸大完成度。

---

## 6. 里程碑路线图（M0–M4）

| 里程碑 | 目标范围 | 关键交付物 | 验收方式 |
| :--- | :--- | :--- | :--- |
| **M0** | 需求规范、架构、模板与可运行底座 | `PRD.md`、`ARCHITECTURE.md`、模板与预置配置、核心模型、SQLite 增量库、规则过滤、双语 HTML 简历、离线 Demo CLI 与单测 | ✅ 已完成（7 项单测通过） |
| **M1** | 真实官方 ATS 接入 | SmartRecruiters / Greenhouse / Lever / Workday HTTP 拉取、分页与限流控制、单站错误隔离、`scan` / `status` CLI 与 `scan_digest.json` | ✅ 已完成（适配器单测 + 公开端点实测） |
| **M2** | 证据型匹配（方案 A 优先）与猎头简报 | ASCII 词边界过滤、按需完整 JD 补全、防幻觉证据 ID/数字校验器、`apply-match` CLI 与配套 BYOA `SKILL.md`（零额外 API 费） | ✅ 已完成（18 项单测 + 中国区实测通过） |
| **M3（本阶段）** | 截断保护、项目选材与双语导出 | `FetchBatch` 截断安全下架保护、`selector.py` 自动选材、可选 ReportLab PDF 导出与 `resume` CLI | ✅ 已完成（23 项单测 + CLI 烟雾通过） |
| **M4** | 自动化与开源发布 | `LICENSE`、CI 与 GitHub Actions 每日巡检模板、只读 MCP Server、双语发布图与 v0.1 Release | ⏳ 待实现 |
