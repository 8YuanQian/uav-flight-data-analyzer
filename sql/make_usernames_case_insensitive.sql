-- 为现有 users 表增加大小写不敏感的唯一约束；若存在冲突，事务会回滚。
BEGIN;

CREATE UNIQUE INDEX IF NOT EXISTS users_username_lower_unique_idx
    ON users (LOWER(username));

COMMIT;
