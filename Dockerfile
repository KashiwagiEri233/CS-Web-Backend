# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# builder：装依赖。与 CI 一致用 requirements.lock（带哈希），保证镜像里的依赖
# 与流水线校验过的完全一致；--require-hashes 下任何未锁定的传递依赖都会直接报错。
# ---------------------------------------------------------------------------
FROM python:3.13-slim AS builder

# 中国境内镜像源（可通过 --build-arg 覆盖）
ARG APT_MIRROR=http://mirrors.aliyun.com/debian
ARG APT_SECURITY_MIRROR=http://mirrors.aliyun.com/debian-security
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

# 替换 Debian 软件源；当前阶段后续如需 apt 安装也会使用国内镜像
RUN if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
      sed -i \
        -e "s#https\?://deb.debian.org/debian-security#${APT_SECURITY_MIRROR}#g" \
        -e "s#https\?://deb.debian.org/debian#${APT_MIRROR}#g" \
        /etc/apt/sources.list.d/debian.sources; \
    fi

ENV PIP_INDEX_URL=${PIP_INDEX_URL} \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# psycopg2-binary 是 wheel，无需编译工具链；这里只装 pip 依赖，保持 builder 精简。
COPY requirements.lock ./
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --require-hashes -r requirements.lock


# ---------------------------------------------------------------------------
# runtime：只拷 venv 和应用代码，不带构建产物
# ---------------------------------------------------------------------------
FROM python:3.13-slim AS runtime

ARG APT_MIRROR=http://mirrors.aliyun.com/debian
ARG APT_SECURITY_MIRROR=http://mirrors.aliyun.com/debian-security
RUN if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
      sed -i \
        -e "s#https\?://deb.debian.org/debian-security#${APT_SECURITY_MIRROR}#g" \
        -e "s#https\?://deb.debian.org/debian#${APT_MIRROR}#g" \
        /etc/apt/sources.list.d/debian.sources; \
    fi

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

# 非 root 运行：容器逃逸/RCE 时限制影响面
RUN useradd --create-home --uid 10001 appuser

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv

# 只拷运行期真正需要的东西（.dockerignore 已排除 tests/docs/.env 等）
COPY --chown=appuser:appuser app ./app
COPY --chown=appuser:appuser alembic ./alembic
COPY --chown=appuser:appuser alembic.ini run.py ./

# 日志落盘目录（ER-40）：prod 日志写 /app/logs；以 appuser 属主预建，
# 供命名卷 logs: 首次挂载时继承属主，避免容器非 root 下 PermissionError 降级为仅控制台。
RUN mkdir -p /app/logs && chown appuser:appuser /app/logs

USER appuser

EXPOSE 8000

# 健康检查打 /health（liveness 浅检查）。就绪探针 /readyz 会探 DB，
# 更适合放在编排层（k8s readinessProbe），不放这里以免容器反复被判不健康。
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status == 200 else 1)"

# 多 worker（ER-37）：默认 4，可用 UVICORN_WORKERS 覆盖（编排层负责进程数）。
# --timeout-graceful-shutdown 30（ER-36 优雅停机）：SIGTERM 后最多等 30s 让在途请求结束。
# exec 形式使 uvicorn 成为 PID 1，确保信号直达、优雅停机生效。
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${UVICORN_WORKERS:-4} --timeout-graceful-shutdown ${UVICORN_GRACEFUL_SHUTDOWN:-30}"]
