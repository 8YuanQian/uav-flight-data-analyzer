# 通过 Node 的内置测试运行器验证页面状态，不安装前端测试依赖。

from pathlib import Path
import shutil
import subprocess

import pytest


def test_csv_upload_page_logic():
    node = shutil.which("node")
    if node is None:
        pytest.skip("页面交互测试需要 Node.js")
    test_file = Path(__file__).with_suffix(".cjs")
    result = subprocess.run(
        [node, "--test", str(test_file)],
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
