# Compose 容器更新与数据迁移报告

完成时间：2026-11-04 23:06:51 +0800。

## 当前入口

- 正式 API：http://127.0.0.1:8002
- 测试 API：http://127.0.0.1:8003
- Compose 项目：`uav-project`
- PostgreSQL 服务：`postgres`；Redis 服务：`redis`
- 正式任务处理：`worker`；测试任务处理：`worker-test`
- 数据库和 Redis 不发布宿主机端口，应用通过服务名访问。

```powershell
docker compose exec postgres psql -U postgres -d uav_project
docker compose exec postgres psql -U postgres -d uav_project_test
```

## 迁移内容及核验

两个数据库均使用 PostgreSQL 自定义归档完整备份、恢复。恢复前后逐表比较行数与规范化行摘要，同时比较表结构、约束、索引、自增序列值和调用状态，全部一致；初始化脚本与 API 启动后再次核对，未新增或丢失业务行。

| 数据 | 正式库 uav_project | 测试库 uav_project_test |
| --- | ---: | ---: |
| 用户 | 3 | 2 |
| 飞行器 | 304 | 2 |
| 飞行记录 | 1009 | 45 |
| 知识文档 | 200 | 0 |
| 会话标题 | 3 | 0 |
| 检查点 | 118 | 0 |
| 检查点数据块 | 180 | 0 |
| 检查点写入 | 418 | 0 |
| 保留的旧文档 | 200 | 0 |

迁移范围还包括全部任务状态、幂等键、用户密码哈希、会话标题及 LangGraph 检查点。旧 `test_documents` 表按原样保留，没有在迁移中合并或清理数据。

Redis 的 /0～/5 全部持久化数据随 AOF/RDB 目录迁移。核对原有键类型、内容摘要和绝对过期时间；未清空任务结果或缓存。正式、测试 CSV 暂存卷分别备份和迁移，不会混用。

## 容器与模型

新镜像：`uav-project-refactored:migrated-20261104`。新 PostgreSQL、Redis 使用 Compose 自建网络和独立命名卷；本机通过可选配置复用 E 盘模型缓存，并使用持久化分词器缓存。`db-init`、`model-init` 正常退出状态均为 0。

修改 `.env` 仅增加/更新 `UAV_APP_IMAGE`，密码、模型密钥和 JWT 签名密钥没有改变；`.env.test` 没有修改。当前日志只写本项目的 `logs`，不向原项目写入。

## 已验证

- 在不发布外部端口时验证新 API 页面、受保护接口拒绝匿名访问、已有用户 JWT 访问、会话列表及数据库读取。
- 正式、测试 worker 均能通过自己的 Redis 逻辑库响应 Celery ping。
- 切换后从宿主机实际访问 8002、8003 的 `/health` 均返回 200。
- 恢复后执行 PostgreSQL `ANALYZE` 更新查询统计。
- 没有调用 DeepSeek，没有上传新的 CSV 测试任务，没有新增用户或飞行记录。

首次迁移尝试因脚本对归档目录的检查过严而在发布前中止，并自动恢复旧服务；修正后先在临时库完整恢复和校验备份，再重新执行迁移并完成切换。临时恢复库已回收。

## 备份与回退边界

备份位于项目 `backups/compose_migration_20261104/`：

- `uav_project.dump`、`uav_project_test.dump`：最终 PostgreSQL 归档。
- `redis_data/`：Redis 持久化文件。
- `csv_uploads/`、`csv_test_uploads/`：两个 CSV 暂存目录。
- `migration.json`：逐表摘要、序列、结构、备份 SHA256 和迁移状态。
- `RECOVERY.md`：阶段含义和回退注意事项。

迁移后停用的旧 PostgreSQL、旧 Redis、旧正式/测试 API 和 worker 共 6 个容器，已按用户要求删除。4 个旧数据卷、旧镜像和全部迁移备份保留。原容器与数据卷的对应关系记录在备份目录 `container_cleanup.json`；恢复旧环境需要重新创建容器并挂载对应旧卷，不能直接启动已删除的容器。新环境已接收后续写入，任何回退都需要先核对新增数据。

本次仅更新重构项目的部署和运行环境，没有同步修改原项目代码。