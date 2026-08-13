-- ============================================================================
-- 同步 alembic_version 表中的旧 revision id -> 新 revision id
-- ============================================================================
-- 背景：迁移文件 revision 占位符 id 已规范化为真实 hex（见 2026-08-14 自检修复）。
--       若某环境（本地 / 预发 / 生产）的数据库已应用过这些迁移，其 alembic_version
--       表仍记录旧 id，会导致 `alembic upgrade head` 误判 head 不匹配并试图重跑迁移。
-- 作用：将已部署库中已落库的旧 id 更新为新 id，使 Alembic  lineage 与文件一致。
--
-- 用法：
--   1) 备份： pg_dump ... > backup_before_alembic_sync.sql
--   2) 连接目标库执行本文件：
--        psql "$DATABASE_URL" -f scripts/sync_alembic_version_ids.sql
--   3) 校验： alembic heads   （应只剩 d3e4f5a6b7c8）
--            alembic current  （应为 d3e4f5a6b7c8）
--
-- 仅当 alembic_version 当前记录的是旧 id 时才需要执行；全新库（从头迁移）无需本脚本。
-- 旧 id 与新 id 一一对应：
--   d6e7f8g9h0i1 -> 9f1c2a3b4d5e
--   h2i3j4k5l6m7 -> 7e8f9a0b1c2d
--   c8d9e0f1a2b3 -> 5c6d7e8f9a0b
--   e5f6g7h8i9j0 -> 3a4b5c6d7e8f
--   f0a1b2c3d4e5 -> 1b2c3d4e5f6a
--   22232b182a66 -> 8c9d0e1f2a3b
--   22232b182a66b -> 6e7f8a9b0c1d
--   22232b182a66c -> 4f5a6b7c8d9e
--   22232b182a66d -> 2a3b4c5d6e7f
-- ============================================================================

UPDATE alembic_version SET version_num = '9f1c2a3b4d5e' WHERE version_num = 'd6e7f8g9h0i1';
UPDATE alembic_version SET version_num = '7e8f9a0b1c2d' WHERE version_num = 'h2i3j4k5l6m7';
UPDATE alembic_version SET version_num = '5c6d7e8f9a0b' WHERE version_num = 'c8d9e0f1a2b3';
UPDATE alembic_version SET version_num = '3a4b5c6d7e8f' WHERE version_num = 'e5f6g7h8i9j0';
UPDATE alembic_version SET version_num = '1b2c3d4e5f6a' WHERE version_num = 'f0a1b2c3d4e5';
UPDATE alembic_version SET version_num = '8c9d0e1f2a3b' WHERE version_num = '22232b182a66';
UPDATE alembic_version SET version_num = '6e7f8a9b0c1d' WHERE version_num = '22232b182a66b';
UPDATE alembic_version SET version_num = '4f5a6b7c8d9e' WHERE version_num = '22232b182a66c';
UPDATE alembic_version SET version_num = '2a3b4c5d6e7f' WHERE version_num = '22232b182a66d';
