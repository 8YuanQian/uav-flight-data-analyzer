"""保留原有的 uvicorn api:app 启动入口。"""

from app.app import app


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "uav-flight-analyzer",
    }
