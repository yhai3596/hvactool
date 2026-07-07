#!/usr/bin/env bash
# =====================================================================
# HVAC 生产部署脚本
#   把本目录同步到生产服务器；仅当后端 server.py 变化时才重启服务
#   （前端 HTML/CSS/JS 为静态实时托管，改动即时生效、零中断）。
#   用法:  bash deploy.sh        (需本机已配 SSH 私钥、能免密登录服务器)
#   Windows 可双击 deploy-hvac.bat 调用本脚本。
#
#   说明: 服务器出境网络受限、无法自行 git pull，故由本机中转部署。
# =====================================================================
set -euo pipefail

# ==== 可配置项 ====
SERVER="root@119.29.105.107"
SSH_KEY="$HOME/.ssh/id_ed25519"
REMOTE_DIR="/var/www/hvac"
SITE_HOST="hvac.geopro.cc"
# ==================

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SSHOPT="-i $SSH_KEY -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=accept-new"

echo "[1/4] 比对后端指纹 ..."
OLD_MD5=$(ssh $SSHOPT "$SERVER" "md5sum '$REMOTE_DIR/server.py' 2>/dev/null | cut -d' ' -f1" || echo "")
NEW_MD5=$(md5sum "$SRC_DIR/server.py" | cut -d' ' -f1)

echo "[2/4] 打包并上传 ..."
tar --exclude='./.git' --exclude='./.claude' --exclude='./__pycache__' \
    --exclude='./venv' --exclude='*.pyc' --exclude='./deploy.sh' \
    -czf /tmp/hvac_deploy.tgz -C "$SRC_DIR" .
scp $SSHOPT /tmp/hvac_deploy.tgz "$SERVER:/tmp/hvac_deploy.tgz"
ssh $SSHOPT "$SERVER" "tar xzf /tmp/hvac_deploy.tgz -C '$REMOTE_DIR' && chown -R www-data:www-data '$REMOTE_DIR'"

echo "[3/4] 生效 ..."
if [ "$OLD_MD5" != "$NEW_MD5" ]; then
  echo "  server.py 有变化 → 重启后端并等待就绪"
  ssh $SSHOPT "$SERVER" "
    systemctl restart hvac
    for i in \$(seq 1 20); do curl -sf http://127.0.0.1:8137/api/health >/dev/null 2>&1 && break; sleep 1; done
    echo \"  后端 hvac.service: \$(systemctl is-active hvac)\"
  "
else
  echo "  仅前端更新 → 无需重启（静态文件即时生效，零中断）"
fi

echo "[4/4] 线上验证 ..."
ssh $SSHOPT "$SERVER" "
  code=\$(curl -s -k --resolve $SITE_HOST:443:127.0.0.1 -o /dev/null -w '%{http_code}' https://$SITE_HOST/index.html)
  echo \"  线上首页 HTTPS: \$code\"
  { [ \"\$code\" = '200' ] && echo '  ✅ 站点正常 → https://$SITE_HOST'; } || { echo '  ⚠️  异常, 查看: journalctl -u hvac -n 30'; exit 1; }
"
