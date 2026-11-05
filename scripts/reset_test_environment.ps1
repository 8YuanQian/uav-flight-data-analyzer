[CmdletBinding()]
param(
    [switch]$Execute,
    [ValidatePattern('^[a-z0-9][a-z0-9_-]*$')]
    [string]$ProjectName = 'uav-project',
    [switch]$UseLocalCache,
    [ValidateRange(1, 3600)]
    [int]$DrainTimeoutSeconds = 300
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$projectDirectory = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$testComposePath = Join-Path $projectDirectory 'compose.test.yaml'
$mainComposePath = Join-Path $projectDirectory 'compose.yaml'
$composeArguments = @('compose', '--project-name', $ProjectName,
    '-f', $mainComposePath, '-f', $testComposePath)
if ($UseLocalCache) {
    $composeArguments += @('-f', (Join-Path $projectDirectory 'compose.local.yaml'))
    $composeArguments += @('-f', (Join-Path $projectDirectory 'compose.test.local.yaml'))
}
$composeArguments += @('--profile', 'testing')
$testEnvironmentPath = Join-Path $projectDirectory '.env.test'
$testDatabase = 'uav_project_test'
$testRedisDatabases = @(3, 4, 5)
$requiredDataTables = @(
    'chat_titles', 'checkpoint_blobs', 'checkpoint_writes', 'checkpoints',
    'celery_task_states', 'csv_upload_idempotency_keys', 'flight_report_idempotency_keys',
    'documents', 'flight_records',
    'password', 'uavs', 'users'
)
$dataTables = @($requiredDataTables)
# 旧库可能保留这些表；新库不创建它们，只在实际存在时加入手动清理清单。
$optionalLegacyTables = @('test_documents', 'flight_records_legacy', 'flight_analyses')
$expectedTables = @($requiredDataTables + 'checkpoint_migrations' | Sort-Object)

function Invoke-DockerText {
    param([string[]]$DockerArguments)
    $output = & docker @DockerArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Docker 命令失败，退出码：$LASTEXITCODE"
    }
    return $output
}

function Invoke-DockerCommand {
    param([string[]]$DockerArguments)
    & docker @DockerArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Docker 命令失败，退出码：$LASTEXITCODE"
    }
}

function Get-TestDatabaseScalar {
    param([string]$Sql)
    $output = @(Invoke-DockerText -DockerArguments ($composeArguments + @(
        'exec', '-T', 'postgres', 'psql', '-U', 'postgres', '-d', $testDatabase,
        '-X', '-A', '-t', '-v', 'ON_ERROR_STOP=1', '-c', $Sql
    )))
    if ($output.Count -ne 1) {
        throw '测试数据库查询未返回单个结果，已停止清理。'
    }
    return ([string]$output[0]).Trim()
}

function Get-TestDataRowCount {
    # 仅统计明确列出的数据表，保留 LangGraph 的迁移版本表。
    $terms = @($dataTables | ForEach-Object { "(SELECT COUNT(*) FROM public.$_)" })
    return [long](Get-TestDatabaseScalar -Sql ('SELECT ' + ($terms -join ' + ')))
}

function Get-RedisSize {
    param([int]$DatabaseNumber)
    $output = @(Invoke-DockerText -DockerArguments ($composeArguments + @(
        'exec', '-T', 'redis',
        'redis-cli', '-n', [string]$DatabaseNumber, 'DBSIZE'
    )))
    if ($output.Count -ne 1) {
        throw "Redis /$DatabaseNumber 未返回键数量，已停止清理。"
    }
    return [long]([string]$output[0]).Trim()
}

