"""RBAC service 层单元测试。

不依赖真实数据库：用 AsyncMock 替换 RBACRepository，验证
- update_role / update_permission 的不存在返回 None 与字段写入逻辑
- get_user_roles 的空用户返回空列表
- check_permission 的超级用户短路与普通用户聚合判断

聚焦于本次修复（DRY、分层、新增只读方法），DB 集成行为由
tests/integration/test_rbac_db.py 覆盖。
"""
