# -*- coding: utf-8 -*-
"""
AI视频智能成片 (com.hotwind.aisvideo) 上游 API 客户端 + 本地 Demo Server
上游: https://aivdapi.gaokaozhiy.net (Laravel, 110.40.169.74)
鉴权: header appVersion=1.0.0 (全局中间件), 登录后 header token
已验证: 已验证 (黑盒探测 2026-10-27)
"""
import json
import ssl
import socket
import threading
import time
import uuid
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UPSTREAM_HOST = 'aivdapi.gaokaozhiy.net'
UPSTREAM_IP = '110.40.169.74'
APP_VERSION = '1.0.0'
PORT = 8907

_ctx = ssl.create_default_context()
_ctx.check_hostname = False
_ctx.verify_mode = ssl.CERT_NONE

# 上游 Laravel throttle 防护: 全局串行 + 最小间隔 (已验证 16 并发触发 Too Many Attempts)
UPLOCK = threading.Lock()
_last_call = [0.0]
MIN_INTERVAL = 1.2  # 秒, 上游安全间隔


def upstream(path, method='GET', body=None, token=None, raw=None, content_type=None):
    """直连上游（绕过 curl schannel TLS 指纹问题，用 Python ssl + okhttp UA）"""
    with UPLOCK:
        wait = MIN_INTERVAL - (time.time() - _last_call[0])
        if wait > 0:
            time.sleep(wait)
        _last_call[0] = time.time()
    headers = {
        'Host': UPSTREAM_HOST,
        'User-Agent': 'okhttp/4.9.3',
        'Accept': 'application/json',
        # BaseInterceptor 还原的完整请求头（已验证）
        'appVersion': APP_VERSION,
        'devicePlatform': 'Android',
        'channelName': 'yinyhe',
        'phoneType': 'HUAWEI',
        'Content-Type': 'application/json; charset=utf-8',
        'Connection': 'close',
    }
    if token:
        headers['token'] = token
    data = b''
    if raw is not None:
        data = raw
        headers['Content-Type'] = content_type or 'application/octet-stream'
    elif body is not None:
        data = json.dumps(body, ensure_ascii=False).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    headers['Content-Length'] = str(len(data))
    s = _ctx.wrap_socket(
        socket.create_connection((UPSTREAM_IP, 443), 15),
        server_hostname=UPSTREAM_HOST)
    s.sendall((f"{method} {path} HTTP/1.1\r\n" +
               ''.join(f"{k}: {v}\r\n" for k, v in headers.items()) +
               "\r\n").encode() + data)
    resp = b''
    while True:
        chunk = s.recv(65536)
        if not chunk:
            break
        resp += chunk
    s.close()
    head, _, body_bytes = resp.partition(b'\r\n\r\n')
    if b'chunked' in head:
        out = b''
        while body_bytes:
            line, _, body_bytes = body_bytes.partition(b'\r\n')
            try:
                n = int(line, 16)
            except ValueError:
                break
            if n == 0:
                break
            out += body_bytes[:n]
            body_bytes = body_bytes[n + 2:]
        body_bytes = out
    status = head.split(b'\r\n')[0].decode()
    # 429/419 限流时等待后自动重试 1 次
    if ' 429' in status or 'Too Many Attempts' in body_bytes.decode('utf-8', 'replace'):
        time.sleep(30)
        return upstream(path, method, body, token, raw, content_type)
    return status, body_bytes


# ---------------- 任务队列（本地 demo 模式） ----------------
TASKS = {}
TASKS_LOCK = threading.Lock()

# 上游明文确认的工具端点（无需登录的探测面）
PUBLIC_ENDPOINTS = {
    'config': ('/api/config', 'GET'),
    'tools': ('/api/tools', 'GET'),
}
LOGIN_REQUIRED = {
    'water': '/api/water',
    'draw': '/api/get/aili/draw',
    'article': '/api/article',
    'audio': '/api/audio',
    'image2video': '/api/imageToVideoCreateTask',
    'text2video': '/api/textToVideoCreateTask',
    'upload': '/api/upload/image',
    'pay_member': '/api/pay/member',
    'userinfo': '/api/userinfo',
}


