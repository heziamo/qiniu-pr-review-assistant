# qiniu-pr-review-assistant

AI-powered GitHub PR review assistant —— 七牛云 × XEngineer 暑期实训营 **题目三**

基于 **FastAPI + Anthropic Claude SDK** 的 GitHub Pull Request 自动审查助手：拉取指定 PR 的 diff，调用 Claude 进行多维度代码审查，并可将结果作为评论发布回 PR。

## 功能

- 拉取任意 GitHub 仓库指定 PR 的元信息与文件 diff（PyGithub）
- 调用 Claude（默认 `claude-opus-4-8`）对 diff 做正确性 / 安全性 / 可维护性 / 性能 / 测试五维审查
- 采用 **prompt caching**：把稳定的审查规范缓存为前缀，跨多次审查复用，节省约 90% 输入成本
- 可选地把审查报告作为评论发布回 PR

## 技术栈

| 组件 | 用途 |
| --- | --- |
| FastAPI + Uvicorn | HTTP 服务 |
| Anthropic SDK | 调用 Claude 审查（流式 + 自适应思考 + prompt caching） |
| PyGithub | 拉取 PR diff、发布评论 |
| Pydantic / pydantic-settings | 数据模型与配置 |

## 目录结构

```
app/
├── __init__.py
├── main.py           # FastAPI 入口与路由
├── github_client.py  # GitHub 拉取 diff / 发布评论
├── reviewer.py       # 调用 Claude 审查（含 prompt caching）
└── models.py         # Pydantic 模型与配置
```

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置密钥
cp .env.example .env
# 编辑 .env，填入 ANTHROPIC_API_KEY 与 GITHUB_TOKEN

# 3. 启动服务
uvicorn app.main:app --reload
```

服务启动后访问 http://127.0.0.1:8000/docs 查看交互式 API 文档。

## API

### `POST /review`

```bash
curl -X POST http://127.0.0.1:8000/review \
  -H "Content-Type: application/json" \
  -d '{"repo": "octocat/Hello-World", "pr_number": 42, "post_comment": false}'
```

响应包含审查报告（Markdown）以及 token 用量，其中 `cache_read_tokens` 可用于验证
prompt caching 是否命中（第二次审查同一规范前缀时应 > 0）。

### `GET /health`

健康检查。

## 环境变量

| 变量 | 必填 | 说明 |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | ✅ | Anthropic API Key |
| `GITHUB_TOKEN` | ✅ | GitHub Personal Access Token（`repo` / `public_repo` 权限） |
| `ANTHROPIC_MODEL` | ❌ | 模型，默认 `claude-opus-4-8` |
