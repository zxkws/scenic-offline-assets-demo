# 景区车机离线素材管理 Demo

一个可运行的最小示例：**3 个景区 → 各自站点 → 多种素材分类 → 多文件 → SQLite → 发布 JSON → 自动离线同步**。

不是 ZIP。文件按 SHA-256 逐个下载、校验，本地保存于 App 的 `filesDir/scenic/{景区}/files/`；完整景区切换 `active.json` 后才生效。

## 一分钟运行（Python 3.10+，零第三方依赖）

```bash
python3 server.py
```

浏览器打开 **http://127.0.0.1:8765**。首次自动初始化 SQLite 数据库、三景区、五个站点、示例 PNG 和 WAV，分别发布 v1。

后台选择景区、站点、分类，上传图片/音频/视频，随后点击**发布新版本**。可查看生成的 `manifest.json`。

公开的示例接口：

```text
GET    /api/scenics
GET    /api/stations?scenicId=A
GET    /api/categories
GET    /api/materials?stationId=A-S01
POST   /api/materials?stationId=A-S01&categoryCode=gallery&title=xxx&filename=photo.png
DELETE /api/materials/{materialId}
POST   /api/scenics/A/publish
GET    /api/scenics/A/manifest
GET    /assets/{sha256}.png
```

上传接口的请求体为原始文件字节（`application/octet-stream`），Web 页面已处理。示例文件与 SQLite DB 在 `runtime/` 中，默认不纳入 Git；已发布 JSON 快照位于 `runtime/exports/`。发布后数据库保存不可变的 JSON 快照，未发布的修改对客户端不可见。

## 离线客户端示范

电脑上执行：

```bash
python3 client.py
# 重复执行：输出每个景区 0 files to download
```

目录 `runtime/device/{A,B,C}/active.json` + `files/{sha256}.ext` 是 Android 端目录的模拟。断网时使用已经同步的 `active.json` 和本地文件。修改素材并发布后重跑客户端，仅下载新增的哈希文件。

## Android 原生 App

用 Android Studio 打开 `android-app/`，构建运行即可。Android 示例（Java，最低 API 26）启动时自动下载所有景区，显示本地景区、站点与素材标题；断网重开读取本地数据。无需用户点击下载。

- Android 模拟器：默认服务器 `http://10.0.2.2:8765`，后端启动方式不变。
- 实际车机：将 `MainActivity.java` 中的 `BASE` 改为后端可访问的 LAN 地址，服务器用 `python3 server.py --host 0.0.0.0` 在**可信局域网**里启动。
- 车机实际项目应使用 HTTPS、合适的下载任务调度、下载进度/失败重试、网络恢复唤醒和版本切换时机。本 Java 示例仅展示启动同步、SHA 校验、续传及离线读取，不承诺关机时自动下载或周期调度。

## 架构

SQLite 六张表：`scenic`、`station`、`category`、`file`、`station_material`、`release`。

`publish()` 查询站点和关联关系，按站点、分类分组，将每个素材映射到 `fileId`；`files` 集中记录 URL、大小、SHA-256、MIME。每个景区独立版本。相同文件可以被多处引用，不重复下载。

## Demo 边界

**这是教学 Demo，不能直接部署公网生产。** 管理接口没有鉴权、权限隔离或 HTTPS；文件格式只按扩展名识别，不做真正的内容检测；仅支持简单单文件上传，无大文件分块上传和进度上报；也没有数据库并发写入重试、生产日志、设备状态上报和完整的 OTA 调度。公开 GitHub 仓库意味着公开源代码，**并不意味着应把管理服务裸露在公网**。

上线应至少加入管理员登录、景区权限、HTTPS、上传文件校验、限制和限流、对象存储、发布事务/可回滚、Android WorkManager/合适前台任务与定制车机实测。

## 验证

```bash
python3 -m unittest discover -s tests -v
```

示例素材均由 Python 生成，不包含真实景区文件或敏感信息。
