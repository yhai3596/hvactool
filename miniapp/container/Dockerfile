# 微信云托管 · HVAC CoolProp 计算服务
# 端口三处一致：app.py 默认 80 / 下方 EXPOSE 80 / 控制台 containerPort 80
FROM python:3.11-slim

WORKDIR /app

# 先装依赖再拷代码，利用构建缓存；用腾讯云 PyPI 镜像加速（构建发生在国内）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    -i https://mirrors.cloud.tencent.com/pypi/simple

COPY . .

EXPOSE 80

CMD ["python", "app.py"]
