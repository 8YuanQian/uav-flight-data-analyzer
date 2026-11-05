# 只清理测试 worker 挂载的 CSV 暂存文件，不删除卷、目录或其他文件。
import os
from pathlib import Path


def clear_test_uploads():
    if (os.getenv("UAV_DB_NAME") != "uav_project_test"
            or os.getenv("CELERY_BROKER_URL") != "redis://redis:6379/3"):
        raise RuntimeError("当前环境不是测试环境，拒绝清理 CSV")
    directory = Path(os.environ["CSV_UPLOAD_DIR"])
    if directory != Path("/app/upload_spool") or directory.is_symlink():
        raise RuntimeError("测试 CSV 目录不符合预期，拒绝清理")
    resolved = directory.resolve(strict=True)
    paths = list(directory.iterdir())
    # 在删除第一份文件前完成所有路径检查，遇到未知内容立即停止。
    for path in paths:
        if (path.is_symlink() or not path.is_file() or path.suffix != ".csv"
                or path.resolve().parent != resolved):
            raise RuntimeError("测试 CSV 目录包含未知内容，拒绝清理")
    for path in paths:
        path.unlink()
    print(f"已清理 {len(paths)} 份测试 CSV；保留卷和目录。")


if __name__ == "__main__":
    clear_test_uploads()
