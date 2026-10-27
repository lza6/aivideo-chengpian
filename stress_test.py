# -*- coding: utf-8 -*-
"""AI视频智能成片 demo server 本地压测 — 第一轮"""
import json
import time
import concurrent.futures as cf
import urllib.request
import statistics
import sys

sys.stdout.reconfigure(encoding='utf-8')
BASE = 'http://127.0.0.1:8907'


def call(path, method='GET', body=None, timeout=15):
    t0 = time.perf_counter()
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={'Content-Type': 'application/json'} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            r.read()
            return time.perf_counter() - t0, r.status
    except urllib.error.HTTPError as e:
        e.read()
        return time.perf_counter() - t0, e.code
    except Exception:
        return time.perf_counter() - t0, 0


def report(name, times, expected):
    codes_ok = all(c == expected for _, c in times)
    lat = sorted(t for t, _ in times)
    med = statistics.median(lat) * 1000
    p95 = lat[int(len(lat) * .95) - 1] * 1000
    print(f"{'PASS' if codes_ok else 'FAIL'}  {name:34s} n={len(times):3d} "
          f"median={med:7.1f}ms  p95={p95:8.1f}ms  codes={set(c for _, c in times)}")
    return codes_ok


results = []

# 1. 本地健康检查（纯本地，无上游）
t = [call('/health') for _ in range(200)]
results.append(report('health 200x', t, 200))

# 2. 透传上游 /api/tools（含上游 RTT）
t = [call('/api/tools') for _ in range(30)]
results.append(report('proxy /api/tools 30x', t, 200))

# 3. 上游 /api/config
t = [call('/api/config') for _ in range(30)]
results.append(report('proxy /api/config 30x', t, 200))

# 4. 错误路径：未知路由
t = [call('/api/noexist') for _ in range(50)]
results.append(report('404 route 50x', t, 404))

# 5. demo 任务创建（并发 20）
def mk(i):
    return call('/api/demo/text2video', 'POST', {'prompt': f'stress {i}'})
with cf.ThreadPoolExecutor(20) as ex:
    t = list(ex.map(mk, range(20)))
results.append(report('demo task create 20c x20', t, 200))

# 6. 任务查询并发
with cf.ThreadPoolExecutor(10) as ex:
    t = list(ex.map(lambda i: call('/api/tasks'), range(100)))
results.append(report('tasks list 10c x100', t, 200))

# 7. 登录错误路径（上游 4xx 结构化返回）
t = [call('/api/login', 'POST', {'phone': '13800138000', 'code': '000000'}) for _ in range(10)]
results.append(report('login wrong-code 10x', t, 200))

# 8. send/code 限速观察（上游真实发短信，只测 5 次看是否限流）
t = [call('/api/send/code', 'POST', {'phone': '13800138000'}) for _ in range(5)]
results.append(report('send/code 5x (upstream)', t, 200))

print()
ok = sum(results)
print(f'== {ok}/{len(results)} PASS')
