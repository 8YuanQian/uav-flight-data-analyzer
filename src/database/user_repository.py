# 用户凭据与聊天会话归属的数据库操作。

from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from .connection import get_connection


# 用户名触发数据库唯一约束时抛出此异常。
class UsernameAlreadyExists(ValueError):
    pass


# 在同一事务中写入用户和密码哈希，避免产生无密码用户。
def create_user(username: str, password_hash: str) -> dict:
    try:
        # 同一个连接上下文负责提交或回滚：第二次插入失败时不会留下无密码用户。
        with get_connection() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    "INSERT INTO users (username) VALUES (%s) RETURNING id, username, create_at",
                    (username,),
                )
                user = cursor.fetchone()
                # 通过 RETURNING 取得数据库生成的主键，作为 password.user_id。
                cursor.execute(
                    "INSERT INTO password (user_id, password_hash) VALUES (%s, %s)",
                    (user["id"], password_hash),
                )
        return user
    except psycopg.errors.UniqueViolation as exc:
        # 数据库中的用户名唯一索引负责拦截大小写不同的重复注册。
        raise UsernameAlreadyExists(username) from exc


# 即使密码行意外缺失，也保留查询到的用户，随后按密码错误处理。
def find_login_user(username: str) -> dict | None:
    with get_connection() as connection:
        with connection.cursor(row_factory=dict_row) as cursor:
            # LEFT JOIN 让“用户名存在但密码行缺失”仍能被当作密码校验失败处理。
            # 用 LOWER 匹配用户名，查询结果仍返回注册时保存的原始写法。
            cursor.execute(
                """SELECT u.id, u.username, p.password_hash
                   FROM users AS u
                   LEFT JOIN password AS p ON p.user_id = u.id
                   WHERE LOWER(u.username) = LOWER(%s)""",
                (username,),
            )
            return cursor.fetchone()


# 只按有效 JWT 中的用户 ID 列出会话；旧会话没有标题时返回 None。
def list_user_conversations(user_id: int) -> list[dict] | None:
    with get_connection() as connection:
        with connection.cursor(row_factory=dict_row) as cursor:
            # 从原有 thread_ids 数组展开会话，关联新会话保存的首条提问。
            cursor.execute(
                """SELECT threads.thread_id, titles.title
                   FROM users AS u
                   LEFT JOIN LATERAL UNNEST(u.thread_ids) WITH ORDINALITY
                       AS threads(thread_id, position) ON TRUE
                   LEFT JOIN chat_titles AS titles
                       ON titles.thread_id = threads.thread_id AND titles.user_id = u.id
                   WHERE u.id = %s
                   ORDER BY threads.position""",
                (user_id,),
            )
            rows = cursor.fetchall()
            if not rows:
                return None
            return [row for row in rows if row["thread_id"] is not None]


# 检查指定 UUID 是否属于当前用户的会话数组。
def user_owns_thread(user_id: int, thread_id: UUID) -> bool:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            # PostgreSQL 的 @> 是数组包含运算符；它不会仅凭 URL 中的 UUID 授权。
            cursor.execute(
                "SELECT 1 FROM users WHERE id = %s AND thread_ids @> ARRAY[%s::uuid]",
                (user_id, thread_id),
            )
            return cursor.fetchone() is not None


# 在同一事务中登记新会话和首条提问；用户不存在则返回 False。
def add_user_thread(user_id: int, thread_id: UUID, title: str) -> bool:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            # 在一条 UPDATE 内检查并追加，避免把同一会话 ID 重复写入该用户数组。
            cursor.execute(
                """UPDATE users
                   SET thread_ids = CASE
                       WHEN thread_ids @> ARRAY[%s::uuid] THEN thread_ids
                       ELSE array_append(thread_ids, %s::uuid)
                   END
                   WHERE id = %s
                   RETURNING id""",
                (thread_id, thread_id, user_id),
            )
            if cursor.fetchone() is None:
                return False
            # 标题只在创建会话时写一次；后续提问不会改动它。
            cursor.execute(
                "INSERT INTO chat_titles (thread_id, user_id, title) VALUES (%s, %s, %s)",
                (thread_id, user_id, title),
            )
            return True


# 只移除指定用户拥有的一个会话 ID，并清理该会话对应的标题。
def remove_user_thread(user_id: int, thread_id: UUID) -> bool:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            # 在 UPDATE 中同时限定用户和会话归属；不允许凭 UUID 删除其他用户的会话。
            cursor.execute(
                """UPDATE users
                   SET thread_ids = ARRAY_REMOVE(thread_ids, %s::uuid)
                   WHERE id = %s AND thread_ids @> ARRAY[%s::uuid]
                   RETURNING id""",
                (thread_id, user_id, thread_id),
            )
            if cursor.fetchone() is None:
                return False
            # 与上面的 UPDATE 使用同一事务，失败时一起回滚。
            cursor.execute(
                "DELETE FROM chat_titles WHERE user_id = %s AND thread_id = %s",
                (user_id, thread_id),
            )
            return True
