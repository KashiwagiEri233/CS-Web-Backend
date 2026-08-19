"""FastAPI RBAC Framework 应用包。"""

# 应用版本单一事实源：FastAPI(version=...)、OTel service.version、启动日志均引用此处，
# 升级版本只改这一处。
#
# 版本号规则（2026-08-19 起）：
#   - 机器版本 __version__ 保持 PEP 440 / semver 合规的三段式（如 "1.0.0"），
#     因为 npm / PEP 440 不允许 4 段版本号或非 ASCII 字符（会破坏打包与 uv.lock）。
#   - __codename__ 是「发布代号」：可为节日标签（如 "七夕"）或 MMDD 日期（如 "0819"），
#     纯展示用途，拼成 "1.0.0.七夕" / "1.0.0.0819"。前端页脚、CHANGELOG 标题用展示版，
#     打包文件（pyproject/package.json 的 version 字段/uv.lock）只用 __version__ 核心段。
__version__ = "1.0.0"
__codename__ = "七夕"
