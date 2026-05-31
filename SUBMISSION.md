# 提交报告 — AI PR Review 助手

> 七牛云 × XEngineer 暑期实训营 · 题目三

## 链接

| 项 | 链接 |
| --- | --- |
| 代码仓库 | https://github.com/heziamo/qiniu-pr-review-assistant |
| 在线 Demo | http://117.50.181.92:8000/ |
| 设计文档 | [docs/DESIGN.md](docs/DESIGN.md) |

## 核心功能清单

- **PR diff 拉取**：输入 GitHub PR URL，自动解析并拉取每个文件的 unified diff（PyGithub）。
- **多维度结构化审查**：调用 LLM 从正确性 / 安全 / 性能 / 风格 / 可维护性五个维度审查，输出 JSON。
- **风险分级与定位**：每条风险带 `severity`（critical/high/medium/low）、`type`、`file:line`、描述与修改建议；附 0–100 总评分。
- **大文件 hunk 分块**：单文件 diff > 2000 行时按 `@@` hunk 拆分分别审查再合并，控制上下文与成本。
- **多模型可切换**：默认 DeepSeek-V3，一个环境变量切到 Claude，架构上可扩展 GPT 等。
- **可视化前端**：深色卡片式单页，评分圈 + 风险卡片染色 + 折叠 + 复制 Markdown 报告 + 移动端适配。
- **一键回写 PR 评论**：可选地把审查报告作为评论发布回 PR。
- **工程化保障**：429/5xx 指数退避重试、大 PR 限流保护、`/metrics` 监控、Docker 多阶段部署。

## 技术亮点（3 条）

1. **LLMClient 抽象层 —— 成本与可扩展兼得**
   面向统一接口 `chat(messages) -> str` 编程，上层审查逻辑与厂商解耦。默认用 DeepSeek-V3，
   同等输入下单次成本约为 Claude 的 **1/20**（实测大 PR：DeepSeek ≈¥0.10 vs Claude ≈¥2.3）；
   新增厂商只需加一个子类，零侵入。

2. **结构化 JSON 审查 + 大文件 hunk 分块**
   严格 JSON schema 输出，前端可直接渲染为分级风险卡片；对超长单文件按 diff hunk 拆分、
   贪心合并、分块审查后取最差分块主导总分，兼顾覆盖率、可定位性与 token 成本。

3. **工程化完备 + 真实实测**
   重试退避 / 大 PR 保护 / 内存监控指标 / 非 root 多阶段 Docker 镜像（约 207MB）/ 公网部署；
   并用 3 个真实开源 PR（45 行 / 1157 行 / 18794 行触发分块）跑出 token、耗时、成本实测数据（见设计文档 §6）。

## 30 秒演示视频脚本

| 时间 | 画面 | 旁白 |
| --- | --- | --- |
| 0–4s | 首页 banner | "大型 PR 人工 review 耗时又易漏。这是一个用大模型辅助审查的助手。" |
| 4–10s | 粘贴一个小型 PR URL，点「开始审查」，spinner + 「正在调用 DeepSeek 审查」 | "粘贴 GitHub PR 链接，一键审查。" |
| 10–20s | 结果页：评分圈 + 按严重程度染色的风险卡片（file:line / 类型 / 描述 / 建议） | "几秒出结构化报告：总评分、分级风险、精确到文件行、附修改建议。" |
| 20–26s | 展示大 PR 的 hunk 分块结果 + 点「复制 Markdown 报告」/ 勾选发评论回 PR | "大文件自动分块审查；报告可一键复制或发回 PR。" |
| 26–30s | 回到 DESIGN 架构图 / 成本对比 | "多模型抽象、Docker 部署，成本仅 Claude 的 1/20。" |

> 录制建议：用小型 PR（如 `pallets/click#3534`）演示，审查在数秒内完成，节奏紧凑。
