# 多阶段构建：构建阶段
FROM python:3.11-alpine AS builder

WORKDIR /app

# 安装构建依赖
RUN apk add --no-cache gcc musl-dev

# 复制依赖文件
COPY requirements.txt .

# 安装 Python 依赖
RUN pip install --no-cache-dir --user -r requirements.txt

# 运行阶段
FROM python:3.11-alpine

WORKDIR /app

# 从构建阶段复制已安装的包
COPY --from=builder /root/.local /root/.local

# 复制应用代码
COPY . .

# 确保 PATH 包含用户本地 bin 目录
ENV PATH=/root/.local/bin:$PATH

# 创建数据目录（用于 SQLite）
RUN mkdir -p /data

# 暴露端口
EXPOSE 5000

# 设置时区为东八区
ENV TZ=Asia/Shanghai

# 启动命令
CMD ["gunicorn", "-w", "1", "-b", "0.0.0.0:5000", "--timeout", "120", "app:app"]
