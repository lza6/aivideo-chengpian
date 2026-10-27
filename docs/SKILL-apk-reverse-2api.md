# Skill: APK 逆向 → 2API 工作流（Windows 环境可复用）

针对"国内 AI 类安卓 App"的系统性逆向协议、搭 2API 服务器、本地压测的完整流程。
来源：NoTrackAI / imagerator / phota3a / aivideo-chengpian 四个项目的实战沉淀。

## 适用条件

- APK 为国内灰产/工具类 AI App（Laravel/ThinkPHP 后端为多）
- 目标：还原上游协议 → 本地 2API（OpenAI 兼容或原样透传）→ 压测

## 流程

### Phase 1: 静态侦察（10 分钟，不反编译）

```bash
unzip app.apk -d raw
# 1. assets 内业务配置
cat raw/assets/*.json
# 2. dex 域名面（过滤 SDK 噪音）
grep -aohE "https?://[a-zA-Z0-9./_?=&-]+" raw/classes*.dex | sort -u \
  | grep -viE "umeng|alipay|weixin|google|adobe|w3.org|schemas|qq.com|aliyuncs"
# 3. 端点路径（Python 从字符串表提取）
python -c "import re; [print(m) for f in ['raw/classes.dex','raw/classes2.dex','raw/classes3.dex','raw/classes4.dex'] for m in sorted(set(re.findall(rb'api/[a-zA-Z][a-zA-Z0-9_/]+', open(f,'rb').read())))]"
# 4. 业务 dex 定位: hotwind/包名出现次数最多的那个 dex
```

### Phase 2: 黑盒探测（30 分钟，产出 80% 协议）

```python
# 核心: curl 被拒 ≠ 上游死。用 Python ssl + okhttp UA
import ssl, socket
ctx = ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
s = ctx.wrap_socket(socket.create_connection((ip,443),10), server_hostname=host)
s.sendall(f"GET {path} HTTP/1.1\r\nHost: {host}\r\nUser-Agent: okhttp/4.9.3\r\nConnection: close\r\n\r\n".encode())
```

- **405 响应回显全部方法** → 端点存在性确认利器
- **全局中间件爆破**：候选 header 列表逐个试（version/appVersion/X-Version/ver/versionCode...），特征是 4040"版本号不存在"→ 2000 成功
- **错误码分层**：403(无token) / 4004(验证码错) / 4005(参数结构错) — 用错误码变化反推字段名与格式
- **限流确认**：并发上探 → `Too Many Attempts.` = Laravel throttle（按接口+IP，60s 窗口）

### Phase 3: 源码级还原（可选，仅在需要签名算法/token 生成时）

```bash
# jadx 卡死(>8k 类)时直接用 androguard
python -c "
from androguard.misc import AnalyzeDex
a,d,dx = AnalyzeDex('business.dex')
for c in d.get_classes():
    if 'net/' in c.get_name() or 'Interceptor' in c.get_name():
        for m in c.get_methods():
            if m.get_code():
                for i in m.get_instructions(): print(i.get_output()[:130])
"
```

重点类：`net/BaseInterceptor`（请求头注入）、`net/APIService`（端点+参数）、`net/*Interceptor`（签名/加密）、`entity/*RequestEntity`（请求体字段）。

Retrofit 注解读取需手工解析 `annotations_directory_item`（androguard 高层 API 不暴露，见 docs/ANALYSIS.md）。

### Phase 4: 2API 交付

- `demo_server.py`：ThreadingHTTPServer + 上游透传（含鉴权头注入）+ 全局限速闸（防上游 throttle）+ 429 自动重试 + 内嵌中文 demo 页
- `stress_test.py`：health / 透传 / 错误路径 / 并发任务 / 登录链路 8 场景
- 端口约定：8902/8907/8911/8913（按项目分配，避免冲突）

## 检查清单

- [ ] 域名面提取并过滤 SDK 噪音
- [ ] TLS 指纹问题确认（curl 拒握时换 Python ssl）
- [ ] 全局中间件 header 破解
- [ ] 错误码分层定位参数结构
- [ ] 上游限流模型确认（阈值+窗口）
- [ ] 鉴权 token 获取路径明确（短信/OAuth/设备注册）
- [ ] demo server 有限速闸与 429 重试
- [ ] 压测 8 场景全 PASS
- [ ] ICM 记忆沉淀（协议+坑+交付路径）

## 常见登录墙与突破优先级

1. **短信验证码**：send/code 真实下发 → 需真实手机号（唯一可靠通道）
2. **设备注册**：device_id 任意伪造可绕（参考 imagerator/miricanvas 案例）
3. **OEM 运营商一键登录**：不可伪造
4. **微信 OAuth**：需运行时环境，不可行