function Assert-TestTargets {
    if (-not (Test-Path -LiteralPath $testComposePath -PathType Leaf) -or
        -not (Test-Path -LiteralPath $mainComposePath -PathType Leaf) -or
        -not (Test-Path -LiteralPath $testEnvironmentPath -PathType Leaf)) {
        throw '测试 Compose 或 .env.test 缺失，已停止清理。'
    }

    # 解析 Compose 的最终配置，防止环境变量或配置修改后误清日常环境。
    $configJson = @(Invoke-DockerText -DockerArguments (
        $composeArguments + @('config', '--format', 'json')
    )) -join "`n"
    $config = ConvertFrom-Json -InputObject $configJson
    $serviceNames = @($config.services.PSObject.Properties.Name)
    if ($config.name -ne $ProjectName -or
        @('postgres', 'redis', 'api', 'worker', 'api-test', 'worker-test' | Where-Object {
            $_ -notin $serviceNames
        }).Count -ne 0 -or
        'csv_test_uploads' -notin @($config.volumes.PSObject.Properties.Name)) {
        throw '测试 Compose 的项目、服务或卷已变化，已停止清理。'
    }

    foreach ($serviceName in @('api-test', 'worker-test')) {
        $service = $config.services.$serviceName
        $environment = $service.environment
        if ($environment.UAV_DB_NAME -ne $testDatabase -or
            $environment.UAV_DB_HOST -ne 'postgres' -or
            [string]$environment.UAV_DB_PORT -ne '5432' -or
            $environment.CELERY_BROKER_URL -ne 'redis://redis:6379/3' -or
            $environment.CELERY_RESULT_BACKEND -ne 'redis://redis:6379/4' -or
            $environment.REDIS_CACHE_URL -ne 'redis://redis:6379/5') {
            throw "$serviceName 的数据库或 Redis 目标不是预期的测试配置，已停止清理。"
        }
        $spoolMount = @($service.volumes | Where-Object { $_.target -eq '/app/upload_spool' })
        if ($spoolMount.Count -ne 1 -or
            $spoolMount[0].type -ne 'volume' -or
            $spoolMount[0].source -ne 'csv_test_uploads') {
            throw "$serviceName 的 CSV 暂存卷不是预期的测试卷，已停止清理。"
        }
    }

    # 正式服务不能挂载测试暂存卷，也不能指向测试库或测试 Redis。
    foreach ($serviceName in @('api', 'worker')) {
        $service = $config.services.$serviceName
        if ($service.environment.UAV_DB_NAME -ne 'uav_project' -or
            $service.environment.CELERY_BROKER_URL -ne 'redis://redis:6379/0' -or
            $service.environment.CELERY_RESULT_BACKEND -ne 'redis://redis:6379/1' -or
            $service.environment.REDIS_CACHE_URL -ne 'redis://redis:6379/2' -or
            @($service.volumes | Where-Object { $_.source -eq 'csv_test_uploads' }).Count -ne 0) {
            throw '正式环境与测试环境未正确隔离，已停止清理。'
        }
    }

    $port = @($config.services.'api-test'.ports)
    $workerHasPorts = @($config.services.'worker-test'.PSObject.Properties.Name) -contains 'ports'
    if ($port.Count -ne 1 -or
        [string]$port[0].host_ip -ne '127.0.0.1' -or
        [int]$port[0].published -lt 1 -or [int]$port[0].published -gt 65535 -or
        [string]$port[0].target -ne '8000' -or
        $workerHasPorts) {
        throw '测试服务端口已变化，已停止清理。'
    }
    $script:testHealthUrl = 'http://127.0.0.1:' + $port[0].published + '/health'

    $testEnvironmentFile = Get-Item -LiteralPath $testEnvironmentPath
    if (($testEnvironmentFile.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw '.env.test 是重解析点，已停止清理。'
    }
    $environmentText = [IO.File]::ReadAllText($testEnvironmentPath)
    if ([regex]::Matches($environmentText, '(?m)^JWT_SECRET_KEY=[^\r\n]*').Count -ne 1 -or
        [string]::IsNullOrWhiteSpace([string]$config.services.'api-test'.environment.JWT_SECRET_KEY) -or
        $config.services.'api-test'.environment.JWT_SECRET_KEY -ne
        $config.services.'worker-test'.environment.JWT_SECRET_KEY -or
        $config.services.'api-test'.environment.JWT_SECRET_KEY -eq
        $config.services.api.environment.JWT_SECRET_KEY) {
        throw '测试 JWT 配置不完整，已停止清理。'
    }

    if ((Get-TestDatabaseScalar -Sql 'SELECT current_database()') -ne $testDatabase) {
        throw '当前数据库不是 uav_project_test，已停止清理。'
    }
    $actualTables = @(Invoke-DockerText -DockerArguments ($composeArguments + @(
        'exec', '-T', 'postgres', 'psql', '-U', 'postgres', '-d', $testDatabase,
        '-X', '-A', '-t', '-v', 'ON_ERROR_STOP=1', '-c',
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
    )))
    $actualRequired = @($actualTables | Where-Object { $_ -notin $optionalLegacyTables })
    if (@(Compare-Object -ReferenceObject $expectedTables -DifferenceObject $actualRequired).Count -ne 0) {
        throw '测试库表结构已变化，必须先更新清理表清单。'
    }
    $script:dataTables = @($requiredDataTables + @($actualTables | Where-Object {
        $_ -in $optionalLegacyTables
    }) | Sort-Object -Unique)

    $migrationCount = [long](Get-TestDatabaseScalar -Sql 'SELECT COUNT(*) FROM public.checkpoint_migrations')
    if ($migrationCount -le 0) {
        throw 'LangGraph 迁移记录为空，已停止清理。'
    }
    foreach ($databaseNumber in $testRedisDatabases) {
        [void](Get-RedisSize -DatabaseNumber $databaseNumber)
    }
    return $migrationCount
}

function Get-RunningTestServices {
    return @(Invoke-DockerText -DockerArguments (
        $composeArguments + @('ps', '--status', 'running', '--services')
    ))
}

function Wait-ForActiveTestTasks {
    if ((Get-RunningTestServices) -notcontains 'worker-test') {
        return
    }
    $stopwatch = [Diagnostics.Stopwatch]::StartNew()
    $inspectCode = 'from app.app import celery_app; tasks = celery_app.control.inspect(timeout=5).active(); print(-1 if tasks is None else sum(len(items) for items in tasks.values()))'
    while ($true) {
        $output = @(Invoke-DockerText -DockerArguments ($composeArguments + @(
            'exec', '-T', 'worker-test',
            'python', '-c', $inspectCode
        )))
        $activeCount = [int]([string]($output | Select-Object -Last 1)).Trim()
        if ($activeCount -lt 0) {
            throw '无法确认测试 worker 的任务状态；测试 API 已停止，未清理数据。'
        }
        if ($activeCount -eq 0) {
            return
        }
        if ($stopwatch.Elapsed.TotalSeconds -ge $DrainTimeoutSeconds) {
            throw "仍有 $activeCount 个测试任务在运行；测试 API 已停止，未清理数据。"
        }
        Write-Host "等待 $activeCount 个测试任务完成……"
        Start-Sleep -Seconds 5
    }
}

function Rotate-TestJwtSecret {
    # 清理测试用户后使旧令牌失效；不输出或备份密钥内容。
    $secretBytes = New-Object byte[] 32
    $generator = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $generator.GetBytes($secretBytes)
    } finally {
        $generator.Dispose()
    }
    $secret = [BitConverter]::ToString($secretBytes).Replace('-', '').ToLowerInvariant()
    $currentText = [IO.File]::ReadAllText($testEnvironmentPath)
    $newText = [regex]::Replace(
        $currentText, '(?m)^JWT_SECRET_KEY=[^\r\n]*', 'JWT_SECRET_KEY=' + $secret
    )
    [IO.File]::WriteAllText($testEnvironmentPath, $newText, (New-Object Text.UTF8Encoding($false)))
}

