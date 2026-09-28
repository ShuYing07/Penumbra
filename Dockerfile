# 疏影·知微 企业版 —— API/Worker 镜像（模块七）
# 桌面版不需要；面向私有化部署的 REST API 服务。
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
# 企业版依赖（API/数据库/队列）
RUN pip install --no-cache-dir -r requirements.txt \
    fastapi uvicorn[standard] psycopg2-binary redis celery

COPY api/ api/
COPY core/ core/
COPY config.yaml.example config.yaml.example

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
