# 直接使用已经构建好的hello-world-openclaw作为基础镜像
FROM hello-world-openclaw:latest

# 安装Python环境和必要的依赖，使用--no-install-recommends减少安装体积
RUN apt-get update && \
    apt-get install -y --no-install-recommends python3 python3-pip && \
    pip3 install --no-cache-dir --break-system-packages markdown && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# 复制当前任务文件
COPY . /app

# 设置工作目录
WORKDIR /app
