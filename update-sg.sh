#!/usr/bin/env bash
# =====================================================================
# HVAC 新加坡服务器 · 本机一键更新（SSH 中转）
#   前提: SSH 已能连通（即宝塔的 SSH 防护已关闭）。
#   用法: bash update-sg.sh   或双击 deploy-hvac-sg.bat
#   逻辑: 打包本地代码 → scp → 仅 server.py 变化才重启后端 → 线上验证
# =====================================================================
set -uo pipefail

SERVER="root@43.156.58.154"
SSH_KEY="$HOME/.ssh/id_ed25519"
REMOTE_DIR="/var/www/hvac"
SITE_HOST="hvac.geopro.cc"

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SSHOPT="-i $SSH_KEY -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15"

echo "[0/4] 预检 SSH 连通..."
if ! ssh $SSHOPT "$SERVER" true 2>/dev/null; then
  echo "  ❌ SSH 连不上 $SERVER。"
  echo "     多半是宝塔的「SSH 防爆破/防护」还开着。请先按文档关闭它，再重试。"
  echo "     （网站本身不受影响，此脚本仅用于代码更新。）"
  exit 1
fi
echo "  ✅ SSH 通"

echo "[1/4] 比对后端指纹..."
OLD=$(ssh $SSHOPT "$SERVER" "md5sum '$REMOTE_DIR/server.py' 2>/dev/null | cut -d' ' -f1")
NEW=$(md5sum "$SRC_DIR/server.py" | cut -d' ' -f1)

echo "[2/4] 打包并上传..."
tar --exclude='./.git' --exclude='./.claude' --exclude='./__pycache__' --exclude='./venv' \
    --exclude='*.pyc' --exclude='./deploy.sh' --exclude='./deploy-sg.sh' \
    --exclude='./update-sg.sh' --exclude='./fix-nginx.sh' \
    -czf /tmp/hvac_sg.tgz -C "$SRC_DIR" .
scp $SSHOPT /tmp/hvac_sg.tgz "$SERVER:/tmp/hvac_sg.tgz"
ssh $SSHOPT "$SERVER" "tar xzf /tmp/hvac_sg.tgz -C '$REMOTE_DIR' && chmod -R a+rX '$REMOTE_DIR'"

echo "[3/4] 生效..."
if [ "$OLD" != "$NEW" ]; then
  echo "  server.py 有变化 → 重启后端并等待就绪"
  ssh $SSHOPT "$SERVER" "
    systemctl restart hvac
    for i in \$(seq 1 20); do curl -sf http://127.0.0.1:8137/api/health >/dev/null 2>&1 && break; sleep 1; done
    echo \"    后端 hvac.service: \$(systemctl is-active hvac)\"
  "
else
  echo "  仅前端更新 → 无需重启（静态文件即时生效，零中断）"
fi

echo "[4/4] 线上验证..."
ssh $SSHOPT "$SERVER" "
  code=\$(curl -s -k --resolve $SITE_HOST:443:127.0.0.1 -o /dev/null -w '%{http_code}' https://$SITE_HOST/index.html)
  echo \"    线上首页 HTTPS: \$code\"
  { [ \"\$code\" = '200' ] && echo '    ✅ 站点正常'; } || echo '    ⚠️  异常, 查看: journalctl -u hvac -n 30'
"
echo "完成 → https://$SITE_HOST"