try {
    $migrationCountBefore = Assert-TestTargets
    $rowCountBefore = Get-TestDataRowCount
    Write-Host "目标数据库：$testDatabase；待清理数据行数：$rowCountBefore"
    foreach ($databaseNumber in $testRedisDatabases) {
        Write-Host "Redis /$databaseNumber 当前键数：$(Get-RedisSize -DatabaseNumber $databaseNumber)"
    }
    Write-Host '将清理测试库的数据表、Redis /3～/5 和测试 CSV 暂存卷；保留表结构、迁移记录和日志。'
    if (-not $Execute) {
        Write-Host '仅预览，未修改任何数据。需要清理时手动加 -Execute。'
        return
    }

    # 先阻止新请求，再等待已执行的任务结束；队列里的未执行任务随后会被清空。
    Invoke-DockerCommand -DockerArguments ($composeArguments + @('stop', '-t', '60', 'api-test'))
    Wait-ForActiveTestTasks
    Invoke-DockerCommand -DockerArguments ($composeArguments + @('stop', '-t', '60', 'worker-test'))

    # 一条 TRUNCATE 语句覆盖所有关联表；任何约束错误都会使事务整体回滚。
    $resetSql = @'
BEGIN;
DO $$
BEGIN
    IF current_database() <> 'uav_project_test' THEN
        RAISE EXCEPTION 'Refusing to reset a non-test database';
    END IF;
END
$$;
TRUNCATE TABLE
__DATA_TABLES__
CONTINUE IDENTITY RESTRICT;
COMMIT;
'@
    # 表名只来自上面的固定白名单，不能由请求或环境变量提供。
    $truncateTargets = @($dataTables | ForEach-Object { "    public.$_" }) -join (',' + [Environment]::NewLine)
    $resetSql = $resetSql.Replace('__DATA_TABLES__', $truncateTargets)
    Invoke-DockerCommand -DockerArguments ($composeArguments + @(
        'exec', '-T', 'postgres', 'psql', '-U', 'postgres', '-d', $testDatabase,
        '-X', '-v', 'ON_ERROR_STOP=1', '-c', $resetSql
    ))
    if ((Get-TestDataRowCount) -ne 0 -or
        [long](Get-TestDatabaseScalar -Sql 'SELECT COUNT(*) FROM public.checkpoint_migrations') -ne $migrationCountBefore) {
        throw '测试库清理后核验失败；测试服务保持停止，请检查数据。'
    }

    foreach ($databaseNumber in $testRedisDatabases) {
        Invoke-DockerCommand -DockerArguments ($composeArguments + @(
            'exec', '-T', 'redis',
            'redis-cli', '-n', [string]$databaseNumber, 'FLUSHDB', 'SYNC'
        ))
        if ((Get-RedisSize -DatabaseNumber $databaseNumber) -ne 0) {
            throw "Redis /$databaseNumber 清理后仍有键；测试服务保持停止。"
        }
    }

    # 只挂载并清理测试暂存卷；不执行 down，也不删除任何数据库或 Redis 卷。
    Invoke-DockerCommand -DockerArguments ($composeArguments + @(
        'run', '--rm', '--no-deps', 'worker-test', 'python', 'scripts/clear_test_uploads.py'
    ))
    Rotate-TestJwtSecret
    Invoke-DockerCommand -DockerArguments ($composeArguments + @('up', '-d', '--no-deps', '--force-recreate', 'api-test', 'worker-test'))

    $healthy = $false
    for ($attempt = 0; $attempt -lt 90; $attempt++) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $testHealthUrl -TimeoutSec 3
            if ([int]$response.StatusCode -eq 200) {
                $healthy = $true
                break
            }
        } catch {
            # 应用加载模型期间端口可能暂时不可用，继续等待。
        }
        Start-Sleep -Seconds 2
    }
    if (-not $healthy -or (Get-RunningTestServices) -notcontains 'worker-test') {
        throw '数据已清理，但测试服务尚未全部就绪；请检查测试容器日志。'
    }
    Write-Host "测试环境清理完成。$testHealthUrl 已就绪，请重新注册测试用户并登录。"
} catch {
    [Console]::Error.WriteLine('清理未完成：' + $_.Exception.Message)
    exit 1
}
