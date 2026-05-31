# syntax=docker/dockerfile:1.6
# ───── 第一阶段：builder（装依赖，结果拷到 runtime） ─────
FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

WORKDIR /build
COPY requirements.txt .
# 把依赖装到独立目录 /install，方便整段拷到 runtime
RUN pip install --prefix=/install -r requirements.txt

# ───── 第二阶段：runtime（最小镜像） ─────
FROM python:3.11-slim AS runtime

# 非 root 用户运行（最小权限原则）
RUN useradd -m -u 1000 app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH=/install/bin:$PATH \
    PYTHONPATH=/install/lib/python3.11/site-packages

# 拷贝 builder 阶段已装好的依赖
COPY --from=builder /install /install

WORKDIR /app
COPY --chown=app:app app ./app
COPY --chown=app:app scripts ./scripts

USER app
EXPOSE 8000

# 健康检查：每 30s 探一次 /health
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=3).status==200 else 1)"

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
