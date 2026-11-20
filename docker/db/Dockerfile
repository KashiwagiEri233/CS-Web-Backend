# PostgreSQL 18 + zhparser（中文全文检索分词）
#
# 构建：docker compose build db
# 验证：docker exec cs-db psql -U postgres -d domefff -c "SELECT * FROM pg_available_extensions WHERE name='zhparser';"
#
# 说明：
#   - 基线版本跟随生产环境的 PostgreSQL 18，避免开发/生产大版本漂移
#   - 使用 Debian 版官方镜像：其 LLVM 工具链完整（llvm-config-19），
#     而 alpine 版缺少 llvm-lto 等链接期工具，无法完成扩展的比特码安装
#   - 编译产物装到 PG 的 pkglibdir/share 后，清理全部编译依赖以压缩体积

FROM postgres:18

# Debian 镜像源（可通过 --build-arg 覆盖）
ARG APT_MIRROR=http://mirrors.aliyun.com/debian
ARG APT_SECURITY_MIRROR=http://mirrors.aliyun.com/debian-security
ARG SCWS_VERSION=1.2.3
ARG SCWS_URL=https://www.xunsearch.com/scws/down
ARG ZHPARSER_REF=master

# 1. 切国内镜像源并安装编译依赖
#    官方镜像编译时启用 --with-llvm，扩展需产出 .bc 比特码，
#    zhparser 的 pgxs 安装阶段会调用 llvm-lto（llvm-19 提供）。
RUN if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
      sed -i \
        -e "s#https\?://deb.debian.org/debian-security#${APT_SECURITY_MIRROR}#g" \
        -e "s#https\?://deb.debian.org/debian#${APT_MIRROR}#g" \
        /etc/apt/sources.list.d/debian.sources; \
    fi \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        gcc make libc6-dev \
        postgresql-server-dev-18 \
        llvm-19 \
        curl ca-certificates bzip2

# 2. 编译安装 SCWS（zhparser 的底层分词库）
#    使用官方发布包而非 GitHub 源码快照：后者只有 configure.ac、无预生成 configure。
RUN curl -fsSL "${SCWS_URL}/scws-${SCWS_VERSION}.tar.bz2" \
        | tar xj -C /tmp \
    && cd /tmp/scws-${SCWS_VERSION} \
    && ./configure --prefix=/usr/local \
    && make -j"$(nproc)" \
    && make install \
    && ldconfig

# 3. 编译安装 zhparser，装入 PG18 的扩展目录
#    SCWS 把头文件装到 /usr/local/include/scws，zhparser 的 Makefile 需显式补全搜索路径。
RUN curl -fsSL "https://github.com/amutu/zhparser/archive/refs/heads/${ZHPARSER_REF}.tar.gz" \
        | tar xz -C /tmp \
    && cd /tmp/zhparser-${ZHPARSER_REF} \
    && PG_CONFIG=/usr/bin/pg_config \
       CFLAGS="-I/usr/local/include -I/usr/local/include/scws" \
       LDFLAGS="-L/usr/local/lib" \
       make -j"$(nproc)" \
    && PG_CONFIG=/usr/bin/pg_config make install

# 4. 清理编译依赖与临时文件；SCWS 的 /usr/local/lib/libscws.so 是运行时依赖，保留
RUN rm -rf /tmp/scws-${SCWS_VERSION} /tmp/zhparser-${ZHPARSER_REF} \
    && apt-get purge -y --auto-remove \
        gcc make libc6-dev postgresql-server-dev-18 llvm-19 curl bzip2 ca-certificates \
    && rm -rf /var/lib/apt/lists/*
