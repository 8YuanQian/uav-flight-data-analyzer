"""保留原数据库模块的接口，同时支持新增的 repository 子模块。"""

import sys as _sys
from importlib.machinery import SourceFileLoader as _SourceFileLoader
from pathlib import Path as _Path


# 原项目已有 src/database.py。加载原文件到此包的命名空间，保持
# get_connection、配置变量及分析记录函数的行为，不复制或改写连接逻辑。
_legacy_path = _Path(__file__).resolve().parent.parent / "database.py"
_SourceFileLoader(__name__, str(_legacy_path)).exec_module(_sys.modules[__name__])

del _legacy_path, _SourceFileLoader, _Path, _sys
