#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信云托管入口：复用已验证的 server.py 计算函数，只暴露 GET 计算 API。
  - 监听 0.0.0.0:$PORT（云托管硬性要求；默认 80，与 Dockerfile EXPOSE / 控制台 containerPort 一致）
  - 根路径 / 与 /health 返回 200（供云托管健康检查探针）
  - 不含静态托管、不含 Supabase 代理（小程序用不到，缩小攻击面）
  - server.py 内容与主站完全一致（规矩 5.3：已验证代码不改，只 import 复用）
本地试跑:  PORT=8139 python app.py
"""
import json
import os
import traceback
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from server import ROUTES   # 已验证的 10 个 GET 计算路由（/api/health /api/props /api/sat ...）

PORT = int(os.environ.get('PORT', 80))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):        # 云托管自己采集访问日志，这里静默
        pass

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False, default=str).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ('/', '/health'):        # 健康检查
            self._json(200, {'ok': True, 'service': 'hvac-coolprop'})
            return
        if u.path in ROUTES:
            try:
                self._json(200, ROUTES[u.path](parse_qs(u.query)))
            except ValueError as e:
                self._json(400, {'error': str(e)})
            except Exception as e:
                traceback.print_exc()
                self._json(500, {'error': '计算失败: %s' % str(e)[:200],
                                 'hint': '请检查输入是否超出物性有效范围'})
            return
        self._json(404, {'error': 'not found'})


if __name__ == '__main__':
    print('hvac-coolprop container listening on 0.0.0.0:%d' % PORT, flush=True)
    ThreadingHTTPServer(('0.0.0.0', PORT), Handler).serve_forever()
