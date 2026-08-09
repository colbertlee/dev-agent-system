# Dockerfile — 多 Agent 系统 Linux 容器化部署
FROM python:3.11-slim

WORKDIR /app

# 先复制依赖并安装，以利用缓存层
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目代码
COPY . .

# 创建工作目录与记忆目录
RUN mkdir -p workspace memory_store backups chroma_data

# 暴露统一 A2A 网关端口
EXPOSE 8000

# 默认启动统一网关
CMD ["python", "-m", "dev_agent_system.server", "--host", "0.0.0.0", "--port", "8000"]
