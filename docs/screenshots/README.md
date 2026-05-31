# 演示截图采集指南

本目录存放 README 引用的 5 张界面截图。以下是采集步骤——在**你的浏览器**里按步骤截图，保存为对应文件名即可。

## 准备

```bash
source .venv/bin/activate
uvicorn app.main:app --reload
# 浏览器打开 http://localhost:8000/
```

截图前建议：窗口宽度 ~1100px、关闭浏览器 devtools、清掉上一次的审查结果（刷新页面）。

## 演示用的 3 个真实 PR（已实测）

| 体量 | PR URL | 实测结果 |
| --- | --- | --- |
| 小 | `https://github.com/pallets/click/pull/3534` | 45 行，评分 90，1 个 high 风险 |
| 中 | `https://github.com/pytest-dev/pytest/pull/14520` | 1,157 行，评分 95，0 风险 |
| 大 | `https://github.com/scipy/scipy/pull/25236` | 18,794 行 / 51 文件，**触发 hunk 分块（2 块）**，评分 90，3 风险 |

> 大 PR（scipy）约 10s 出结果、~103K token；确保 `.env` 里 `DEEPSEEK_API_KEY` 已配置。

## 5 张截图

| 文件名 | 内容 | 怎么截 |
| --- | --- | --- |
| `home.png` | 首页 UI | 打开 http://localhost:8000/ ，截整页（banner + 输入区） |
| `reviewing.png` | 审查中状态 | 填入大 PR（scipy）URL 点「开始审查」，在出现 spinner +「正在调用 DeepSeek 审查…」时截图 |
| `result-small.png` | 小 PR 结果 | 用 click#3534 跑完，截评分圈 + summary + 那条 high 风险卡片 |
| `result-large.png` | 大 PR 分块结果 | 用 scipy#25236 跑完，截 summary（含「主要变更」+「…d_test.f (片段 1/1)」两段分块标注）+ 风险列表 |
| `markdown-export.png` | Markdown 导出 | 任一结果页点「📄 查看 Markdown」展开纯文本报告后截图 |

保存到本目录、用上表的文件名，README 顶部与「界面截图」区即会自动显示。