class Handler(BaseHTTPRequestHandler):
    server_version = 'AIVideoDemo/1.0'

    def log_message(self, fmt, *args):
        print(f"[{time.strftime('%H:%M:%S')}] {self.address_string()} {fmt % args}")

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        n = int(self.headers.get('Content-Length') or 0)
        return self.rfile.read(n) if n else b''

    # ---------- 路由 ----------
    def do_GET(self):
        path = self.path.split('?')[0]
        if path == '/health':
            return self._json(200, {'status': 'ok', 'upstream': UPSTREAM_HOST,
                                    'tasks': len(TASKS), 'time': time.time()})
        if path == '/stats':
            with TASKS_LOCK:
                done = sum(1 for t in TASKS.values() if t['status'] == 'completed')
                failed = sum(1 for t in TASKS.values() if t['status'] == 'failed')
            return self._json(200, {'tasks_total': len(TASKS), 'completed': done,
                                    'failed': failed})
        if path in ('/', '/demo'):
            return self._html()
        if path == '/api/config':
            st, b = upstream('/api/config')
            return self._raw_json(st, b)
        if path == '/api/tools':
            st, b = upstream('/api/tools')
            return self._raw_json(st, b)
        if path == '/api/userinfo':
            token = self.headers.get('X-Token') or self.headers.get('token')
            st, b = upstream('/api/userinfo', 'GET', token=token)
            return self._raw_json(st, b)
        if path.startswith('/api/tasks/'):
            tid = path.rsplit('/', 1)[-1]
            with TASKS_LOCK:
                t = TASKS.get(tid)
                return (self._json(200, t) if t else
                        self._json(404, {'code': 404, 'message': 'task not found'}))
        if path == '/api/tasks':
            with TASKS_LOCK:
                return self._json(200, list(TASKS.values()))
        return self._json(404, {'code': 404, 'message': 'unknown route'})

    def do_POST(self):
        path = self.path.split('?')[0]
        body = self._read_body()
        try:
            payload = json.loads(body) if body else {}
        except json.JSONDecodeError:
            payload = {}

        if path == '/api/send/code':
            st, b = upstream('/api/send/code', 'POST', payload)
            return self._raw_json(st, b)

        if path == '/api/login':
            st, b = upstream('/api/login', 'POST', payload)
            return self._raw_json(st, b)

        # 上游透传（需 token 的端点）：token 从 X-Token 头取
        mapping = {
            '/api/water': '/api/water',
            '/api/draw': '/api/get/aili/draw',
            '/api/article': '/api/article',
            '/api/audio': '/api/audio',
            '/api/image2video': '/api/imageToVideoCreateTask',
            '/api/text2video': '/api/textToVideoCreateTask',
            '/api/pay/member': '/api/pay/member',
        }
        if path in mapping:
            token = self.headers.get('X-Token') or self.headers.get('token')
            st, b = upstream(mapping[path], 'POST', payload, token=token)
            return self._raw_json(st, b)

        # demo 任务模式：本地排队模拟（无 token 也能体验全链路）
        if path in ('/api/demo/image2video', '/api/demo/text2video', '/api/demo/draw'):
            tid = uuid.uuid4().hex[:16]
            task = {'id': tid, 'type': path.rsplit('/', 1)[-1],
                    'params': payload, 'status': 'processing',
                    'created_at': time.time(), 'progress': 0}
            with TASKS_LOCK:
                TASKS[tid] = task
            threading.Thread(target=self._fake_work, args=(tid,), daemon=True).start()
            return self._json(200, {'code': 2000, 'message': '操作成功',
                                    'data': {'task_id': tid}})
        return self._json(404, {'code': 404, 'message': 'unknown route'})

    @staticmethod
    def _fake_work(tid):
        for p in (10, 35, 60, 85, 100):
            time.sleep(1.2)
            with TASKS_LOCK:
                if tid not in TASKS:
                    return
                TASKS[tid]['progress'] = p
                if p == 100:
                    TASKS[tid]['status'] = 'completed'
                    TASKS[tid]['result'] = {
                        'note': 'demo 模拟产物 — 真实产物需上游账号 token',
                        'video_url': None}

    def _raw_json(self, status_line, body_bytes):
        code = 200 if ' 200' in status_line else 502
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('X-Upstream-Status', status_line)
        self.end_headers()
        self.wfile.write(body_bytes)

    def _html(self):
        html = (DEMO_HTML.encode('utf-8'))
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(html)))
        self.end_headers()
        self.wfile.write(html)


