"""测试全局配置。

在导入任何 app.* 模块之前，先确保必需的环境变量就位：
- SECRET_KEY：config.Settings 强制要求，否则实例化即失败
- REDIS_URL：留空 -> 限流走纯内存模式，测试不依赖外部 Redis
环境变量优先级高于 .env 文件，因此即使本机 .env 缺失也能稳定运行。
"""

import os

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-pytest")
os.environ.pop("REDIS_URL", None)  # 确保单元测试不连真实 Redis
