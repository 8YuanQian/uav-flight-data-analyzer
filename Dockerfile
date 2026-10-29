FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /uvx /bin/

ENV VIRTUAL_ENV=/opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app
COPY requirements.txt /app/requirements.txt

RUN uv venv /opt/venv \
    && uv pip install --python /opt/venv/bin/python "torch==2.14.1+cpu" --index-url https://download.pytorch.org/whl/cpu \
    && uv pip install --python /opt/venv/bin/python -r /app/requirements.txt

COPY . /app

CMD ["python", "-m", "uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
