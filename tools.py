"""
Garmin Health - LLM 工具链（11个 FunctionTool）
供大模型通过自然语言调用，查询 Garmin Connect 健康与运动数据

架构：tools.py 只负责参数定义与分发，业务逻辑在 services.py 中。
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent
from astrbot.api import FunctionTool

from .services import (
    health_today_data,
    health_heart_rate_days,
    health_sleep_days,
    health_steps_days,
    detailed_health_report,
    get_filtered_activities,
    build_activity_line,
    activities_report,
    compute_volume,
    build_volume_report,
    personal_best_report,
    yearly_report,
    rename_activity,
)
from .utils import clamp_int, normalize_date_range
from .client_manager import _today_str


# ════════════════════════════════════════════
# 工具 1：今日健康概览
# ════════════════════════════════════════════

@dataclass
class GarminHealthTodayTool(FunctionTool):
    """今日健康概览"""

    client_manager: object = None
    name: str = "garmin_health_today"
    description: str = (
        "查询今日健康概览，包含步数、心率、睡眠等基本信息。"
        "适合问「我今天状态怎么样」「今天健康数据」「今天身体怎么样」等。"
    )
    parameters: dict = field(default_factory=lambda: {
        "type": "object",
        "properties": {},
        "required": [],
    })

    async def run(self, event: AstrMessageEvent) -> str:
        return await health_today_data(self.client_manager)()


# ════════════════════════════════════════════
# 工具 2：心率趋势
# ════════════════════════════════════════════

@dataclass
class GarminHeartRateTool(FunctionTool):
    """心率趋势查询"""

    client_manager: object = None
    name: str = "garmin_heart_rate"
    description: str = (
        "查询心率趋势数据，支持指定天数（默认7天）。"
        "适合问「最近心率怎么样」「心率趋势」「心跳数据」等。"
    )
    parameters: dict = field(default_factory=lambda: {
        "type": "object",
        "properties": {
            "days": {"type": "integer", "description": "查询天数，默认7天"},
        },
        "required": [],
    })

    async def run(self, event: AstrMessageEvent, days: Optional[int] = 7) -> str:
        return await health_heart_rate_days(self.client_manager, days)()


# ════════════════════════════════════════════
# 工具 3：睡眠报告
# ════════════════════════════════════════════

@dataclass
class GarminSleepTool(FunctionTool):
    """睡眠报告查询"""

    client_manager: object = None
    name: str = "garmin_sleep"
    description: str = (
        "查询睡眠报告，支持指定天数（默认7天）。"
        "适合问「最近睡眠怎么样」「睡眠质量」「睡得好吗」等。"
    )
    parameters: dict = field(default_factory=lambda: {
        "type": "object",
        "properties": {
            "days": {"type": "integer", "description": "查询天数，默认7天"},
        },
        "required": [],
    })

    async def run(self, event: AstrMessageEvent, days: Optional[int] = 7) -> str:
        return await health_sleep_days(self.client_manager, days)()


# ════════════════════════════════════════════
# 工具 4：步数数据
# ════════════════════════════════════════════

@dataclass
class GarminStepsTool(FunctionTool):
    """步数数据查询"""

    client_manager: object = None
    name: str = "garmin_steps"
    description: str = (
        "查询步数数据，支持指定天数（默认7天）。"
        "适合问「最近走多少步」「步数统计」「今天走了多少」等。"
    )
    parameters: dict = field(default_factory=lambda: {
        "type": "object",
        "properties": {
            "days": {"type": "integer", "description": "查询天数，默认7天"},
        },
        "required": [],
    })

    async def run(self, event: AstrMessageEvent, days: Optional[int] = 7) -> str:
        return await health_steps_days(self.client_manager, days)()


# ════════════════════════════════════════════
# 工具 5：综合健康诊断报告
# ════════════════════════════════════════════

@dataclass
class GarminDetailedReportTool(FunctionTool):
    """综合健康诊断报告"""

    client_manager: object = None
    name: str = "garmin_detailed_report"
    description: str = (
        "生成综合健康诊断报告，包含今日数据和7天平均，以及健康建议。"
        "适合问「身体报告」「综合健康」「详细报告」「全面体检」等。"
    )
    parameters: dict = field(default_factory=lambda: {
        "type": "object",
        "properties": {},
        "required": [],
    })

    async def run(self, event: AstrMessageEvent) -> str:
        return await detailed_health_report(self.client_manager)()


# ════════════════════════════════════════════
# 工具 6：查询活动
# ════════════════════════════════════════════

@dataclass
class GarminQueryActivitiesTool(FunctionTool):
    """查询活动"""

    client_manager: object = None
    name: str = "garmin_query_activities"
    description: str = (
        "查询活动记录，支持按日期范围、活动名称关键词、活动类型筛选。"
        "适合问「最近的活动」「梧桐山活动」「昨天跑了什么」「跑步记录」等。"
    )
    parameters: dict = field(default_factory=lambda: {
        "type": "object",
        "properties": {
            "keyword": {"type": "string", "description": "活动名称关键词"},
            "start_date": {"type": "string", "description": "起始日期，YYYY-MM-DD、YYYY-MM 或 YYYY"},
            "end_date": {"type": "string", "description": "结束日期，YYYY-MM-DD、YYYY-MM 或 YYYY"},
            "activity_type": {"type": "string", "description": "活动类型，如 running, hiking, walking, cycling, swimming, trail_running"},
            "limit": {"type": "integer", "description": "返回条数上限，默认10，最大200"},
        },
        "required": [],
    })

    async def run(
        self, event: AstrMessageEvent,
        keyword: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        activity_type: Optional[str] = None,
        limit: Optional[int] = 10,
    ) -> str:
        try:
            try:
                start_date, end_date = normalize_date_range(start_date, end_date)
            except ValueError as e:
                return f"❌ {e}"
            limit = clamp_int(limit, 10, 1, 200)

            activities = await get_filtered_activities(
                self.client_manager,
                keyword=keyword,
                start_date=start_date,
                end_date=end_date,
                activity_type=activity_type,
                max_count=limit,
            )()
            if not activities:
                return "🔍 未找到匹配的活动"

            lines = [f"🔍 共找到{len(activities)}条活动", "━━━━━━━━━━━━━━"]
            for i, act in enumerate(activities, 1):
                lines.append(f"\n#{i} {build_activity_line(act)}")
            return "\n".join(lines)
        except Exception as e:
            logger.error(f"查询活动失败: {e}", exc_info=True)
            return f"❌ 查询失败: {e}"


# ════════════════════════════════════════════
# 工具 7：跑步统计
# ════════════════════════════════════════════

@dataclass
class GarminRunningVolumeTool(FunctionTool):
    """跑步统计（九类细分）"""

    client_manager: object = None
    name: str = "garmin_running_volume"
    description: str = (
        "查询跑步统计，分跑步、路跑、场地跑、室内跑、跑步机、虚拟跑、越野跑、超马和障碍跑九类，支持按时间范围筛选。"
        "适合问「这个月跑了多少」「跑量统计」「今年跑量」「最近跑步情况」等。"
    )
    parameters: dict = field(default_factory=lambda: {
        "type": "object",
        "properties": {
            "start_date": {"type": "string", "description": "起始日期，YYYY-MM-DD，默认近7天"},
            "end_date": {"type": "string", "description": "结束日期，YYYY-MM-DD"},
        },
        "required": [],
    })

    async def run(
        self, event: AstrMessageEvent,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> str:
        try:
            try:
                start_date, end_date = normalize_date_range(start_date, end_date)
            except ValueError as e:
                return f"❌ {e}"
            if start_date is None:
                start_date = (datetime.now() - timedelta(days=6)).strftime("%Y-%m-%d")
            if end_date is None:
                end_date = _today_str()

            activities = await self.client_manager.get_activities()
            if not activities:
                return "❌ 暂无活动数据"

            running = compute_volume(activities, {"running"}, start_date, end_date)
            street_run = compute_volume(activities, {"street_running"}, start_date, end_date)
            track_run = compute_volume(activities, {"track_running"}, start_date, end_date)
            indoor_run = compute_volume(activities, {"indoor_running"}, start_date, end_date)
            treadmill = compute_volume(activities, {"treadmill_running"}, start_date, end_date)
            virtual_run = compute_volume(activities, {"virtual_run"}, start_date, end_date)
            trail_run = compute_volume(activities, {"trail_running"}, start_date, end_date)
            ultra_run = compute_volume(activities, {"ultra_run"}, start_date, end_date)
            obstacle = compute_volume(activities, {"obstacle_run"}, start_date, end_date)
            all_zero = all(v["count"] == 0 for v in [running, street_run, track_run, indoor_run, treadmill, virtual_run, trail_run, ultra_run, obstacle])
            if all_zero:
                return f"📅 {start_date} ~ {end_date}\n━━━━━━━━━━━━━━\n暂无跑步记录"

            return build_volume_report("跑步统计", running=running, street_running=street_run, track_running=track_run, indoor_running=indoor_run, treadmill_running=treadmill, virtual_running=virtual_run, trail_running=trail_run, ultra_running=ultra_run, obstacle_racing=obstacle)
        except Exception as e:
            logger.error(f"跑步统计失败: {e}", exc_info=True)
            return f"❌ 跑步统计失败: {e}"


# ════════════════════════════════════════════
# 工具 8：通用活动量统计
# ════════════════════════════════════════════

@dataclass
class GarminActivityVolumeTool(FunctionTool):
    """通用活动量统计"""

    client_manager: object = None
    name: str = "garmin_activity_volume"
    description: str = (
        "查询指定活动类型的运动量统计，支持徒步、步行、骑行、游泳等。"
        "适合问「今年徒步多少」「这个月骑行多少」「最近游泳统计」「步行总量」等。"
    )
    parameters: dict = field(default_factory=lambda: {
        "type": "object",
        "properties": {
            "activity_type": {"type": "string", "description": "活动类型，可填 hiking/walking/cycling/swimming 或 Garmin typeKey"},
            "start_date": {"type": "string", "description": "起始日期，YYYY-MM-DD，默认近7天"},
            "end_date": {"type": "string", "description": "结束日期，YYYY-MM-DD，默认今天"},
        },
        "required": ["activity_type"],
    })

    async def run(
        self, event: AstrMessageEvent,
        activity_type: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> str:
        try:
            aliases = {
                "徒步": {"hiking"},
                "hiking": {"hiking"},
                "步行": {"walking"},
                "walking": {"walking"},
                "walk": {"walking"},
                "骑行": {"cycling"},
                "cycling": {"cycling"},
                "cycle": {"cycling"},
                "游泳": {"swimming", "lap_swimming", "open_water_swimming"},
                "swimming": {"swimming", "lap_swimming", "open_water_swimming"},
                "swim": {"swimming", "lap_swimming", "open_water_swimming"},
            }
            key = (activity_type or "").strip().lower()
            type_keys = aliases.get(key)
            if not type_keys:
                type_keys = {str(activity_type).strip()}
            title = str(activity_type).strip()
            try:
                start_date, end_date = normalize_date_range(start_date, end_date)
            except ValueError as e:
                return f"❌ {e}"
            if start_date is None:
                start_date = (datetime.now() - timedelta(days=6)).strftime("%Y-%m-%d")
            if end_date is None:
                end_date = _today_str()

            activities = await self.client_manager.get_activities()
            if not activities:
                return "❌ 暂无活动数据"

            stats = compute_volume(activities, type_keys, start_date, end_date)
            if stats["count"] == 0:
                return f"📅 {start_date} ~ {end_date}\n━━━━━━━━━━━━━━\n暂无{title}记录"
            return build_volume_report(title, single=stats)
        except Exception as e:
            logger.error(f"活动量统计失败: {e}", exc_info=True)
            return f"❌ 活动量统计失败: {e}"


# ════════════════════════════════════════════
# 工具 9：个人最佳记录
# ════════════════════════════════════════════

@dataclass
class GarminPersonalBestTool(FunctionTool):
    """个人最佳记录"""

    client_manager: object = None
    name: str = "garmin_personal_best"
    description: str = (
        "查询个人最佳记录，含最长距离、最快配速、最大爬升、最长时长。"
        "适合问「我的PB」「个人最佳」「最好成绩」「跑得最好的一次」等。"
    )
    parameters: dict = field(default_factory=lambda: {
        "type": "object",
        "properties": {},
        "required": [],
    })

    async def run(self, event: AstrMessageEvent) -> str:
        return await personal_best_report(self.client_manager)()


# ════════════════════════════════════════════
# 工具 10：年度运动报告
# ════════════════════════════════════════════

@dataclass
class GarminYearlyReportTool(FunctionTool):
    """年度运动报告（仅支持单年）"""

    client_manager: object = None
    name: str = "garmin_yearly_report"
    description: str = (
        "查询指定年份的年度运动报告，含总活动次数、总距离、总时长、总爬升、总消耗、均次距离和月度分布。"
        "只支持单年查询，不支持跨年。不传参数时默认今年。"
        "适合问「年度报告」「2024年运动总结」「2025年运动总结」等。"
    )
    parameters: dict = field(default_factory=lambda: {
        "type": "object",
        "properties": {
            "year": {"type": "integer", "description": "年份，例如 2025。不传则默认为今年。"},
        },
        "required": [],
    })

    async def run(self, event: AstrMessageEvent, year: Optional[int] = None) -> str:
        try:
            now_year = datetime.now().year
            target_year = year if year is not None else now_year
            return await yearly_report(self.client_manager, target_year)()
        except Exception as e:
            logger.error(f"年度报告失败: {e}", exc_info=True)
            return f"❌ 年度报告失败: {e}"


# ════════════════════════════════════════════
# 工具 11：修改活动名称
# ════════════════════════════════════════════

@dataclass
class GarminRenameActivityTool(FunctionTool):
    """修改Garmin活动名称"""

    client_manager: object = None
    name: str = "garmin_rename_activity"
    description: str = (
        "修改Garmin活动的名称。需要提供活动ID或活动名称关键词来定位活动，以及新的活动名称。"
        "适合问「改活动名」「把梧桐山改成梅沙尖」等。"
    )
    parameters: dict = field(default_factory=lambda: {
        "type": "object",
        "properties": {
            "activity_id": {"type": "string", "description": "活动ID，优先匹配"},
            "keyword": {"type": "string", "description": "活动名称关键词，用于模糊搜索"},
            "new_name": {"type": "string", "description": "新的活动名称"},
            "confirm": {"type": "boolean", "description": "是否确认执行重命名"},
        },
        "required": ["new_name"],
    })

    async def run(
        self, event: AstrMessageEvent,
        new_name: str,
        activity_id: Optional[str] = None,
        keyword: Optional[str] = None,
        confirm: Optional[bool] = None,
    ) -> str:
        if not keyword and not activity_id:
            return "❌ 请至少提供 keyword 或 activity_id"
        if not confirm:
            if activity_id:
                return f"⚠️ 请确认重命名活动 {activity_id} 为「{new_name}」，再次发送加上 confirm=true"
            return f"⚠️ 请确认重命名关键词「{keyword}」的活动为「{new_name}」，再次发送加上 confirm=true"
        return await rename_activity(self.client_manager, keyword or "", new_name)()


# ════════════════════════════════════════════
# 工具注册
# ════════════════════════════════════════════

def create_all_tools(client_manager) -> list:
    """创建并返回所有 FunctionTool 实例"""
    return [
        GarminHealthTodayTool(client_manager=client_manager),
        GarminHeartRateTool(client_manager=client_manager),
        GarminSleepTool(client_manager=client_manager),
        GarminStepsTool(client_manager=client_manager),
        GarminDetailedReportTool(client_manager=client_manager),
        GarminQueryActivitiesTool(client_manager=client_manager),
        GarminRunningVolumeTool(client_manager=client_manager),
        GarminActivityVolumeTool(client_manager=client_manager),
        GarminPersonalBestTool(client_manager=client_manager),
        GarminYearlyReportTool(client_manager=client_manager),
        GarminRenameActivityTool(client_manager=client_manager),
    ]
