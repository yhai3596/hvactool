#!/usr/bin/env bash
# 在服务器上一次性安装 autopull(systemd timer 每分钟触发) + 顺带禁用密码登录SSH
# 用法(控制台): curl -fsSL <raw>/install-autopull.sh | sudo bash
set -euo pipefail

ROOT=/var/www/hvac
REPO=https://github.com/yhai3596/hvactool

echo "[1/5] 确保 /var/www/hvac 是 git 仓库(否则重克隆保留原文件)"
if [ ! -d "$ROOT/.git" ]; then
  BAK=/var/www/hvac.bak.$(date +%s); mv "$ROOT" "$BAK"
  git clone --depth 1 "$REPO" "$ROOT"
  # 保留原 venv 与已生效证书(证书本就在 /etc/ssl/hvac 外部)
  [ -d "$BAK/venv" ] && mv "$BAK/venv" "$ROOT/venv"
  echo "  已重克隆并保留 venv, 原目录备份至 $BAK"
else
  cd "$ROOT" && git remote set-url origin "$REPO"
  git fetch --depth 1 origin main --quiet && git reset --hard origin/main --quiet
  echo "  已同步至最新"
fi

echo "[2/5] 安装 autopull 脚本"
install -m 0755 "$ROOT/autopull-sg.sh" /usr/local/bin/hvac-autopull.sh

echo "[3/5] 创建 systemd service + timer(每分钟)"
cat > /etc/systemd/system/hvac-autopull.service <<'UNIT'
[Unit]
Description=HVAC auto-pull from GitHub
After=network.target
[Service]
Type=oneshot
ExecStart=/usr/local/bin/hvac-autopull.sh
UNIT
cat > /etc/systemd/system/hvac-autopull.timer <<'UNIT'
[Unit]
Description=HVAC auto-pull every 1 minute
[Timer]
OnBootSec=30s
OnUnitActiveSec=60s
AccuracySec=15s
Persistent=true
[Install]
WantedBy=timers.target
UNIT
systemctl daemon-reload
systemctl enable --now hvac-autopull.timer
echo "  timer 状态: $(systemctl is-active hvac-autopull.timer)"
echo "  下次触发: $(systemctl show hvac-autopull.timer --value -p NextElapseUSecRealtime)"

echo "[4/5] 立即跑一次 autopull"
/usr/local/bin/hvac-autopull.sh
tail -2 /var/log/hvac-autopull.log 2>/dev/null || echo "  (无变更, 无日志)"

echo "[5/5] 加固 SSH: 禁用密码登录(仅密钥)"
if grep -qE "^\s*PasswordAuthentication\s+yes" /etc/ssh/sshd_config 2>/dev/null; then
  sed -i "s/^\s*PasswordAuthentication\s\+yes/PasswordAuthentication no/" /etc/ssh/sshd_config
elif ! grep -qE "^\s*PasswordAuthentication" /etc/ssh/sshd_config 2>/dev/null; then
  echo "PasswordAuthentication no" >> /etc/ssh/sshd_config
fi
# 移除子目录里可能覆盖的 yes
for f in /etc/ssh/sshd_config.d/*.conf; do
  [ -f "$f" ] || continue
  grep -q "PasswordAuthentication" "$f" && sed -i "s/PasswordAuthentication.*yes/PasswordAuthentication no/" "$f"
done
sshd -t && systemctl reload sshd && echo "  sshd 已禁用密码登录(仅密钥)"

echo "===== 安装完成 ====="
echo "以后你 git push 后, 服务器 1 分钟内自动上线, 日志: tail -f /var/log/hvac-autopull.log"
