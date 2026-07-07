# 用 Python 标准库 + CoolProp 造一个暖通工具站，附国内服务器签 Let's Encrypt 的踩坑实录

> 在线站点：https://hvac.geopro.cc ｜ 技术栈：原生前端 + `http.server` + CoolProp + nginx + acme.sh

本文分两部分：一是这个暖通计算/仿真工具站的**技术实现**，二是把它部署到**国内云服务器**时,签 HTTPS 证书遇到的坑和最终解法。后半部分对所有在国内服务器上部署的同学都有参考价值。

---

## 一、为什么是"无框架 + 标准库"

工程计算工具，**稳定、可信、可长期维护**比技术时髦重要。所以刻意选了最轻的路线：

- **前端**：原生 HTML/CSS/JavaScript，Canvas/SVG 绘图，**零构建、零框架、无 npm**。
- **后端**：Python 标准库 `http.server` 单文件，静态托管 + 一组物性 JSON API。
- **物性引擎**：[CoolProp](http://www.coolprop.org/) 8.x。
- **认证**：Supabase（前端直连 publishable key）。
- **生产**：Ubuntu 24.04 + nginx 反代 + systemd + Let's Encrypt。

整站前端不到一百 KB，后端一个 `server.py`。

## 二、后端：stdlib http.server 包一层 CoolProp

核心就是把 CoolProp 的 `PropsSI` / `HAPropsSI` 暴露成 JSON 接口。用 `ThreadingHTTPServer` + `SimpleHTTPRequestHandler`，路由用一个 dict 分发：

```python
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from CoolProp.CoolProp import PropsSI, HAPropsSI

ROUTES = {
    '/api/health':   api_health,
    '/api/props':    api_props,      # 任意状态点物性
    '/api/sat':      api_sat,        # 饱和点
    '/api/sattable': api_sat_table,  # 饱和表
    '/api/dome':     api_dome,       # 压焓图穹顶
    '/api/phcycle':  api_phcycle,    # 理论循环
    '/api/psychro':  api_psychro,    # 湿空气
    '/api/watersat': api_watersat,
    '/api/liquid':   api_liquid,     # 水/乙二醇输送物性
}

ThreadingHTTPServer(('127.0.0.1', 8137), Handler).serve_forever()
```

几个工程上的处理值得一提：

**① 焓熵基准统一到 IIR。** CoolProp 默认基准和常用物性表册不一致，直接给用户会对不上表。统一偏移到 IIR（0°C 饱和液 h=200 kJ/kg，s=1.0）：

```python
h0 = PropsSI('H', 'T', 273.15, 'Q', 0, cp_name)
offset_h = h0 - 200000.0   # 后续所有 H 减去该偏移
```

**② 预定义混合物的临界参数兜底。** `R454B.mix` 这类预定义混合物用 `Props1SI` 查不到临界参数，用文献常数兜底（Opteon XL41：Tc 78.1°C / Pc 5.267 MPa / M 62.6）。

**③ 只监听 127.0.0.1。** 后端不直接对外，由 nginx 反代，减少暴露面。

前端所有计算页通过 `fetch` 调这些接口，压焓图/焓湿图用 Canvas 画，状态点可拖拽后防抖调 API 精算。

## 三、systemd + nginx

后端做成 systemd 服务常驻：

```ini
[Service]
User=www-data
WorkingDirectory=/var/www/hvac
ExecStart=/var/www/hvac/venv/bin/python /var/www/hvac/server.py
Restart=on-failure
```

nginx 反代 + 强制 HTTPS：

```nginx
server {
    listen 80;
    server_name hvac.geopro.cc;
    return 301 https://$host$request_uri;
}
server {
    listen 443 ssl http2;
    server_name hvac.geopro.cc;
    ssl_certificate     /etc/ssl/hvac/geopro.fullchain.cer;
    ssl_certificate_key /etc/ssl/hvac/geopro.key;
    location / { proxy_pass http://127.0.0.1:8137; }
}
```

> 小坑：nginx 1.24 用 `listen 443 ssl http2;`，别写成 1.25 才有的独立指令 `http2 on;`，否则 `unknown directive`。

## 四、重头戏：国内服务器签 Let's Encrypt 的坑

这才是最值得写的部分。

### 坑 1：服务器出境被限，连不上任何 ACME CA

在服务器上直接跑 certbot：

```
ValueError: Requesting acme-v02.api.letsencrypt.org/directory: Network is unreachable
```

排查后确认**不是 IPv6 问题，而是出境到 Let's Encrypt（走 Cloudflare 的 IP）被阻断**。挨个测：

```bash
# 全部 HTTP 000 超时：
curl -m12 https://acme-v02.api.letsencrypt.org/directory   # Let's Encrypt
curl -m12 https://acme.zerossl.com/v2/DV90                  # ZeroSSL
curl -m12 https://api.buypass.com/acme/directory           # Buypass
curl -m12 https://api.cloudflare.com/client/v4             # Cloudflare API
# 只有国内可达：
curl -m12 https://cloud.tencent.com                        # HTTP 200
```

结论：**在这台服务器上，任何需要连境外 ACME CA 的方案都行不通**——certbot、acme.sh、DNS-01 全部卡在"连不上 CA"这一步。服务器自己也别想 `git pull` GitHub。

### 坑 2：DNS 不在 Cloudflare，用不了橙云代理

本来想用 Cloudflare 橙云代理让边缘出证书，一查 `NS` 记录，域名实际托管在 GoDaddy（`domaincontrol.com`），Cloudflare 那两条 NS 是残留没生效。此路不通。

### 解法：本机签发 + 自动推送 + 自动续期

关键观察：**服务器出境被限，但本机能出境（能连 GitHub / CA），也能 SSH 到服务器。** 那就让本机做中转。

用 acme.sh + 域名商 API 做 DNS-01（GoDaddy 支持 API，先测账户可用）：

```bash
export GD_Key=xxx GD_Secret=yyy
~/.acme.sh/acme.sh --issue --dns dns_gd -d hvac.geopro.cc --server letsencrypt
```

acme.sh 自动加/删 `_acme-challenge` TXT、验证、签发。证书签好后，用 `--install-cert --reloadcmd` 绑定"续期后自动部署"钩子——**在本机执行**，scp 证书到服务器再 reload nginx：

```bash
~/.acme.sh/acme.sh --install-cert -d hvac.geopro.cc --ecc \
  --reloadcmd "scp .../fullchain.cer root@SERVER:/etc/ssl/hvac/geopro.fullchain.cer \
            && scp .../*.key       root@SERVER:/etc/ssl/hvac/geopro.key \
            && ssh root@SERVER 'systemctl reload nginx'"
```

最后用 Windows 计划任务每天跑 `acme.sh --cron`，临期自动续、自动推、自动重载。**整条链路：签发、续期、部署都在本机完成，服务器全程不需要出境。**

### 顺带：代码更新也走"本机中转"

同理，服务器不能 `git pull`，于是写了个一键部署脚本 `deploy.sh`：本机打包→scp→**仅当 `server.py` 变化才重启后端**（前端是 `SimpleHTTPRequestHandler` 实时读盘，改 HTML/JS 即时生效、零中断）→服务器侧 curl 200 验证。

```bash
OLD=$(ssh $SRV "md5sum $DIR/server.py|cut -d' ' -f1")
NEW=$(md5sum server.py|cut -d' ' -f1)
# ... 上传解压 ...
[ "$OLD" != "$NEW" ] && ssh $SRV "systemctl restart hvac"   # 仅后端变才重启
```

## 五、小结

- 工程工具，**克制的技术选型**（无框架 + 标准库）换来长期可维护性；
- 物性计算别自己拟合，**站在 CoolProp 肩膀上**，并统一到用户熟悉的基准；
- 国内服务器部署，**"本机中转"是绕开出境限制的通用思路**——证书签发、续期、代码部署都可以放到能出境的本机，服务器只当被动接收端。

站点：**https://hvac.geopro.cc** ，欢迎试用。有问题欢迎评论区交流。

---

*作者：Alan ｜ 公众号：Alan 的 AI 世界。*
