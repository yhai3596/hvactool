# HVAC 工具站 · 生产部署复盘与运维手册

> 记录 2026-07-07 ~ 07-08 从国内服务器迁移至新加坡服务器的完整过程、遇到的全部问题及解决方案。
> 这些是踩坑换来的经验资产,请勿删除。运维前请先读[附录 A · QA](#附录-a--qa常见问题) 和 [附录 C · 排查决策树](#附录-c--排查决策树)。

---

## 一、最终生产架构（TL;DR）

```
                       用户浏览器 (HTTPS)
                              │
        hvac.geopro.cc / hvac.geotoday.net   (GoDaddy DNS, A 记录)
                              │  :443  Let's Encrypt (ECC, 90天)
                              ▼
   ┌───────────────────────────────────────────────────┐
   │  腾讯云新加坡 CVM  43.156.58.154                    │
   │  OpenCloudOS 9.6 (RHEL9 系, dnf)                    │
   │                                                     │
   │  nginx 1.26.3  ── 80→301跳转 / 443 ssl 反向代理     │
   │                        │                            │
   │  systemd: hvac.service (root)                       │
   │     /var/www/hvac/venv/bin/python server.py         │
   │     监听 127.0.0.1:8137  (CoolProp 8.0.0)           │
   │                                                     │
   │  systemd timer: hvac-autopull.timer (每分钟)        │
   │     git pull → 变化则生效  (自动更新)               │
   │  acme.sh (cron) → 证书自动续期                      │
   └───────────────────────────────────────────────────┘
```

| 维度 | 方案 |
|------|------|
| 服务器 | 腾讯云**新加坡** `43.156.58.154`,OpenCloudOS 9.6 |
| 为何境外 | 国内服务器 **未 ICP 备案**,80/443 被腾讯云网络层拦截 |
| 域名/DNS | GoDaddy 托管,`hvac.geopro.cc`/`hvac.geotoday.net` A 记录 → 43.156.58.154 |
| 后端 | `server.py`（stdlib http.server + CoolProp API）由 systemd 以 root 跑,监听 127.0.0.1:8137 |
| Web | nginx 反向代理,两域名各一 server 块 + 各自证书 |
| 证书 | Let's Encrypt,**服务器本地 acme.sh + GoDaddy DNS-01 自签自续** |
| 代码更新 | **服务器每分钟自动 `git pull`**（因 SSH 被网络层封锁,不能用 SSH 中转） |
| 仓库 | GitHub `yhai3596/hvactool`,**须保持 public**（服务器匿名 pull） |

### 三条最重要的教训

1. **国内服务器跑网站必须 ICP 备案**,否则 80/443 被拦;不想备案就用境外服务器 + 境外域名。
2. **腾讯云主机自带云镜(YunJing) + 若装了宝塔(BT-Panel),两者都会用用户态 RST 掉"陌生 IP"的 SSH**,且都有自愈/防删机制。自用机建议直接卸载。
3. **`pkill -9 -f "字符串"` 是大坑**:`-f` 匹配整条命令行,若你正在执行的命令里含该字符串,会把自己杀掉(终端显示 `Killed`,后续命令全不执行)。永远用 `pkill -x 进程名` 或 `ps -eo pid,comm | awk` 按进程名匹配。

---

## 二、问题复盘（按主题）

### 2.1 ICP 备案 —— 迁移的起因

**现象**:国内服务器(腾讯云大陆 `119.29.105.107`)上网站突然打不开。

**诊断**:SSH 登录服务器,`systemctl is-active hvac nginx` 均 active,本地 `curl -k --resolve ...:127.0.0.1` 返回 **200** —— 服务完全正常,是**外网访问被拦**。

**根因**:大陆服务器运行 Web 服务需 ICP 备案,未备案时腾讯云在**网络层**拦截 80/443 入站。这与服务器内部无关,改什么配置都没用。

**解决**:迁移到**境外服务器(新加坡)**。境外主机 + 境外域名(geopro.cc/geotoday.net)不需要 ICP 备案。

---

### 2.2 域名与 DNS（GoDaddy）

**关键发现**:
- `geopro.cc` / `geotoday.net` 的 NS 记录**混用**:既有 Cloudflare(`ezra/tara.ns.cloudflare.com`)又有 GoDaddy(`ns53/54.domaincontrol.com`)。**实际生效的是 GoDaddy**(SOA 主 NS 是 `ns53.domaincontrol.com`,DNS 面板也是 GoDaddy)。Cloudflare 那两条是历史残留,**不能用 Cloudflare 橙云代理**(域名没真正托管在 CF)。
- 根域名 `geopro.cc` → Vercel(76.76.21.21),`geotoday.net` → AWS。**根域名不能动**(会搞挂现有站),所以用**子域名 `hvac.*`**。

**用 GoDaddy API 自动改 A 记录**(无需登面板):
```bash
curl -X PUT -H "Authorization: sso-key {KEY}:{SECRET}" -H "Content-Type: application/json" \
  "https://api.godaddy.com/v1/domains/geopro.cc/records/A/hvac" \
  -d '[{"data":"43.156.58.154","ttl":600}]'
```
> GoDaddy Production API Key 需账户满足条件(有域名即可,本例 geopro.cc/geotoday.net 都 ACTIVE)。生成:https://developer.godaddy.com/keys → Create New API Key → **Production**。

**坑**:本机 DNS 走代理(fake-ip 198.18 段),本地查解析不准。**用 DoH 查真实公网记录**:
```bash
curl -s "https://dns.google/resolve?name=hvac.geopro.cc&type=A"
```
DNS 改后有 TTL 缓存(本例 600s),等几分钟传播。

---

### 2.3 服务器接入（SSH 密钥）

**问题 1 · 主机密钥变更**:连接报 `REMOTE HOST IDENTIFICATION HAS CHANGED`。
- **根因**:服务器重装,SSH 主机密钥变了。
- **解决**:`ssh-keygen -R <IP>` 清旧记录,连接后核对服务器身份确认非 MITM。

**问题 2 · 公钥认证被拒**:重装后 `Permission denied (publickey)`。
- **根因**:重装清空了 `~/.ssh/authorized_keys`。
- **解决**:在**云厂商控制台网页终端**(走内网,不受 SSH 拦截影响)注入公钥:
  ```bash
  mkdir -p ~/.ssh && chmod 700 ~/.ssh && echo '<你的公钥>' >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys
  ```

**问题 3 · SSH 别名配置陷阱**:`~/.ssh/config` 里 `n8n` 别名写了 `IdentitiesOnly yes` + `IdentityFile n8n.pem`(旧钥),即使注入了新公钥,用别名连也只会拿旧钥 → 认证失败。
- **解决**:显式指定新私钥并隔离:`ssh -i ~/.ssh/id_ed25519 -o IdentitiesOnly=yes root@<IP>`。

**问题 4 · 本机无 sshpass**:Git-Bash 不带 sshpass,无法在脚本里自动输密码。
- **解决**:一律走**公钥免密**;首次公钥注入通过控制台网页终端完成。

---

### 2.4 ⭐ 安全组件拦截 SSH —— 本次最大障碍

**统一现象**:`kex_exchange_identification: Connection closed by remote host`。TCP 能建立(`Connection established`),但在 SSH 协议握手第一步(发 banner 前)被**主动 RST**,**根本到不了用户名/密钥验证**。本地 `127.0.0.1:22` 却完全正常。这是典型的"**用户态安全程序按源 IP 掐连接**"。

排查经历了三个元凶,逐层剥开:

#### (a) 腾讯云云镜 YunJing（主机安全 agent）
- **定位**:`iptables -S` 有 `match-set YJ-GLOBAL-INBLOCK` 的 DROP 规则(`YJ`=YunJing);进程 `YDLive`、`YDService`,路径 `/usr/local/qcloud/YunJing/`;引用该黑名单的脚本 `clearRules.sh`、`stopYDCore.sh`。
- **自愈**:`stopYDCore.sh` 停了核心后,守护 `stargate`(腾讯云 agent 总管)会**重新拉起甚至重装**云镜。只停 YunJing 不停 stargate,几分钟就自愈。
- **彻底禁用**:
  ```bash
  systemctl disable --now stargate sgagent YDService YDLive 2>/dev/null
  kill -9 $(pgrep -x stargate) 2>/dev/null   # 精确进程名,勿用 -f
  kill -9 $(pgrep -x YDLive) 2>/dev/null
  kill -9 $(pgrep -x YDService) 2>/dev/null
  mv /usr/local/qcloud/YunJing  /usr/local/qcloud/YunJing.off
  mv /usr/local/qcloud/stargate /usr/local/qcloud/stargate.off
  ```
  > 长期建议:腾讯云控制台「主机安全」关闭该机「密码破解拦截」或直接卸载 agent。

#### (b) 宝塔面板 BT-Panel + 安全插件
- **定位**:`ss -tlnp` 见 `*:8888 BT-Panel`;`/www/server/panel/plugin/` 下有 `firewall`、`safeCloud`;进程 `BT-Panel`、`BT-Task`(`/www/server/panel/pyenv/bin/python3`);SSH 错误计数任务 `task_ssh_error_count.pl`。
- **防删**:`/www/server/panel/default.pl` 被 `chattr +i` 锁死(`rm` 报 `Operation not permitted`),还有开机自启入口会把守护拉回来。
- **彻底卸载**:
  ```bash
  # 先杀进程(按进程名,勿用 -f)
  for pid in $(ps -eo pid,comm | awk '/BT-Panel|BT-Task/{print $1}'); do kill -9 $pid; done
  # 解锁被 chattr +i 的文件
  chattr -R -i /www/server/panel 2>/dev/null
  rm -f /www/server/panel/default.pl
  # 找并禁用自启入口
  find /etc/rc.d /etc/systemd/system /etc/init.d /etc/cron.d /var/spool/cron 2>/dev/null \
    | xargs grep -l "/www/server/panel" 2>/dev/null | while read f; do chattr -i "$f" 2>/dev/null; mv "$f" "$f.off"; done
  crontab -l 2>/dev/null | grep -v "/www/server/panel" | crontab -
  rm -rf /www/server/panel
  ```
  > **卸载宝塔不影响** nginx/systemd/网站文件/证书 —— 它们在 `/etc/nginx`、`/etc/systemd`、`/etc/ssl/hvac`、`/var/www/hvac`,都不在宝塔目录下。

#### (c) 最终结论:网络路径级封锁（服务器内无解）
云镜、宝塔全清、iptables/nftables/hosts.deny 全空、腾讯云安全组 22 对 `0.0.0.0/0` 放行(截图确认)后,**外部 SSH 仍被拦**。

**决定性证据**(抓 sshd 日志):
- 其他攻击者 IP(如 `8.222.233.94`)能到达 sshd、留下暴力破解日志;
- **我方出口 IP 完全没有任何 sshd 日志** —— TCP 建立后在到达 sshd 前就被掐;
- 从国内服务器连该机 22 则是 **TCP 直接超时**(另一种拦截)。

→ 拦截发生在**服务器主机之外的网络路径**(云商策略或线路级封锁),服务器内部无法解决。**放弃恢复 SSH,改用 autopull 方案**(见 2.8)。

---

### 2.5 系统差异（OpenCloudOS 9）

新加坡这台是 **OpenCloudOS 9.6**(腾讯云国产 OS,RHEL9 系),与 Ubuntu 差异:
- 包管理是 **dnf**(非 apt)。
- **无 `www-data`/`nginx` 用户**(装 nginx 前) → systemd 服务 `User=` 指定这些会启动失败。**改用 root 运行 + `chmod -R a+rX`**。
- **SELinux 默认 enforcing** → nginx 反代到 127.0.0.1:8137 需放行:`setsebool -P httpd_can_network_connect 1`(兜底 `setenforce 0`)。

---

### 2.6 nginx 安装（两个连环坑）

**坑 1 · 宝塔 exclude**:`dnf install nginx` 报 `All matches were filtered out by exclude filtering`。宝塔在 dnf 配置里加了 `exclude=nginx*`(防止系统 nginx 与它冲突)。
- **解决**:`dnf install -y --disableexcludes=all nginx`。

**坑 2 · 官方源 openssl 依赖冲突**:加 nginx 官方 el9 源后,最新 nginx 1.30 需要 `libssl.so.3(OPENSSL_3.2.0/3.5.0)`,OpenCloudOS 9 自带 openssl 版本不够 → `nothing provides libssl.so.3(OPENSSL_3.2.0)`。
- **解决**:**别用 nginx 官方源**。OpenCloudOS 默认源里就有兼容的 nginx 1.26.3,移除官方源 + `--disableexcludes=all` 即可。

---

### 2.7 HTTPS 证书

**国内服务器(旧)**:出境被墙,连不上**任何** ACME CA(Let's Encrypt/ZeroSSL/Google/Buypass 全 `HTTP 000`)。
- **方案**:在**能出境的本机**用 `acme.sh` + GoDaddy **DNS-01** 签发,再 scp 证书到服务器。续期也在本机(Windows 计划任务)。

**新加坡服务器(新)**:能出境(`LE:200`)。
- **方案**:**服务器本地自签自续**。`acme.sh --issue --dns dns_gd`(GoDaddy DNS-01,凭据存服务器 `~/.acme.sh/account.conf`),`--install-cert --reloadcmd "nginx -s reload"`,acme.sh cron 自动续期,**全程不需 SSH**。这是境外服务器相比国内的最大优势。

**其他证书坑**:
- acme.sh 偶发 `curl error 35`(SSL handshake) → **重试即可**,不是配置问题。
- `dns_gd` 删验证 TXT 时偶发 error 35 → 残留 `_acme-challenge` TXT,用 GoDaddy API `DELETE .../records/TXT/_acme-challenge.hvac` 清理。
- 用 **DNS-01 而非 HTTP-01**:不依赖 A 记录已指向本机,可在切 DNS 前就把证书签好,减少迁移窗口。

---

### 2.8 代码更新方案的演进

| 阶段 | 方案 | 为何放弃/采用 |
|------|------|--------------|
| 国内 | 本机 `deploy.sh` SSH 中转(打包→scp→重启) | 可用 |
| 新加坡·尝试1 | 同上 SSH 中转 | **SSH 被网络层封锁,不可用** |
| 新加坡·尝试2 | 控制台 `curl raw \| bash` 全量部署脚本 | 首次部署用,日常更新太重 |
| 新加坡·最终 | **服务器 systemd timer 每分钟 `git pull`** | ✅ 不依赖 SSH,push 即上线 |

**autopull 最终形态**:
- 本机改代码 → `git push` → 服务器 `hvac-autopull.timer` 每分钟触发 `git pull`;
- `server.py` 的 md5 变化才 `systemctl restart hvac`,前端变化零中断即时生效;
- 日志 `/var/log/hvac-autopull.log`,每次更新一行 `[UPD] <old> -> <new> | ... | HTTPS:200`;
- **前提**:仓库须 **public**(服务器匿名 pull)。改 private 会静默 `fetch 失败`。

---

### 2.9 反复踩的"老坑"合集

#### ⭐ 坑 A · `pkill -9 -f "字符串"` 自杀
**最坑、踩了至少 3 次**(safeCloud、qcloud/YunJing、panel/pyenv/python3)。

**现象**:控制台跑一段 `sudo bash -c '... pkill -9 -f "safeCloud" ...'`,只输出一个 `Killed` 就回到提示符,后面的命令全没执行。

**根因**:`pkill -f` 匹配进程的**完整命令行**。而执行这条命令的 `bash -c '...safeCloud...'` 进程,它自己的命令行里**就包含 "safeCloud" 这个字符串**,于是 pkill 把自己的父 bash 也匹配上并 `kill -9` → 脚本被自己杀死中断。

**正确做法**:
```bash
# ✅ 用 -x 精确匹配"进程名"(comm),不匹配命令行
pkill -9 -x YDLive
# ✅ 或按进程名取 PID 再杀
for pid in $(ps -eo pid,comm | awk '/BT-Panel|BT-Task/{print $1}'); do kill -9 $pid; done
# ❌ 危险:字符串会出现在当前命令行里
pkill -9 -f "safeCloud"
```

#### 坑 B · git shallow clone
**现象**:`git fetch --depth 1` 报 `fatal: shallow file has changed since we read it`。
**解决**:自动更新脚本里**去掉 `--depth`**,用完整 `git fetch origin main`。已 clone 的 shallow 仓库用 `git fetch --unshallow` 转完整。

#### 坑 C · Windows cmd.exe 把 UTF-8 中文当 GBK
**现象**:`.bat` 里写中文 `REM` 注释,双击运行报 `'…' 不是内部或外部命令`。
**根因**:中文 Windows 的 cmd.exe 用 GBK/CP936 解码 UTF-8 存的 bat,多字节中文被拆成乱码当命令执行。
**解决**:`.bat` 一律用**纯 ASCII(英文)注释**。

#### 坑 D · schannel 偶发握手失败
**现象**:本机 curl 验证线上 HTTPS 偶发 `curl (35) schannel: failed to receive handshake`。
**根因**:本机走代理,到服务器的 TLS 偶发抖动。**服务器端本地验证是 200**。
**解决**:**重试**;验证优先在服务器侧做(`--resolve ...:127.0.0.1`)更稳。

#### 坑 E · 部署脚本 systemd `User=` 指向不存在的用户
**现象**:`hvac.service` active 但 `!! 后端未就绪`。
**根因**:OpenCloudOS 无 `www-data`/`nginx` 用户,`User=nginx` 导致启动失败。
**解决**:去掉 `User=`(用 root),配 `chmod -R a+rX`。

#### 坑 F · systemd `Type=simple` 的"active"假象
**现象**:`systemctl is-active hvac` = active,但 `curl 127.0.0.1:8137` 连不上(000)。
**根因**:`Type=simple` 下 active 只表示进程存在,不代表已监听就绪。CoolProp 首次 import 约 2-3 秒。
**解决**:启动后**轮询** health 直到就绪:`for i in $(seq 1 15); do curl -sf .../api/health && break; sleep 1; done`。

---

## 附录 A · QA（常见问题）

**Q1:为什么网站在国内服务器打不开?**
未 ICP 备案。大陆服务器跑 Web 必须备案,否则腾讯云网络层拦 80/443。境外服务器 + 境外域名不需要备案。

**Q2:域名 DNS 在哪管?能用 Cloudflare 加速吗?**
在 **GoDaddy**(https://dcc.godaddy.com)。NS 里虽有 Cloudflare 残留,但生效的是 GoDaddy,**不能用 Cloudflare 橙云代理**(域名没托管在 CF)。改记录用 GoDaddy API 或面板。

**Q3:为什么用子域名 `hvac.*` 而不是根域名?**
根域名 `geopro.cc`→Vercel、`geotoday.net`→AWS,都有现网服务,动根域名会搞挂。子域名 `hvac.*` 独立指向新服务器,互不影响。

**Q4:两个域名怎么改指向?**
GoDaddy API PUT A 记录(见 2.2),或面板改。改后等 DNS 传播(TTL 600s),用 `curl "https://dns.google/resolve?name=hvac.geopro.cc&type=A"` 查真实生效值。

**Q5:服务器怎么登录?**
`ssh -i ~/.ssh/id_ed25519 -o IdentitiesOnly=yes root@43.156.58.154`。**但目前外部 SSH 被网络层封锁**(见 Q9),实际运维走**腾讯云控制台网页终端**。

**Q6:什么是 ICP,一定要备案吗?**
ICP 是中国大陆网站的经营许可备案。**只有服务器在大陆才需要**。本项目用新加坡服务器,规避了备案。代价:国内访问速度略逊于备案的大陆服务器。

**Q7:云镜(YunJing)是什么?为什么要禁用?**
腾讯云主机安全 agent(`/usr/local/qcloud/YunJing`,进程 YDLive/YDService)。它的"密码破解拦截"会把陌生 IP 的 SSH 连接用户态 RST 掉,连正常运维都被拦。自用机建议禁用/卸载(见 2.4a)。禁用后控制台「主机安全」显示离线,无碍。

**Q8:宝塔面板(BT-Panel)是什么?为什么卸载?**
Linux 服务器可视化面板(8888 端口)。它的 `firewall`/`safeCloud` 插件同样会拦 SSH,且有 `chattr +i` 防删和自启自愈。本项目不用它管站(用命令行 nginx+systemd),故彻底卸载(见 2.4b)。卸载不影响 nginx/网站/证书。

**Q9:为什么 SSH 一直连不上,报 `Connection closed`?**
TCP 建立后握手前被 RST。逐层排查过云镜、宝塔、iptables/nftables、安全组,全清后仍被拦。决定性证据:**别的 IP 能到 sshd 留日志,我方 IP 无任何日志** → 拦截在服务器**之外**的网络路径(云商/线路级),主机内无解。因此改用 autopull(服务器主动 pull),不再依赖 SSH。

**Q10:防火墙有几层?改哪层有用?**
三层,由外到内:
1. **网络路径/云商策略**(本次拦 SSH 的最终元凶)—— 主机内改不了。
2. **腾讯云安全组**(控制台配)—— 在网卡之外,主机内 iptables 改不动它;本例 22 已对 0.0.0.0/0 放行。
3. **主机内 iptables/nftables/云镜/宝塔**(SSH 命令可改)—— 本例已全清。
判断在哪层:主机内规则清了还拦 → 往上层(安全组/网络路径)看;别的 IP 能进只有你不行 → 网络路径针对性封锁。

**Q11:证书怎么续期?会过期吗?**
新加坡服务器上 **acme.sh 自动续期**(GoDaddy DNS-01,cron 本地跑,reload nginx),不需人工、不需 SSH。当前证书到 2026-10-05,会在到期前自动续。

**Q12:我改了代码怎么上线?**
`git push` 到 `yhai3596/hvactool` 的 main。服务器每分钟自动 `git pull`,1 分钟内上线。前端改动即时生效,后端(server.py)改动会自动重启服务。**你无需登录服务器**。

**Q13:autopull 靠什么工作?仓库为什么要 public?**
服务器 `hvac-autopull.timer`(systemd,每分钟)跑 `git pull`。它用 **https 匿名**拉取,所以仓库必须 **public**。改成 private 会导致 fetch 失败、更新停止(日志会记 `[WARN]`)。仓库内无密钥,公开安全。

**Q14:那个 `Killed` 是怎么回事?(pkill 老坑)**
`pkill -9 -f "safeCloud"` 的 `-f` 匹配**整条命令行**;而正在执行这条命令的 `bash -c '...safeCloud...'`,其命令行里就有 "safeCloud",于是 pkill **把自己杀了**,显示 `Killed`,后续命令全不执行。**永远用 `pkill -x 进程名` 或 `ps -eo pid,comm | awk` 按进程名匹配**,不要用 `-f` 匹配会出现在当前命令里的字符串。

**Q15:如果哪天自动更新不动了怎么办?**
控制台网页终端查:`systemctl status hvac-autopull.timer`(是否 active)、`tail -20 /var/log/hvac-autopull.log`(有无 `[WARN]`)。常见:仓库被设回 private(改回 public)、`/var/www/hvac` 不是 git 仓库、网络到 GitHub 不通。手动补一次:`cd /var/www/hvac && git fetch origin main && git reset --hard origin/main && systemctl restart hvac`。

---

## 附录 B · 关键命令速查

```bash
# ── 本机:改域名指向(GoDaddy) ──
curl -X PUT -H "Authorization: sso-key {KEY}:{SECRET}" -H "Content-Type: application/json" \
  "https://api.godaddy.com/v1/domains/geopro.cc/records/A/hvac" -d '[{"data":"IP","ttl":600}]'

# ── 本机:查真实公网 DNS(绕过本机代理) ──
curl -s "https://dns.google/resolve?name=hvac.geopro.cc&type=A"

# ── 本机:外部验证线上(校验证书) ──
curl -sS --resolve hvac.geopro.cc:443:43.156.58.154 -o /dev/null \
  -w "%{http_code} verify:%{ssl_verify_result}\n" https://hvac.geopro.cc/

# ── 控制台:看自动更新状态 ──
systemctl status hvac-autopull.timer
tail -f /var/log/hvac-autopull.log

# ── 控制台:手动强制同步一次 ──
cd /var/www/hvac && git fetch origin main && git reset --hard origin/main && systemctl restart hvac

# ── 控制台:看后端/nginx ──
systemctl is-active hvac nginx
journalctl -u hvac -n 30 --no-pager
curl -sk --resolve hvac.geopro.cc:443:127.0.0.1 -o /dev/null -w "%{http_code}\n" https://hvac.geopro.cc/

# ── 控制台:安全地杀进程(勿用 -f) ──
pkill -9 -x <进程名>
for pid in $(ps -eo pid,comm | awk '/名字/{print $1}'); do kill -9 $pid; done

# ── 控制台:证书手动续期 ──
~/.acme.sh/acme.sh --cron
```

---

## 附录 C · 排查决策树

```
网站打不开?
├─ 本地 curl(127.0.0.1) 200,外网不通?
│    ├─ 大陆服务器 → 查 ICP 备案(未备案会被拦 80/443)
│    └─ 云安全组是否放行 80/443
├─ DNS 指向对不对? → curl dns.google/resolve 查真实 A 记录
└─ 证书问题? → openssl s_client 看有效期/颁发者

SSH 连不上?
├─ Connection closed(握手前被 RST)?
│    ├─ 本地 127.0.0.1:22 有 banner? → sshd 正常,是外部拦截
│    ├─ 别的 IP 能进只你不行? → 网络路径/云商针对性封锁(主机内无解,走控制台/autopull)
│    ├─ 查主机内: ps 找 YDLive/YDService(云镜)、BT-Panel(宝塔)、iptables/nftables、hosts.deny
│    └─ 云安全组 22 来源是否限制了 IP
├─ Permission denied(publickey)? → authorized_keys 是否有你的公钥(重装会清空)
└─ 主机密钥变了? → ssh-keygen -R <IP>,确认非 MITM 后重连

自动更新停了?
├─ systemctl status hvac-autopull.timer(active?)
├─ tail /var/log/hvac-autopull.log(有 [WARN]?)
├─ 仓库是否被设回 private? → 改回 public
└─ 手动同步: cd /var/www/hvac && git fetch && git reset --hard origin/main

杀进程/清组件时脚本莫名 "Killed" 中断?
└─ 检查是否用了 pkill -f "字符串",且该字符串出现在当前命令行 → 改 pkill -x 或 ps|awk
```

---

*最后更新:2026-07-08 · 迁移与本手册作者:Claude Code 协助 Alan 完成*
