# Compose 部署与维护

## 本机当前运行状态（2026-11-04）

正式库、测试库、Redis 和两个 CSV 暂存卷已迁入 `uav-project` 项目。正式接口仍是 8002，测试接口仍是 8003。新镜像为 `uav-project-refactored:migrated-20261104`，已通过 `.env` 中的 `UAV_APP_IMAGE` 固定；密码、API 密钥和 JWT 密钥保持原值。

本机复用 E 盘模型缓存，后续更新使用：

```powershell
docker compose -f compose.yaml -f compose.test.yaml -f compose.local.yaml -f compose.test.local.yaml up -d --build api worker api-test worker-test
# 手动清理测试环境时必须沿用本机缓存配置
.\scripts\reset_test_environment.ps1 -UseLocalCache -Execute
```

备份和逐表校验结果见 [本次迁移报告](compose_migration_20261104.md)。迁移后停用的 6 个旧容器已删除，旧数据卷和备份保留，当前不再使用 `uav-postgres` 作为数据库入口。

## 新机器部署

需要 Docker Compose 2.24.4 或更新版本，测试配置使用的 `!override` 从该版本开始支持，见 [Docker 合并规则](https://docs.docker.com/reference/compose-file/merge/)。默认配置自行创建 PostgreSQL、Redis、网络和持久卷，不依赖旧容器、预建网络或 E 盘目录。首次构建镜像和准备模型需要网络；缓存完整后 API 和 worker 使用离线模型。

在项目根目录复制 `.env.example` 为 `.env`，填写数据库密码、DeepSeek 密钥和至少 32 字符的随机 JWT 密钥；不要覆盖已有文件。

```powershell
docker compose up -d --build api worker
docker compose logs -f db-init model-init api worker
```

访问 `http://127.0.0.1:8002/login`。`db-init` 自动创建 `uav_project`、`uav_project_test` 并执行同一套 SQL；`model-init` 准备两个检索模型及 `o200k_base` 分词器。两个初始化容器成功退出后才启动 API 和 worker。LangGraph 检查点表仍由 API 的 `setup()` 创建。

新项目名为 `uav-project`，区别于本机旧项目 `uav_project_refactored`，不会自动接入旧数据卷。如果旧 API 已占用 8002/8003，可在 `.env` 设置 `UAV_API_PORT`、`UAV_TEST_API_PORT` 使用其他端口进行验证。

## 测试环境

复制 `.env.test.example` 为 `.env.test`，填写与正式环境不同的 JWT 密钥：

```powershell
docker compose -f compose.yaml -f compose.test.yaml up -d api-test worker-test
```

测试入口为 `http://127.0.0.1:8003`。同一 PostgreSQL 容器中的正式、测试库分别是 `uav_project`、`uav_project_test`；Redis 分别使用 /0～/2 和 /3～/5。JWT、CSV 暂存卷和日志目录分别隔离。`compose.test.yaml` 是补充配置，不能再单独使用。

## 本机模型缓存（可选）

只有本机存在 `E:/CodexEnv/cache/huggingface-docker` 时，才添加可选配置。新机器直接使用默认命名卷。

```powershell
docker compose -f compose.yaml -f compose.local.yaml up -d --build api worker
docker compose -f compose.yaml -f compose.test.yaml -f compose.local.yaml -f compose.test.local.yaml up -d api-test worker-test
```

初始化、API、worker 必须使用同一种缓存配置，维护时也沿用同一组 `-f` 参数。

## 数据库与日志

数据库默认不发布宿主机端口，通过 Compose 服务名访问：

```powershell
docker compose exec postgres psql -U postgres -d uav_project
docker compose exec postgres psql -U postgres -d uav_project_test
# 手动重复迁移前，先备份并完成旧任务
docker compose run --rm db-init
```

正式日志位于当前项目 `./logs`，测试日志位于 `./logs/test-api`、`./logs/test-worker`。INFO 级别，按北京时间每天分别写 `fastapi-日期.log`、`worker-日期.log`。原项目与重构项目只写各自目录，不再保存跨项目日志副本。

## 手动清理测试数据

```powershell
.\scripts\reset_test_environment.ps1
.\scripts\reset_test_environment.ps1 -Execute
# 部署时使用了本机缓存配置，清理时也要指定
.\scripts\reset_test_environment.ps1 -UseLocalCache -Execute
```

只有 `-Execute` 才修改数据。脚本检查实际配置和库名，停止测试 API，等待当前测试任务结束后停止测试 worker。随后仅清空测试表数据、Redis /3～/5 和测试 CSV，保留表结构、检查点迁移记录、日志和全部数据卷。测试 JWT 会轮换，最后只重建测试服务。不重置自增序列。

脚本不执行 `down --volumes`，不停止正式服务，不清理正式库。检查或执行失败会报错停止；自定义项目名可用 `-ProjectName 实际项目名`。

## 当前机器的旧部署

本次迁移已完成，迁移后停用的旧容器已删除。`compose.existing.yaml`、`compose.existing-test.yaml` 仅保留为旧环境记录和回退参考，不再用于日常启动；下列命令不是当前环境的更新命令：

```powershell
docker compose -f compose.existing.yaml up -d --build api worker
docker compose -f compose.existing-test.yaml up -d api worker
```

旧数据库、Redis 和 CSV 已完成迁移并核对，旧容器已删除，源卷和迁移备份保留，卷与原容器对应关系见 `backups/compose_migration_20261104/container_cleanup.json`。新环境接收后续写入后，不能直接开启旧 API 回退，否则会继续使用过期的数据；需要先核对并处理迁移后的新增数据。不要删除源卷或迁移备份。
