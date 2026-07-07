#!/usr/bin/env bash
# 补装 nginx 并完成 HVAC 站点配置（后端与证书已就绪时使用）
# 宝塔在 dnf 配置里 exclude 了 nginx，用 --disableexcludes=all 绕过
echo "[1] 安装 nginx (OpenCloudOS 默认源, 绕过宝塔 exclude)"
rm -f /etc/yum.repos.d/nginx.repo   # 官方源 nginx 依赖新版 openssl, 与本系统不兼容, 移除
dnf clean all >/dev/null 2>&1
dnf install -y --disableexcludes=all nginx >/tmp/nx.log 2>&1
command -v nginx >/dev/null || dnf install -y --disableexcludes=all --nobest nginx >>/tmp/nx.log 2>&1
command -v nginx >/dev/null && echo "  nginx: $(nginx -v 2>&1)" || { echo "  !! 仍失败:"; tail -8 /tmp/nx.log; exit 1; }

echo "[2] 写 nginx 配置"
mkdir -p /etc/nginx/conf.d
cat > /etc/nginx/conf.d/hvac.conf <<'NGINX'
server { listen 80; server_name hvac.geopro.cc hvac.geotoday.net; return 301 https://$host$request_uri; }
server {
  listen 443 ssl; server_name hvac.geopro.cc;
  ssl_certificate /etc/ssl/hvac/geopro.cer; ssl_certificate_key /etc/ssl/hvac/geopro.key;
  ssl_protocols TLSv1.2 TLSv1.3;
  location / { proxy_pass http://127.0.0.1:8137; proxy_set_header Host $host; proxy_set_header X-Real-IP $remote_addr; proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for; proxy_set_header X-Forwarded-Proto $scheme; }
}
server {
  listen 443 ssl; server_name hvac.geotoday.net;
  ssl_certificate /etc/ssl/hvac/geotoday.cer; ssl_certificate_key /etc/ssl/hvac/geotoday.key;
  ssl_protocols TLSv1.2 TLSv1.3;
  location / { proxy_pass http://127.0.0.1:8137; proxy_set_header Host $host; proxy_set_header X-Real-IP $remote_addr; proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for; proxy_set_header X-Forwarded-Proto $scheme; }
}
NGINX

echo "[3] 启动 nginx"
nginx -t 2>&1 | tail -2
systemctl enable --now nginx 2>/dev/null
systemctl restart nginx && echo "  nginx 启动 OK" || { echo "  !! 启动失败:"; journalctl -u nginx -n 8 --no-pager; }

echo "[4] 本地验证"
for d in hvac.geopro.cc hvac.geotoday.net; do
  curl -s -k --resolve "$d:443:127.0.0.1" -o /dev/null -w "  $d 本地HTTPS: %{http_code}\n" "https://$d/index.html"
done
echo FIXDONE
