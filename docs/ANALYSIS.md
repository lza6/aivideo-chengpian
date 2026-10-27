# 逆向分析记录 — AI视频智能成片

时间线、证据链与踩坑记录（供后续同类任务复用）。

## 分析路径

1. **静态侦察**（无需反编译即可获得大半协议面）
   - `unzip` 解包 → `assets/` 内业务配置 JSON（HomeCaseEntity.json 暴露 COS 资源域名与案例结构）
   - `grep -aohE "https?://..." classes*.dex` → 域名面：过滤 SDK 噪音后剩 `aivdapi.gaokaozhiy.net` / `aifx.gaokaozhiy.net` / `yumao.puata.info`
   - Python 脚本按正则从 dex 字符串表提取 `api/xxx` 路径 → 直接命中全部业务端点

2. **黑盒探测**（Python raw socket，绕 curl schannel TLS 指纹拒握）
   - 域名解析正常但 curl 失败 → 换 Python `ssl` + `User-Agent: okhttp/4.9.3` 立即 200
   - Laravel 特征：405 响应回显全部支持方法（端点确认利器）、`XSRF-TOKEN`/`laravel_session` cookie
   - **全局中间件爆破**：逐个候选 header 试 → `appVersion` 任意值通过（否则 4040 版本号不存在）
   - **错误码分层定位**：403 无权/4004 验证码错/4005 参数错 → 反推请求体字段名（如 `code` 传 6 位数字才从 4005 变 4004，证明字段结构正确）

3. **源码级还原**（androguard，因 jadx 卡死）
   - `Lcom/hotwind/aisvideo/net/BaseInterceptor;` 反汇编 → 完整请求头注入逻辑（appVersion/devicePlatform/channelName/phoneType/token）
   - `Lcom/hotwind/aisvideo/net/APIService;` 方法签名 → 18 个端点与参数类型（Map/FormUrlEncoded/Multipart/JSON 实体）
   - Kotlin data class 字段直接读 → 生成请求体结构（prompt/frames/req_key/seed/aspect_ratio）
   - 手工解析 dex `annotations_directory_item`（androguard 高层 API 不暴露）→ Retrofit POST/GET/Multipart 注解

## 踩坑记录

| 坑 | 解法 |
|---|---|
| jadx 反编译 8k+ 类卡死（CPU 归零，磁盘缓存锁死锁） | 放弃 jadx，androguard 3.3.5 单 dex 加载（business.dex 仅 510 个 hotwind 类）秒级完成 |
| 业务 dex 定位 | 按 `dex 中 hotwind 出现次数` 找：classes2.dex 510 次 → 即业务 dex |
| curl TLS 握手失败误判"上游已死" | 先 nslookup 确认解析 → Python ssl 测试 → 实为 TLS 指纹拦截 |
| nginx 400 vs 上游 500 | 400=nginx 拒绝 header 特殊字符；500=Laravel token 解码炸 — 两种现象都说明 header 名正确 |
| 上游 throttle 误判"服务不稳定" | 16 并发全灭 + 单请求复现 `Too Many Attempts.` → 明确是 Laravel 按接口+IP 限流，60s 窗口 |

## 工具备忘

- androguard 反汇编关键类：`AnalyzeDex(path)` → `d.get_classes()` 按 `get_name()` 过滤 → `m.get_instructions()` 的 `get_output()` 逐条打印（const-string/invoke 全可见）
- Retrofit 注解需手工解析 `annotations_directory_item`（struct: class_annotations_off + field/method/param sizes；annotation_item: visibility u8 + uleb type_idx + uleb size + encoded values）
- dex 头固定偏移：string_ids @56, type_ids @64（u32 size + u32 offset 各一对）
