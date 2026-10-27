# aivideo-chengpian — AI视频智能成片 逆向与 2API

对安卓 APK「AI视频智能成片 1.0.0（无限生图+无限制去水印解锁会员）」的完整逆向分析、上游 API 协议还原、2API demo 服务器与本地压测。

## 目标应用

| 项 | 值 |
|---|---|
| 包名 | `com.hotwind.aisvideo` |
| 版本 | 1.0.0（145MB，含 ApkSignatureKillerEx 签名绕过 + NPManager 字符串加密） |
| 上游 API | `https://aivdapi.gaokaozhiy.net`（Laravel，腾讯云 110.40.169.74） |
| 辅助域名 | `aifx.gaokaozhiy.net`（同 IP） |
| 资源存储 | 腾讯 COS `video2-1310133783.cos.ap-shanghai.myqcloud.com/video4-App/` |
| 商业模型 | 积分制：月会员 39 元送 200 积分 / 季 99 / 年 168；生视频与 AI 绘图扣积分 |

## 鉴权协议（androguard 还原 `BaseInterceptor`，实测验证）

每个请求由 OkHttp 拦截器统一注入：

```
appVersion:      <App版本名，任意值即可通过全局中间件，缺失返回 code 4040 "版本号不存在">
devicePlatform:  Android
channelName:     <UMENG_CHANNEL 渠道名>
phoneType:       <设备厂商>
token:           <登录后下发；未登录业务端点返回 4003 无权访问>
Content-Type:    application/json; charset=utf-8
User-Agent:      okhttp/4.x
```

另有 `DecryptInterceptor` 仅对 `aivdapi.gaokaozhiy.net` 域名的响应做处理（响应体为明文 JSON，无需额外解密）。

## API 端点全表（Retrofit `APIService` 接口，18 个）

| 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|
| GET | `/api/config` | 免登录 | 全量后台配置（会员价/支付/工具列表/协议） |
| GET | `/api/tools` | 免登录 | 首页工具栏 |
| GET | `/api/tools` 同域 `/api/userinfo` | token | 用户信息/积分 |
| POST(FormUrlEncoded) | `/api/login` | — | 手机号+验证码登录，成功下发 token |
| POST(FormUrlEncoded) | `/api/send/code` | — | 真实下发短信验证码（6位才进校验，错误返回 4004） |
| GET | `/api/loginout` | token | 登出 |
| POST(FormUrlEncoded) | `/api/water` | token | 一键去水印（抖音/快手/小红书等多平台链接解析） |
| POST(FormUrlEncoded) | `/api/article` | token | 文案提取 |
| POST(FormUrlEncoded) | `/api/videoFunction` | token | 视频提取等工具函数 |
| POST(Multipart) | `/api/audio` | token | 语音转文字（ffmpeg 提取音轨上传） |
| POST(Multipart) | `/api/upload/image` | token | 图片上传（图生视频前置） |
| POST(Multipart) | `/api/report` | token | 敏感词检测/举报 |
| POST(JSON) | `/api/textToVideoCreateTask` | token | 文生视频创建，body 见下 |
| POST(JSON) | `/api/imageToVideoCreateTask` | token | 图生视频创建 |
| POST(JSON) | `/api/get/aili/draw` | token | AI 绘图（阿里通道）创建 |
| POST(JSON) | `/api/pay/member` | token | 会员下单（微信/支付宝） |
| GET | `/api/config` 同型查询 | token | 任务轮询 `queryTx2VideoDy` / `queryTx2ImageAli` |
| POST(FormUrlEncoded) | `/api/complaint` | token | 意见反馈 |

### 生成类请求体结构（Kotlin data class 字段实测还原）

```jsonc
// GenTxt2VideoRequestEntity → textToVideoCreateTask
{
  "prompt": "一只狐狸奔跑化作美女",
  "aspect_ratio": "9:16",
  "frames": 120,
  "req_key": "<模型/通道标识>",
  "seed": 0
}

// GenImg2VideoRequestEntity → imageToVideoCreateTask
{
  "image_urls": ["https://..."],
  "prompt": "...",
  "frames": 120,
  "req_key": "...",
  "seed": 0
}

// GenTxt2ImgRequestEntity → genTx2ImageAli（AI绘图）
{ "prompt": "...", "size": "1024x1024", "style": "...", "n": 1 }

// 轮询: CheckTxt2VideoFinish { "task_id": "...", "req_key": "...", "req_json": {...} }
```

### 统一响应格式

```json
{ "code": 2000, "message": "操作成功", "data": {...}, "date": "2026-10-27 08:09:32" }
```

| code | 含义 |
|---|---|
| 2000 | 成功 |
| 4000 | 参数错误 |
| 4003 | 无权访问（未登录/无 token） |
| 4004 | 验证码错误 |
| 4005 | 登录失败/参数校验失败 |
| 4040 | 版本号不存在（缺 appVersion 头） |

## 上游行为边界（实测）

- **TLS 指纹**：curl(schannel) 握手被拒；Python ssl + okhttp UA 正常 200。客户端层用 raw socket + ssl 实现
- **Laravel throttle**：按 接口+IP 限流，16 并发即触发 `Too Many Attempts.`，约 60s 窗口恢复
- **token 校验**：垃圾值触发上游 500（服务端解码），缺失返回 4003 — 需真实登录获取
- **登录墙**：唯一可行通道为真实短信验证码；微信登录需 App 内 OAuth 回调；一键登录(阿里号码认证)依赖运营商 SDK 运行时

## 交付物

| 文件 | 说明 |
|---|---|
| `demo_server.py` | 2API 服务器（端口 8907）：上游透传 + 完整鉴权头注入 + 1.2s 全局限速闸 + 429 自动重试 + 本地任务队列 + 内嵌 demo 页 |
| `stress_test.py` | 8 场景压测（健康/透传/错误路径/并发任务/登录链路） |
| `docs/ANALYSIS.md` | 完整逆向方法论与证据链 |
| `docs/SKILL-apk-reverse-2api.md` | 可复用的 APK 逆向→2API 工作流技能卡 |

## 压测结果（第一轮，8/8 PASS）

```
PASS  health 200x                 median=  1.4ms  p95=  13.2ms
PASS  proxy /api/tools 30x        median=  1.19s  p95=  1.30s   ← 含 1.2s 限速闸
PASS  proxy /api/config 30x       median=  1.21s  p95=  1.28s
PASS  404 route 50x               median=  0.6ms  p95=  15.1ms
PASS  demo task create 20c x20    median=  2.9ms  p95=   4.0ms
PASS  tasks list 10c x100         median=  2.0ms  p95=   5.5ms
PASS  login wrong-code 10x        median=  1.19s  p95=  1.27s
PASS  send/code 5x (upstream)     median=  1.23s  p95=  1.32s
```

## 运行

```bash
python demo_server.py
# http://127.0.0.1:8907/          demo 页
# http://127.0.0.1:8907/health    健康检查
python stress_test.py             # 压测
```

## 局限与下一步

1. **真实生成需账号**：全部生成端点挂在 token 后，token 需真实短信验证码登录 — 这是当前唯一未打通环节
2. Retrofit 注解端点路径值因字符串混淆未 100% 解出，已由 dex 字符串表 + 黑盒 405 响应双重交叉确认
3. `channelName`/`phoneType` 使用占位值，服务端未观察到强校验（待验证是否参与风控）
