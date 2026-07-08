#!/usr/bin/env bash
# =====================================================================
# HVAC 新加坡服务器 · 自动拉取 GitHub 更新
#   由 systemd timer 每分钟触发一次。
#   git pull 检查更新；后端 server.py 变化才 restart；前端变化零中断即时生效。
#   日志: /var/log/hvac-autopull.log
# =====================================================================
set -uo pipefail
LOG=/var/log/hvac-autopull.log
ROOT=/var/www/hvac
cd "$ROOT" || { echo "$(date -Is) [FATAL] $ROOT 不存在" >>$LOG; exit 1; }

OLD_HEAD=$(git rev-parse HEAD 2>/dev/null)
OLD_SRV_MD5=$(md5sum server.py 2>/dev/null | cut -d' ' -f1)

# 只拉主分支;超时 60s 避免网络卡死;不改 config 保持读写 https
git -c core.hooksPath=/dev/null fetch --depth 1 origin main --quiet 2>>$LOG || {
  echo "$(date -Is) [WARN] fetch 失败" >>$LOG; exit 0; }
git reset --hard origin/main --quiet 2>>$LOG || {
  echo "$(date -Is) [WARN] reset 失败" >>$LOG; exit 0; }

NEW_HEAD=$(git rev-parse HEAD)
[ "$OLD_HEAD" = "$NEW_HEAD" ] && exit 0   # 无更新, 静默退出

NEW_SRV_MD5=$(md5sum server.py 2>/dev/null | cut -d' ' -f1)
chmod -R a+rX "$ROOT" 2>/dev/null

if [ "$OLD_SRV_MD5" != "$NEW_SRV_MD5" ]; then
  systemctl restart hvac
  for i in $(seq 1 15); do curl -sf http://127.0.0.1:8137/api/health >/dev/null && break; sleep 1; done
  MSG="server.py 变 → 重启后端 OK"
else
  MSG="仅前端 → 无重启, 即时生效"
fi

CODE=$(curl -s -k --resolve hvac.geopro.cc:443:127.0.0.1 -o /dev/null -w "%{http_code}" https://hvac.geopro.cc/ 2>/dev/null)
echo "$(date -Is) [UPD] $OLD_HEAD -> $NEW_HEAD | $MSG | HTTPS:$CODE" >>$LOG