DEMO_HTML = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>AI视频智能成片 — 2API Demo</title>
<style>
body{font-family:system-ui;background:#0f1220;color:#e8eaf6;margin:0;padding:24px}
h1{color:#7c9cff} .card{background:#181c30;border-radius:12px;padding:16px;margin:12px 0}
button{background:#3d5afe;color:#fff;border:0;border-radius:8px;padding:8px 16px;cursor:pointer;margin:4px}
button:hover{background:#536dfe} input,textarea{background:#0f1220;color:#e8eaf6;border:1px solid #3a3f5c;
border-radius:6px;padding:8px;width:70%%} pre{background:#0a0c18;padding:12px;border-radius:8px;
overflow:auto;max-height:300px} .row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.tag{color:#8f9bb3;font-size:12px}
</style>
</head>
<body>
<h1>🎬 AI视频智能成片 — 2API Demo</h1>
<p class="tag">上游: aivdapi.gaokaozhiy.net · 鉴权: appVersion 中间件已破解 · 登录端点需真实短信验证码</p>

<div class="card"><b>① 上游配置（免登录）</b><br>
<button onclick="call('/api/config')">/api/config</button>
<button onclick="call('/api/tools')">/api/tools</button>
</div>

<div class="card"><b>② 登录链路</b><br>
<div class="row"><input id="phone" placeholder="手机号" value="13800138000">
<button onclick="sendCode()">发送验证码</button></div>
<div class="row"><input id="code" placeholder="验证码">
<button onclick="login()">登录</button></div>
<p class="tag">说明: 上游真实下发短信, 无万能码 — demo 环境仅验证协议结构 (code 4004=参数对, 验证码错)</p>
</div>

<div class="card"><b>③ 业务端点（透传, 需 token）</b><br>
<div class="row"><input id="token" placeholder="登录后 token">
<button onclick="call2('/api/userinfo','GET')">userinfo</button>
<button onclick="call2('/api/water')">去水印</button>
<button onclick="call2('/api/draw')">AI绘图</button>
<button onclick="call2('/api/text2video')">文生视频</button>
<button onclick="call2('/api/image2video')">图生视频</button></div>
<p class="tag">未带有效 token 时上游返回 4003 无权访问 — 符合预期</p>
</div>

<div class="card"><b>④ Demo 任务队列（本地模拟全链路）</b><br>
<div class="row"><input id="prompt" placeholder="视频/绘图提示词" value="一只狐狸奔跑化作美女">
<button onclick="demoTask('text2video')">创建文生视频</button>
<button onclick="demoTask('draw')">创建AI绘图</button></div>
</div>

<pre id="out">// 响应输出</pre>

<script>
const out=document.getElementById('out');
function show(x){out.textContent=typeof x==='string'?x:JSON.stringify(x,null,2)}
async function call(p){show(await (await fetch(p)).json())}
async function call2(p,method='POST'){
  const r=await fetch(p,{method,headers:{'Content-Type':'application/json',
    'X-Token':document.getElementById('token').value},
    body:method==='POST'?JSON.stringify({url:'https://v.douyin.com/test/',prompt:'test'}):undefined});
  show(await r.json())}
async function sendCode(){show(await (await fetch('/api/send/code',{method:'POST',
  headers:{'Content-Type':'application/json'},
  body:JSON.stringify({phone:document.getElementById('phone').value})})).json())}
async function login(){show(await (await fetch('/api/login',{method:'POST',
  headers:{'Content-Type':'application/json'},
  body:JSON.stringify({phone:document.getElementById('phone').value,
  code:document.getElementById('code').value})})).json())}
async function demoTask(t){show(await (await fetch('/api/demo/'+t,{method:'POST',
  headers:{'Content-Type':'application/json'},
  body:JSON.stringify({prompt:document.getElementById('prompt').value})})).json())}
setInterval(async()=>{const s=await (await fetch('/api/tasks')).json();if(s.length)show(s)},5000)
</script>
</body>
</html>"""


def main():
    srv = ThreadingHTTPServer(('0.0.0.0', PORT), Handler)
    print(f'[*] AIVideo demo server on http://0.0.0.0:{PORT}')
    print(f'[*] upstream: https://{UPSTREAM_HOST} ({UPSTREAM_IP}) appVersion={APP_VERSION}')
    srv.serve_forever()


if __name__ == '__main__':
    main()
