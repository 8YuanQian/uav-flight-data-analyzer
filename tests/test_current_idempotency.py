import requests
import getpass
import uuid
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor


BASE_URL = "http://127.0.0.1:8003"


def get_token():

    username = input("请输入用户名：")
    password = getpass.getpass("请输入密码：")

    response = requests.post(
        f"{BASE_URL}/auth/login",
        data={
            "username": username,
            "password": password
        },
        timeout=15
    )

    response.raise_for_status()
    data = response.json()
    # 从登录响应中提取 JWT
    token = data.get("uav_access_token")
    if not token:
        raise RuntimeError(f"登录响应中没有找到 JWT：{data}")

    print("登录成功，已获取 JWT")
    return token

# API 配置
TOKEN = get_token()

CSV_PATH = Path(r"E:\Python\aritificial_intelligence\Pandas\UAV_project_refactored\data\uav_flights_upload_test.csv")

# 两个请求使用同一个幂等键
IDEMPOTENCY_KEY = str(uuid.uuid4())

# 等待两个线程都准备好，再同时放行
barrier = threading.Barrier(2)


def submit_request(index):

    # 等待另一个线程准备完成
    barrier.wait()

    # 每个线程独立打开文件
    with CSV_PATH.open("rb") as f:

        response = requests.post(
            f"{BASE_URL}/ai_flight/flights/report",
            headers={
                "Authorization": f"Bearer {TOKEN}"
            },
            data={
                "idempotency_key": IDEMPOTENCY_KEY
            },
            files={
                "file": (CSV_PATH.name, f, "text/csv")
            },
            timeout=60
        )

    return {
        "request": index,
        "status_code": response.status_code,
        "body": response.json()
    }


if __name__ == "__main__":

    print("开始并发幂等性测试")
    print("幂等键:", IDEMPOTENCY_KEY)

    with ThreadPoolExecutor(max_workers=2) as executor:

        results = list(
            executor.map(submit_request, [1, 2])
        )

    for result in results:
        print(result)