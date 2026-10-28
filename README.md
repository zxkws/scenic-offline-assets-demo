# 景区车机离线素材管理 Demo

一个可运行的最小示例：**3 个景区 → 各自站点 → 多种素材分类 → 多文件 → SQLite → 发布 JSON → 自动离线同步**。

不是 ZIP。文件按 SHA-256 逐个下载、校验，本地保存于 App 的 `filesDir/scenic/{景区}/files/`；完整景区切换 `active.json` 后才生效。

## 一分钟运行（Python 3.10+，零第三方依赖）

```bash
python3 server.py
```

浏览器打开 **http://127.0.0.1:8765**。首次自动初始化 SQLite 数据库、三景区、五个站点、示例 PNG 和 WAV，分别发布 v1。

### 日常操作：三步就够

1. **选择景区、站点**。
2. **一次选中多个图片、音频或视频**（也可以拖入）。页面自动推荐「景点图片」「讲解音频」「介绍视频」，需要时在每个文件旁改分类或标题。
3. 点击 **「上传 N 个文件并发布」**。系统逐个上传文件，全部成功后只发布一次该景区版本，车机再自动按哈希增量同步。

已有素材旁有「替换」「删除」，操作完成会**自动发布**，不用再跳到另一个区域点发布。多个文件的自动分类和批量上传由网页完成，后端仍沿用简单的单文件上传接口。

**替换现在是原位更新**：通过 `PUT /api/materials/{materialId}?filename=new.mp3` 上传新文件，保留原素材 ID、分类、标题和顺序，不再通过「新增再删除」模拟替换。新版本发布前，车机仍读取上一版素材。若更新失败，旧文件仍保留。

上传途中如果失败，已成功上传的项目会保留为*待发布草稿*，同一页面点击按钮可继续提交剩余文件；**所有文件上传成功前不会自动发布**。分类和原始 JSON 放在页面底部默认收起的「高级设置」里。

### 新增一种素材分类（不需要改代码）

1. 展开 Web 后台的 **「高级设置 · 分类管理与 JSON」**，填写编码 `background_music`、名称「背景音乐」、媒体类型选「音频」，点击「保存分类」。
2. 选择景区 A → 游客中心 → 选择一个 MP3 或 WAV；在新增文件旁的分类下拉框选择「背景音乐」。
3. 点击 **上传并发布**，在 JSON 的 `stations[].categories[]` 中会出现新分类：

```json
{
  "code": "background_music",
  "name": "背景音乐",
  "mediaType": "audio",
  "items": [{"id": "m_...", "title": "车载背景音乐", "fileId": "f_..."}]
}
```

4. 运行 `python3 client.py`，只会下载缺失或变化的文件；Android 会按这个分类动态显示音频播放入口，**不需要为新编码写特殊页面**。

支持修改分类名称、媒体类型、排序；**编码创建后固定**。已被素材引用的分类不能删除；改变媒体类型时也不能与现有文件类型冲突。分类为所有景区共用的定义，但每个景区的站点、素材和发布版本仍独立。新建空分类不会出现在站点的 JSON 中。

分类可选的媒体类型为 `image`、`audio`、`video`，和业务分类编码是两个概念。新业务分类可以直接配置；**新增真正的文件格式或复杂业务播放规则**仍可能需要升级客户端。

公开的示例接口：

```text
GET    /api/scenics
GET    /api/stations?scenicId=A
GET    /api/categories
POST   /api/categories                         (JSON: code,name,mediaType,position?)
PATCH  /api/categories/{code}                  (JSON: name?,mediaType?,position?)
DELETE /api/categories/{code}
GET    /api/materials?stationId=A-S01
POST   /api/materials?stationId=A-S01&categoryCode=gallery&title=xxx&filename=photo.png
PUT    /api/materials/{materialId}?filename=replacement.png
DELETE /api/materials/{materialId}
POST   /api/scenics/A/publish
GET    /api/scenics/A/manifest
GET    /assets/{sha256}.png
```

分类创建/修改接口使用 `Content-Type: application/json`。上传接口的请求体为原始文件字节（`application/octet-stream`），Web 页面已处理；后端会根据分类 `mediaType` 校验上传文件的扩展名所属媒体类型（仅 Demo 级校验，不检查真实内容）。示例文件与 SQLite DB 在 `runtime/` 中，默认不纳入 Git；已发布 JSON 快照位于 `runtime/exports/`。发布后数据库保存不可变的 JSON 快照，未发布的修改对客户端不可见。

**从旧版 Demo 升级：** 保留 `runtime/`，直接运行最新 `server.py`。程序会为旧 `category` 表自动增加 `media_type` 列，并为原有讲解音频、安全播报、景点视频分类补上正确媒体类型，不删除已有素材及发布版本。

## 离线客户端示范

电脑上执行：

```bash
python3 client.py
# 重复执行：输出每个景区 0 files to download
```

目录 `runtime/device/{A,B,C}/active.json` + `files/{sha256}.ext` 是 Android 端目录的模拟。断网时使用已经同步的 `active.json` 和本地文件。修改素材并发布后重跑客户端，仅下载新增的哈希文件。已下载完整但 SHA-256 不匹配的 `.part` 文件会被丢弃并重新下载，避免无限请求无效的 HTTP Range。

## Android 原生 App

用 Android Studio 打开 `android-app/`，构建运行即可。Android 示例（Java，最低 API 26）启动时自动下载所有景区；顶部三个按钮可**切换当前景区**，并记住上一次选择。只展示选中的景区，按 `active.json` 动态展示任意分类、任意数量的素材，并依据文件 `mimeType` 渲染**图片预览、音频播放、视频播放**。断网重开读取本地数据。无需用户点击下载。

例如新增 `background_music` 或 `safety_audio`，Android 不需要硬编码分类名称，而是自动复用音频播放器。这里只演示**手动点击播放预览**，不代表具备到站自动播报、循环、抢占优先级等具体车机业务规则。

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
