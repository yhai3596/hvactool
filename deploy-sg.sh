#!/usr/bin/env bash
# =====================================================================
# HVAC 新加坡服务器一键部署（OpenCloudOS 9 / RHEL9 系）
#   在服务器控制台执行；证书用 GoDaddy DNS-01 直接在本机签发+自动续期。
#   用法:  curl -fsSL <raw>/deploy-sg.sh | sudo GD_Key=xxx GD_Secret=yyy bash
# =====================================================================
GD_Key="${GD_Key:?需要 GD_Key 环境变量}"
GD_Secret="${GD_Secret:?需要 GD_Secret 环境变量}"
export GD_Key GD_Secret
DOMAINS="hvac.geopro.cc hvac.geotoday.net"
REPO="https://github.com/yhai3596/hvactool"
ROOT=/var/www/hvac

echo "===== HVAC 新加坡部署开始 ====="

echo "[1/8] 安装依赖 (python/pip/git/nginx)..."
dnf install -y -q python3-pip python3-devel gcc git curl tar >/dev/null 2>&1
dnf install -y nginx >/tmp/nginx-install.log 2>&1
if ! command -v nginx >/dev/null; then
  echo "  默认源无 nginx, 改用 nginx 官方 el9 源..."
  cat > /etc/yum.repos.d/nginx.repo <<'EOF'
[nginx-stable]
name=nginx stable
baseurl=http://nginx.org/packages/centos/9/$basearch/
gpgcheck=0
enabled=1
EOF
  dnf install -y nginx >>/tmp/nginx-install.log 2>&1
fi
command -v nginx >/dev/null && echo "  nginx: $(nginx -v 2>&1)" || { echo "  !! nginx 仍失败:"; tail -3 /tmp/nginx-install.log; }

echo "[2/8] 拉取站点代码..."
rm -rf "$ROOT"; mkdir -p /var/www
git clone --depth 1 "$REPO" "$ROOT" 2>&1 | tail -1
echo "  页面数: $(ls "$ROOT"/*.html 2>/dev/null | wc -l)"

echo "[3/8] Python 虚拟环境 + CoolProp (需下载, 稍候)..."
python3 -m venv "$ROOT/venv"
"$ROOT/venv/bin/pip" install -q --upgrade pip >/dev/null 2>&1
"$ROOT/venv/bin/pip" install -q CoolProp >/dev/null 2>&1
"$ROOT/venv/bin/python" -c "import CoolProp,CoolProp.CoolProp as C; print('  CoolProp', CoolProp.__version__, 'R410A Tcrit', round(C.PropsSI('TCRIT','R410A'),1))" || echo "  !! CoolProp 安装异常"

echo "[4/8] 配置后端 systemd 服务..."
chmod -R a+rX "$ROOT"
cat > /etc/systemd/system/hvac.service <<UNIT
[Unit]
Description=HVAC Tool Station (CoolProp API + static)
After=network.target
[Service]
Type=simple
WorkingDirectory=$ROOT
ExecStart=$ROOT/venv/bin/python $ROOT/server.py
Restart=on-failure
RestartSec=3
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now hvac >/dev/null 2>&1
for i in $(seq 1 15); do curl -sf http://127.0.0.1:8137/api/health >/dev/null 2>&1 && break; sleep 1; done
curl -sf http://127.0.0.1:8137/api/health >/dev/null 2>&1 && echo "  后端 8137: OK" || echo "  !! 后端未就绪"

echo "[5/8] SELinux 放行 (反代/绑定)..."
setsebool -P httpd_can_network_connect 1 2>/dev/null && echo "  已允许 httpd 反代" || { setenforce 0 2>/dev/null; echo "  SELinux 置为 permissive"; }

echo "[6/8] 签发 Let's Encrypt 证书 (GoDaddy DNS-01)..."
curl -s https://get.acme.sh | sh -s email=yhai3596@outlook.com >/dev/null 2>&1
ACME=~/.acme.sh/acme.sh
$ACME --set-default-ca --server letsencrypt >/dev/null 2>&1
mkdir -p /etc/ssl/hvac
for d in $DOMAINS; do
  pfx=$(echo "$d" | cut -d. -f2)
  echo "  签发 $d ..."
  $ACME --issue --dns dns_gd -d "$d" --server letsencrypt --dnssleep 25 >/dev/null 2>&1
  $ACME --install-cert -d "$d" --ecc \
     --fullchain-file "/etc/ssl/hvac/$pfx.cer" \
     --key-file "/etc/ssl/hvac/$pfx.key" \
     --reloadcmd "nginx -s reload" >/dev/null 2>&1
  [ -s "/etc/ssl/hvac/$pfx.cer" ] && echo "    证书 $pfx.cer OK" || echo "    !! $d 证书签发失败"
done

echo "[7/8] 配置 nginx..."
cat > /etc/nginx/conf.d/hvac.conf <<'NGINX'
server { listen 80; listen [::]:80; server_name hvac.geopro.cc hvac.geotoday.net; return 301 https://$host$request_uri; }
server {
  listen 443 ssl http2; listen [::]:443 ssl http2; server_name hvac.geopro.cc;
  ssl_certificate /etc/ssl/hvac/geopro.cer; ssl_certificate_key /etc/ssl/hvac/geopro.key;
  ssl_protocols TLSv1.2 TLSv1.3;
  location / { proxy_pass http://127.0.0.1:8137; proxy_set_header Host $host; proxy_set_header X-Real-IP $remote_addr; proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for; proxy_set_header X-Forwarded-Proto $scheme; }
}
server {
  listen 443 ssl http2; listen [::]:443 ssl http2; server_name hvac.geotoday.net;
  ssl_certificate /etc/ssl/hvac/geotoday.cer; ssl_certificate_key /etc/ssl/hvac/geotoday.key;
  ssl_protocols TLSv1.2 TLSv1.3;
  location / { proxy_pass http://127.0.0.1:8137; proxy_set_header Host $host; proxy_set_header X-Real-IP $remote_addr; proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for; proxy_set_header X-Forwarded-Proto $scheme; }
}
NGINX
# 删除可能占用的默认站
rm -f /etc/nginx/conf.d/default.conf 2>/dev/null
sed -i '/# HVAC-managed/,$d' /etc/nginx/nginx.conf 2>/dev/null
nginx -t 2>&1 | tail -2
systemctl enable nginx >/dev/null 2>&1
systemctl restart nginx && echo "  nginx 已启动" || echo "  !! nginx 启动失败"

echo "[8/8] 本地验证..."
for d in $DOMAINS; do
  code=$(curl -s -k --resolve "$d:443:127.0.0.1" -o /dev/null -w "%{http_code}" "https://$d/index.html")
  echo "  $d 本地HTTPS: $code"
done
echo "===== 部署结束，请把以上全部输出贴回 ====="
