# TogoSpace Dockerfile
# 基于 Ubuntu 24.04 LTS 构建
#
# 构建方式：
#   1. 确保 frontend 子模块已初始化：git submodule update --init --recursive
#   2. docker build -t togospace:0.3.8 .
#   3. docker run -d -p 8080:8080 -v togospace-storage:/storage togospace:0.3.8

# ============================================
# Stage 1: 构建前端
# ============================================
FROM ubuntu:24.04 AS frontend-builder

# 安装 Node.js
RUN apt-get update && apt-get install -y \
    curl \
    ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build/frontend

# 复制前端代码（需要在构建前执行 git submodule update --init --recursive）
# 使用 npm ci 要求 lock 文件存在且一致，避免静默 npm install 导致依赖漂移
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

# ============================================
# Stage 2: 最终镜像
# ============================================
FROM ubuntu:24.04

LABEL maintainer="数字人生 Team"
LABEL description="数字人生 (Digital Life) - Multi-Agent Chat Room Framework"
LABEL version="0.3.8"

# 设置环境变量
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TOGOSPACE_HOME=/opt/togospace \
    STORAGE_ROOT=/storage \
    TOGOSPACE_RUN_ENV=docker

# 安装 Python 及运行依赖。
# 注：gh/openssh-client/imagemagick/jq/tree/rsync 等调试/工具未纳入生产镜像，
# 以缩小攻击面；如需调试请基于本镜像构建 dev 变体。
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    curl \
    wget \
    ca-certificates \
    git \
    tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-chi-sim \
    tesseract-ocr-chi-tra \
    file \
    zip \
    unzip \
    sqlite3 \
    iputils-ping \
    && rm -rf /var/lib/apt/lists/*

# 安装 tini（轻量级 init，优雅关闭 + 回收僵尸进程）
RUN apt-get update -qq && apt-get install -y -qq tini && rm -rf /var/lib/apt/lists/*

# 创建应用目录和数据目录
RUN mkdir -p ${TOGOSPACE_HOME} ${STORAGE_ROOT}

WORKDIR ${TOGOSPACE_HOME}

# 先复制 requirements.txt 并安装依赖（利用 Docker 层缓存：src 变化不触发重装）
COPY requirements.txt ${TOGOSPACE_HOME}/requirements.txt

# 创建 Python 虚拟环境并安装依赖（含 markitdown，隔离在 venv 内）
RUN python3 -m venv .venv \
    && .venv/bin/pip install --upgrade pip \
    && .venv/bin/pip install -r requirements.txt \
    && .venv/bin/pip install "markitdown[all]" \
    && rm -rf /root/.cache/pip

# 复制后端源代码和资源文件（变更频繁，放依赖安装之后）
COPY src/ ${TOGOSPACE_HOME}/src/
COPY assets/ ${TOGOSPACE_HOME}/assets/

# 复制前端构建产物
COPY --from=frontend-builder /build/frontend/dist ${TOGOSPACE_HOME}/assets/frontend

# 创建非 root 运行用户并授予数据/应用目录权限
RUN useradd --create-home --shell /usr/sbin/nologin --uid 1000 togospace \
    && chown -R togospace:togospace ${TOGOSPACE_HOME} ${STORAGE_ROOT}

# 创建默认配置文件
RUN mkdir -p ${STORAGE_ROOT} \
    && if [ ! -f ${STORAGE_ROOT}/setting.json ]; then \
        cp ${TOGOSPACE_HOME}/assets/config_template.json ${STORAGE_ROOT}/setting.json; \
    fi \
    && chown -R togospace:togospace ${STORAGE_ROOT}

# 暴露端口
EXPOSE 8080

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/system/status.json || exit 1

# 切换到非 root 用户运行
USER togospace

# 启动命令（使用 tini 作为 entrypoint，优雅关闭 + 回收僵尸进程）
WORKDIR ${TOGOSPACE_HOME}/src
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["../.venv/bin/python3", "backend_main.py", "--config-dir", "/storage"]