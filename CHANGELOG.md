# Changelog

## v1.0.1 (2026-06-10)

### 🏗 重构架构
- `main.py` 拆分为三文件架构：`main.py`（命令路由）+ `services.py`（业务逻辑）+ `utils.py`（工具函数）
- 职责清晰，main.py 只负责命令解析与路由，不再包含业务逻辑

### 🧵 异步改造
- `GarminClientManager` 新增 `call()` 方法，所有 GarminConnect 同步调用经 `asyncio.to_thread` 在线程池串行执行
- 避免同步阻塞 AstrBot 事件循环，并防止并发请求互相踩 session

### 🗂 分页拉取活动
- 新增 `get_activities()` 分页拉取方法，按配置 `garmin_max_activities`（默认 600，最大 10000）拉取
- 解决年度报告（/年度报告）、个人最佳（/PB）和跑量统计漏算的问题

### 🔐 Session 持久化重构
- 从 `garth.load/dump` 迁移到 garminconnect 原生 `tokenstore` 机制
- 自动加载/保存/重试/损坏自动修复，无需手动维护 session 文件

### 🧰 新增工具
- `garmin_activity_volume`：通用活动量统计（徒步/步行/骑行/游泳等非跑步活动）
- 工具总数达到 11 个

### 📅 命令增强
- `/活动` 支持全年（4位年份如 `2026`）、整月（`2026-06` / `2026年6月`）、中文日期（`2026年6月8日`）、斜杠日期（`2026/06/08`）
- 多级智能优先级解析：无参 → 4位年份 → 其他纯数字N条 → 月/日日期 → 活动名模糊搜索
- `/跑量` 等统计命令同步支持中文月和斜杠日期格式

### ✅ 改名确认流程
- `garmin_rename_activity` 新增 `confirm` 参数，需明确确认 `confirm=true` 后才执行改名
- 防止误操作，确保安全

### ⬆ 依赖升级
- `garminconnect>=0.2.19` → `garminconnect>=0.3.3`

### ⚙ 配置项新增
- `garmin_max_activities`：活动分页拉取上限配置，默认 600
