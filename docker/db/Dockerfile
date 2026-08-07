# PostgreSQL 16 + zhparser（中文全文检索分词）
#
# 构建：docker compose build db
# 验证：docker exec cs-backend-db psql -U postgres -d domefff -c "SELECT * FROM pg_available_extensions WHERE name='zhparser';"

FROM postgres:16

# 中国境内 Debian 镜像源（可通过 --build-arg 覆盖）
ARG APT_MIRROR=http://mirrors.aliyun.com/debian
ARG APT_SECURITY_MIRROR=http://mirrors.aliyun.com/debian-security
RUN if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
      sed -i \
        -e "s#https\?://deb.debian.org/debian-security#${APT_SECURITY_MIRROR}#g" \
        -e "s#https\?://deb.debian.org/debian#${APT_MIRROR}#g" \
        /etc/apt/sources.list.d/debian.sources; \
    fi

# 编译安装 SCWS + zhparser；完成后清理编译依赖以减小镜像体积
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc make postgresql-server-dev-16 curl ca-certificates \
    && curl -sL https://github.com/hightman/scws/archive/refs/tags/1.2.3.tar.gz \
        | tar xz -C /tmp \
    && cd /tmp/scws-1.2.3 \
    && ./configure --prefix=/usr/local && make -j$(nproc) && make install && ldconfig \
    && curl -sL https://github.com/amutu/zhparser/archive/refs/heads/master.tar.gz \
        | tar xz -C /tmp \
    && cd /tmp/zhparser-master \
    && make -j$(nproc) && make install \
    && rm -rf /tmp/scws-1.2.3 /tmp/zhparser-master \
    && apt-get purge -y gcc make postgresql-server-dev-16 curl ca-certificates \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*
