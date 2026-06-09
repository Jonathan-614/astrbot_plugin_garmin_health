"""
Garmin Health - LLM 工具链（10个 FunctionTool）
供大模型通过自然语言调用，查询 Garmin Connect 健康与运动数据
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent
from astrbot.api import FunctionTool

from .client_manager import GarminClientManager, _today_str, _format_duration


# ════════════════════════════════════════════
# 工具 1：今日健康概览
# ════════════════════════════════════════════

@dataclass
class GarminHealthTodayTool(FunctionTool):
    """今日健康概览"""

    client_manager: GarminClientManager = None
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
        try:
            client = await self.client_manager.get_client()
        except Exception as e:
            return f"❌ Garmin连接失败: {e}"

        try:
            today = _today_str()
            stats = client.get_stats(today)
            heart_rate = client.get_heart_rates(today)
            sleep_data = client.get_sleep_data(today)

            total_steps = stats.get("totalSteps", "N/A")
            total_distance = stats.get("totalDistance", "N/A")
            dist_km = round(total_distance / 1000, 2) if isinstance(total_distance, (int, float)) else "N/A"
            active_calories = stats.get("activeKilocalories", "N/A")
            total_calories = stats.get("totalKilocalories", "N/A")

            hr_stats = heart_rate.get("heartRateValues", [])
            hr_values = [h[1] for h in hr_stats if h[1] and h[1] > 30]
            if hr_values:
                avg_hr = round(sum(hr_values) / len(hr_values))
                max_hr = max(hr_values)
                min_hr = min(hr_values)
            else:
                avg_hr = max_hr = min_hr = "N/A"

            daily_sleep = sleep_data.get("dailySleepDTO", {})
            sleep_time_secs = daily_sleep.get("sleepTimeSeconds") or 0
            sleep_hours = round(sleep_time_secs / 3600, 1) if sleep_time_secs else "N/A"
            sleep_score = daily_sleep.get("sleepScores", {}).get("overall", {}).get("value", "N/A")
            deep_sleep = round((daily_sleep.get("deepSleepSeconds") or 0) / 60, 1)
            light_sleep = round((daily_sleep.get("lightSleepSeconds") or 0) / 60, 1)
            rem_sleep = round((daily_sleep.get("remSleepSeconds") or 0) / 60, 1)

            return (
                f"📊 今日健康概览 ({today})\n"
                f"━━━━━━━━━━━━━━\n"
                f"👣 步数: {total_steps} 步 | {dist_km} km\n"
                f"🔥 卡路里: {active_calories}/{total_calories} kcal\n"
                f"💓 心率: avg {avg_hr} / max {max_hr} / min {min_hr} bpm\n"
                f"😴 睡眠: {sleep_hours}h (评分{sleep_score})\n"
                f"   深睡{deep_sleep}min / 浅睡{light_sleep}min / REM{rem_sleep}min"
            )
        except Exception as e:
            logger.error(f"获取健康概览失败: {e}", exc_info=True)
            return f"❌ 获取数据失败: {e}"


# ════════════════════════════════════════════
# 工具 2：心率趋势
# ════════════════════════════════════════════

@dataclass
class GarminHeartRateTool(FunctionTool):
    """心率趋势查询"""

    client_manager: GarminClientManager = None
    name: str = "garmin_heart_rate"
    description: str = (
        "查询心率趋势数据，支持指定天数（默认7天）。"
        "适合问「最近心率怎么样」「心率趋势」「心跳数据」等。"
    )
    parameters: dict = field(default_factory=lambda: {
        "type": "object",
        "properties": {
            "days": {
                "type": "integer",
                "description": "查询天数，默认7天",
            },
        },
        "required": [],
    })

    async def run(self, event: AstrMessageEvent, days: Optional[int] = 7) -> str:
        try:
            client = await self.client_manager.get_client()
        except Exception as e:
            return f"❌ Garmin连接失败: {e}"

        try:
            lines = [f"💓 最近{days}天心率趋势", "━━━━━━━━━━━━━━"]
            for i in range(min(days, 30)):
                day = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
                hr_data = client.get_heart_rates(day)
                hr_vals = [h[1] for h in hr_data.get("heartRateValues", []) if h[1] and h[1] > 30]
                if hr_vals:
                    avg = round(sum(hr_vals) / len(hr_vals))
                    mx = max(hr_vals)
                    mn = min(hr_vals)
                    lines.append(f"{day}: avg {avg} / max {mx} / min {mn} bpm")
                else:
                    lines.append(f"{day}: 无数据")
            return "\n".join(lines)
        except Exception as e:
            return f"❌ 获取心率数据失败: {e}"


# ════════════════════════════════════════════
# 工具 3：睡眠报告
# ════════════════════════════════════════════

@dataclass
class GarminSleepTool(FunctionTool):
    """睡眠报告查询"""

    client_manager: GarminClientManager = None
    name: str = "garmin_sleep"
    description: str = (
        "查询睡眠报告，支持指定天数（默认7天）。"
        "适合问「最近睡眠怎么样」「睡眠质量」「睡得好吗」等。"
    )
    parameters: dict = field(default_factory=lambda: {
        "type": "object",
        "properties": {
            "days": {
                "type": "integer",
                "description": "查询天数，默认7天",
            },
        },
        "required": [],
    })

    async def run(self, event: AstrMessageEvent, days: Optional[int] = 7) -> str:
        try:
            client = await self.client_manager.get_client()
        except Exception as e:
            return f"❌ Garmin连接失败: {e}"

        try:
            lines = [f"😴 最近{days}天睡眠报告", "━━━━━━━━━━━━━━"]
            for i in range(min(days, 30)):
                day = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
                sleep_data = client.get_sleep_data(day)
                daily = sleep_data.get("dailySleepDTO", {})
                sleep_secs = daily.get("sleepTimeSeconds") or 0
                hours = round(sleep_secs / 3600, 1) if sleep_secs else "N/A"
                score = daily.get("sleepScores", {}).get("overall", {}).get("value", "N/A")
                deep = round((daily.get("deepSleepSeconds") or 0) / 60, 1)
                light = round((daily.get("lightSleepSeconds") or 0) / 60, 1)
                rem = round((daily.get("remSleepSeconds") or 0) / 60, 1)
                lines.append(f"{day}: {hours}h 评分{score} (深{deep}/浅{light}/REM{rem}min)")
            return "\n".join(lines)
        except Exception as e:
            return f"❌ 获取睡眠数据失败: {e}"


# ════════════════════════════════════════════
# 工具 4：步数数据
# ════════════════════════════════════════════

@dataclass
class GarminStepsTool(FunctionTool):
    """步数数据查询"""

    client_manager: GarminClientManager = None
    name: str = "garmin_steps"
    description: str = (
        "查询步数数据，支持指定天数（默认7天）。"
        "适合问「最近走多少步」「步数统计」「今天走了多少」等。"
    )
    parameters: dict = field(default_factory=lambda: {
        "type": "object",
        "properties": {
            "days": {
                "type": "integer",
                "description": "查询天数，默认7天",
            },
        },
        "required": [],
    })

    async def run(self, event: AstrMessageEvent, days: Optional[int] = 7) -> str:
        try:
            client = await self.client_manager.get_client()
        except Exception as e:
            return f"❌ Garmin连接失败: {e}"

        try:
            lines = [f"👣 最近{days}天步数报告", "━━━━━━━━━━━━━━"]
            for i in range(min(days, 30)):
                day = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
                stats = client.get_stats(day)
                steps = stats.get("totalSteps", "N/A")
                dist = stats.get("totalDistance", 0)
                dist_km = round(dist / 1000, 2) if isinstance(dist, (int, float)) else "N/A"
                cal = stats.get("activeKilocalories", "N/A")
                lines.append(f"{day}: {steps}步 / {dist_km}km / {cal}kcal")
            return "\n".join(lines)
        except Exception as e:
            return f"❌ 获取步数数据失败: {e}"


# ════════════════════════════════════════════
# 工具 5：综合健康诊断报告
# ════════════════════════════════════════════

@dataclass
class GarminDetailedReportTool(FunctionTool):
    """综合健康诊断报告"""

    client_manager: GarminClientManager = None
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
        try:
            client = await self.client_manager.get_client()
        except Exception as e:
            return f"❌ Garmin连接失败: {e}"

        try:
            report_lines = ["📋 Garmin 综合健康报告", "━━━━━━━━━━━━━━"]
            today = _today_str()

            stats = client.get_stats(today)
            hr_data = client.get_heart_rates(today)
            sleep_data = client.get_sleep_data(today)

            steps = stats.get("totalSteps", "N/A")
            dist = round(stats.get("totalDistance", 0) / 1000, 2)
            cal = stats.get("activeKilocalories", "N/A")
            report_lines.append(f"📅 今日 ({today})")
            report_lines.append(f"  👣 步数: {steps}步 | {dist}km | {cal}kcal")

            hr_vals = [h[1] for h in hr_data.get("heartRateValues", []) if h[1] and h[1] > 30]
            if hr_vals:
                avg_hr = round(sum(hr_vals) / len(hr_vals))
                max_hr = max(hr_vals)
                min_hr = min(hr_vals)
                report_lines.append(f"  💓 心率: avg{avg_hr}/max{max_hr}/min{min_hr}bpm")
            else:
                report_lines.append("  💓 心率: 暂无数据")

            daily_sleep = sleep_data.get("dailySleepDTO", {})
            sleep_hours = round((daily_sleep.get("sleepTimeSeconds") or 0) / 3600, 1)
            sleep_score = daily_sleep.get("sleepScores", {}).get("overall", {}).get("value", "N/A")
            report_lines.append(f"  😴 睡眠: {sleep_hours}h (评分{sleep_score})")

            report_lines.append("")
            report_lines.append("📊 7天平均数据")
            total_steps_7d = []
            total_sleep_7d = []

            for i in range(7):
                day = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
                try:
                    s = client.get_stats(day)
                    total_steps_7d.append(s.get("totalSteps", 0) or 0)
                    sd = client.get_sleep_data(day)
                    sleep_secs = sd.get("dailySleepDTO", {}).get("sleepTimeSeconds") or 0
                    if sleep_secs:
                        total_sleep_7d.append(sleep_secs)
                except Exception:
                    continue

            avg_steps = round(sum(total_steps_7d) / len(total_steps_7d)) if total_steps_7d else "N/A"
            avg_sleep_h = round(sum(total_sleep_7d) / len(total_sleep_7d) / 3600, 1) if total_sleep_7d else "N/A"
            report_lines.append(f"  👣 日均步数: {avg_steps}")
            report_lines.append(f"  😴 日均睡眠: {avg_sleep_h}h")

            report_lines.append("")
            report_lines.append("💡 健康小贴士")
            tips = []
            if isinstance(avg_steps, int) and avg_steps < 8000:
                tips.append("🔸 日均步数偏少，建议多走动")
            elif isinstance(avg_steps, int) and avg_steps >= 10000:
                tips.append("✅ 步数达标，继续保持")
            if isinstance(avg_sleep_h, float) and avg_sleep_h < 7:
                tips.append("🔸 睡眠不足7小时，建议早睡")
            elif isinstance(avg_sleep_h, float) and avg_sleep_h >= 8:
                tips.append("✅ 睡眠充足，状态不错")
            if isinstance(sleep_score, (int, float)) and sleep_score < 70:
                tips.append("🔸 睡眠质量偏低，注意改善睡眠环境")
            report_lines.extend(tips if tips else ["✅ 整体状态良好，继续保持"])

            return "\n".join(report_lines)
        except Exception as e:
            logger.error(f"生成综合报告失败: {e}", exc_info=True)
            return f"❌ 生成报告失败: {e}"


# ════════════════════════════════════════════
# 工具 6：查询活动
# ════════════════════════════════════════════

@dataclass
class GarminQueryActivitiesTool(FunctionTool):
    """查询活动"""

    client_manager: GarminClientManager = None
    name: str = "garmin_query_activities"
    description: str = (
        "查询活动记录，支持按日期范围、活动名称关键词、活动类型筛选。"
        "适合问「最近的活动」「梧桐山活动」「昨天跑了什么」「跑步记录」等。"
    )
    parameters: dict = field(default_factory=lambda: {
        "type": "object",
        "properties": {
            "keyword": {
                "type": "string",
                "description": "活动名称关键词，如「梧桐山」「晨跑」",
            },
            "start_date": {
                "type": "string",
                "description": "起始日期，格式 YYYY-MM-DD",
            },
            "end_date": {
                "type": "string",
                "description": "结束日期，格式 YYYY-MM-DD",
            },
            "activity_type": {
                "type": "string",
                "description": "活动类型，如 running, hiking, walking, cycling, swimming, trail_running",
            },
            "limit": {
                "type": "integer",
                "description": "返回条数上限，默认10，最大200",
            },
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
            client = await self.client_manager.get_client()
        except Exception as e:
            return f"❌ Garmin连接失败: {e}"

        try:
            activities = client.get_activities(0, 200)
            if not activities:
                return "❌ 暂无活动数据"

            matched = []
            for act in activities:
                act_type = act.get("activityType", {}).get("typeKey", "")
                act_name = (act.get("activityName", "") or "")
                date_str = (act.get("startTimeLocal", "") or "")[:10]

                if activity_type and act_type != activity_type:
                    continue
                if keyword and keyword.lower() not in act_name.lower():
                    continue
                if start_date and date_str < start_date:
                    continue
                if end_date and date_str > end_date:
                    continue

                matched.append(act)

            if not matched:
                return "🔍 未找到匹配的活动"

            n = min(limit, 200)
            matched = matched[:n]

            lines = [f"🔍 共找到{len(matched)}条活动", "━━━━━━━━━━━━━━"]
            for i, act in enumerate(matched, 1):
                act_type = act.get("activityType", {}).get("typeKey", "未知")
                act_name = (act.get("activityName", "无名称") or "")[:18]
                start_time = act.get("startTimeLocal", "")
                date_str = start_time[:10] if start_time else "未知日期"
                distance = (act.get("distance", 0) or 0) / 1000
                duration = act.get("duration", 0) or 0
                elev = act.get("elevationGain", 0) or 0

                line = f"\n#{i} [{act_type}] {act_name}"
                line += f"\n  📅 {date_str} | 📏 {distance:.2f}km | ⏱ {_format_duration(duration)}"
                if elev:
                    line += f" | ⛰ {round(elev)}m"
                lines.append(line)

            return "\n".join(lines)
        except Exception as e:
            logger.error(f"查询活动失败: {e}", exc_info=True)
            return f"❌ 查询失败: {e}"


# ════════════════════════════════════════════
# 工具 7：跑量统计
# ════════════════════════════════════════════

@dataclass
class GarminRunningVolumeTool(FunctionTool):
    """跑量统计"""

    client_manager: GarminClientManager = None
    name: str = "garmin_running_volume"
    description: str = (
        "查询跑量统计，含路跑和越野跑，支持按时间范围筛选。"
        "适合问「这个月跑了多少」「跑量统计」「今年跑量」「最近跑步情况」等。"
    )
    parameters: dict = field(default_factory=lambda: {
        "type": "object",
        "properties": {
            "start_date": {
                "type": "string",
                "description": "起始日期，格式 YYYY-MM-DD，默认近7天",
            },
            "end_date": {
                "type": "string",
                "description": "结束日期，格式 YYYY-MM-DD",
            },
        },
        "required": [],
    })

    async def run(
        self, event: AstrMessageEvent,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> str:
        try:
            client = await self.client_manager.get_client()
        except Exception as e:
            return f"❌ Garmin连接失败: {e}"

        try:
            if not start_date:
                start_date = (datetime.now() - timedelta(days=6)).strftime("%Y-%m-%d")
            if not end_date:
                end_date = _today_str()

            activities = client.get_activities(0, 200)
            if not activities:
                return "❌ 暂无活动数据"

            road = {"dist": 0.0, "count": 0, "elev": 0.0, "duration": 0.0}
            trail = {"dist": 0.0, "count": 0, "elev": 0.0, "duration": 0.0}

            for act in activities:
                act_type = act.get("activityType", {}).get("typeKey", "")
                if act_type not in ("running", "trail_running"):
                    continue
                date_str = (act.get("startTimeLocal", "") or "")[:10]
                if date_str < start_date or date_str > end_date:
                    continue
                dist = (act.get("distance", 0) or 0) / 1000
                elev = act.get("elevationGain", 0) or 0
                duration = (act.get("duration", 0) or 0) / 3600

                target = road if act_type == "running" else trail
                target["dist"] += dist
                target["count"] += 1
                target["elev"] += elev
                target["duration"] += duration

            if road["count"] == 0 and trail["count"] == 0:
                return f"📅 {start_date} ~ {end_date}\n━━━━━━━━━━━━━━\n暂无跑步记录"

            combined_dist = road["dist"] + trail["dist"]
            combined_cnt = road["count"] + trail["count"]
            combined_elev = road["elev"] + trail["elev"]
            combined_dur = road["duration"] + trail["duration"]

            lines = [
                f"📊 跑量统计 ({start_date} ~ {end_date})",
                "━━━━━━━━━━━━━━",
                f"🏃 路跑: {road['dist']:.2f}km ({road['count']}次)",
                f"   ⛰爬升{round(road['elev'])}m ⏱{round(road['duration'], 1)}h",
                f"🏔 越野跑: {trail['dist']:.2f}km ({trail['count']}次)",
                f"   ⛰爬升{round(trail['elev'])}m ⏱{round(trail['duration'], 1)}h",
                "───",
                f"📌 合计: {combined_dist:.2f}km ({combined_cnt}次)",
                f"   ⛰爬升{round(combined_elev)}m ⏱{round(combined_dur, 1)}h",
            ]
            if combined_cnt > 0:
                lines.append(f"   📏均次{combined_dist/combined_cnt:.2f}km")

            return "\n".join(lines)
        except Exception as e:
            logger.error(f"跑量统计失败: {e}", exc_info=True)
            return f"❌ 跑量统计失败: {e}"


# ════════════════════════════════════════════
# 工具 8：个人最佳记录
# ════════════════════════════════════════════

@dataclass
class GarminPersonalBestTool(FunctionTool):
    """个人最佳记录"""

    client_manager: GarminClientManager = None
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
        try:
            client = await self.client_manager.get_client()
        except Exception as e:
            return f"❌ Garmin连接失败: {e}"

        try:
            activities = client.get_activities(0, 200)
            if not activities:
                return "❌ 暂无活动数据"

            max_dist = max_pace_val = max_elev = max_dur = 0.0
            max_dist_info = max_pace_info = max_elev_info = max_dur_info = ("", "")

            for act in activities:
                dist = (act.get("distance", 0) or 0) / 1000
                duration = act.get("duration", 0) or 0
                elev = act.get("elevationGain", 0) or 0
                speed = act.get("averageSpeed", 0) or 0
                name = (act.get("activityName", "无名称") or "")[:15]
                date = (act.get("startTimeLocal", "") or "")[:10]

                if dist > max_dist:
                    max_dist = dist
                    max_dist_info = (date, name)
                if speed > 0:
                    pace = 1000 / speed / 60
                    if max_pace_val == 0 or pace < max_pace_val:
                        max_pace_val = pace
                        max_pace_info = (date, name)
                if elev > max_elev:
                    max_elev = elev
                    max_elev_info = (date, name)
                dur_h = duration / 3600
                if dur_h > max_dur:
                    max_dur = dur_h
                    max_dur_info = (date, name)

            pace_str = f"{max_pace_val:.2f}min/km" if max_pace_val > 0 else "N/A"

            return (
                f"🏆 个人最佳记录\n"
                f"━━━━━━━━━━━━━━\n"
                f"📏 最长距离: {max_dist:.2f}km\n"
                f"   ↳ {max_dist_info[0]} {max_dist_info[1]}\n"
                f"🏃 最快配速: {pace_str}\n"
                f"   ↳ {max_pace_info[0]} {max_pace_info[1]}\n"
                f"⛰ 最大爬升: {round(max_elev)}m\n"
                f"   ↳ {max_elev_info[0]} {max_elev_info[1]}\n"
                f"⏱ 最长时长: {round(max_dur, 1)}h\n"
                f"   ↳ {max_dur_info[0]} {max_dur_info[1]}"
            )
        except Exception as e:
            logger.error(f"PB统计失败: {e}", exc_info=True)
            return f"❌ PB统计失败: {e}"


# ════════════════════════════════════════════
# 工具 9：年度运动报告
# ════════════════════════════════════════════

@dataclass
class GarminYearlyReportTool(FunctionTool):
    """年度运动报告（仅支持单年）"""

    client_manager: GarminClientManager = None
    name: str = "garmin_yearly_report"
    description: str = (
        "查询指定年份的年度运动报告，含总活动次数、总距离、总时长、总爬升、总消耗、均次距离和月度分布。"
        "只支持单年查询，不支持跨年。不传参数时默认今年。"
        "适合问「年度报告」「2024年运动总结」「2025年运动总结」等。"
    )
    parameters: dict = field(default_factory=lambda: {
        "type": "object",
        "properties": {
            "year": {
                "type": "integer",
                "description": "年份，例如 2025。不传则默认为今年。",
            },
        },
        "required": [],
    })

    async def run(self, event: AstrMessageEvent, year: Optional[int] = None) -> str:
        try:
            client = await self.client_manager.get_client()
        except Exception as e:
            return f"❌ Garmin 连接失败: {e}"

        try:
            now_year = datetime.now().year
            target_year = year if year is not None else now_year

            activities = client.get_activities(0, 200)
            if not activities:
                return "❌ 暂无活动数据"

            period_start = f"{target_year}-01-01"
            period_end = f"{target_year}-12-31"

            total_dist = total_dur = total_elev = total_cal = 0.0
            count = 0
            monthly = {m: 0.0 for m in range(1, 13)}

            for act in activities:
                date_str = (act.get("startTimeLocal", "") or "")[:10]
                if period_start <= date_str <= period_end:
                    dist = (act.get("distance", 0) or 0) / 1000
                    total_dist += dist
                    total_dur += (act.get("duration", 0) or 0) / 3600
                    total_elev += act.get("elevationGain", 0) or 0
                    total_cal += act.get("calories", 0) or 0
                    count += 1
                    monthly[int(date_str[5:7])] += dist

            if count == 0:
                return f"📅 {target_year}年暂无可统计的活动"

            month_lines = [f"  {m}月: {monthly[m]:.1f}km" for m in range(1, 13) if monthly[m] > 0]

            return (
                f"📅 {target_year}年运动报告\n"
                f"━━━━━━━━━━━━━━\n"
                f"🏃 总活动: {count}次\n"
                f"📏 总距离: {total_dist:.2f}km\n"
                f"⏱ 总时长: {round(total_dur, 1)}h\n"
                f"⛰ 总爬升: {round(total_elev)}m\n"
                f"🔥 总消耗: {round(total_cal)}kcal\n"
                f"📊 均次距离: {round(total_dist / count, 2)}km\n"
                f"\n📆 月度分布:\n" + "\n".join(month_lines)
            )
        except Exception as e:
            logger.error(f"年度统计失败: {e}", exc_info=True)
            return f"❌ 年度统计失败: {e}"


# ════════════════════════════════════════════
# 工具 10：修改活动名称
# ════════════════════════════════════════════

@dataclass
class GarminRenameActivityTool(FunctionTool):
    """修改活动名称"""

    client_manager: GarminClientManager = None
    name: str = "garmin_rename_activity"
    description: str = (
        "修改Garmin活动的名称。需要提供活动ID或活动名称关键词来定位活动，以及新的活动名称。"
        "适合问「改活动名」「重命名活动」「把梧桐山改成大南山」等。"
    )
    parameters: dict = field(default_factory=lambda: {
        "type": "object",
        "properties": {
            "activity_id": {
                "type": "string",
                "description": "活动ID，如果知道的话",
            },
            "keyword": {
                "type": "string",
                "description": "活动名称关键词，用于模糊搜索定位活动。与activity_id二选一。",
            },
            "new_name": {
                "type": "string",
                "description": "新的活动名称",
            },
        },
        "required": ["new_name"],
    })

    async def run(
        self, event: AstrMessageEvent,
        new_name: str,
        activity_id: Optional[str] = None,
        keyword: Optional[str] = None,
    ) -> str:
        if not activity_id and not keyword:
            return "❌ 请提供 activity_id 或 keyword 来定位活动"

        try:
            client = await self.client_manager.get_client()
        except Exception as e:
            return f"❌ Garmin连接失败: {e}"

        try:
            if activity_id:
                client.set_activity_name(activity_id, new_name)
                return f"✅ 已将活动 {activity_id} 重命名为「{new_name}」"
            else:
                activities = client.get_activities(0, 50)
                matched = []
                for act in activities:
                    act_name = (act.get("activityName", "") or "")
                    if keyword.lower() in act_name.lower():
                        matched.append(act)

                if not matched:
                    return f"🔍 未找到包含「{keyword}」的活动"

                if len(matched) > 1:
                    names = "\n".join([f"  {a.get('activityId', '?')}: {(a.get('activityName', '') or '')[:20]}" for a in matched[:10]])
                    return f"🔍 找到多个匹配活动，请指定 activity_id：\n{names}"

                act = matched[0]
                act_id = act.get("activityId", "")
                old_name = act.get("activityName", "")
                client.set_activity_name(act_id, new_name)
                return f"✅ 已将「{old_name}」重命名为「{new_name}」"
        except Exception as e:
            logger.error(f"修改活动名失败: {e}", exc_info=True)
            return f"❌ 修改活动名失败: {e}"


# ════════════════════════════════════════════
# 注册所有工具
# ════════════════════════════════════════════

def create_all_tools(client_manager: GarminClientManager) -> list:
    """创建并返回所有 FunctionTool 实例"""
    return [
        GarminHealthTodayTool(client_manager=client_manager),
        GarminHeartRateTool(client_manager=client_manager),
        GarminSleepTool(client_manager=client_manager),
        GarminStepsTool(client_manager=client_manager),
        GarminDetailedReportTool(client_manager=client_manager),
        GarminQueryActivitiesTool(client_manager=client_manager),
        GarminRunningVolumeTool(client_manager=client_manager),
        GarminPersonalBestTool(client_manager=client_manager),
        GarminYearlyReportTool(client_manager=client_manager),
        GarminRenameActivityTool(client_manager=client_manager),
    ]
