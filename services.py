"""Garmin Health 插件业务逻辑层。

负责所有数据查询、统计计算和报告生成。
main.py 和 tools.py 通过调用这里的函数来工作，避免重复。
"""

from datetime import datetime, timedelta
from typing import Optional
from astrbot.api import logger

from .client_manager import GarminClientManager, _today_str, _format_duration
from .utils import (
    safe_float,
    clamp_int,
    normalize_date_range,
    format_pace,
    pace_from_speed,
    parse_volume_arg,
)


# ─── 健康数据 ──────────────────────────────────────

def health_today_data(client_manager: GarminClientManager) -> str:
    """生成今日健康概览。"""
    async def _run():
        try:
            client = await client_manager.get_client()
            today = _today_str()
            stats = await client_manager.call(client.get_stats, today)
            heart_rate = await client_manager.call(client.get_heart_rates, today)
            sleep_data = await client_manager.call(client.get_sleep_data, today)

            total_steps = stats.get("totalSteps", "N/A")
            total_distance = stats.get("totalDistance", "N/A")
            if total_distance == "N/A" or safe_float(total_distance) <= 0:
                if isinstance(total_steps, (int, float)) and total_steps > 0:
                    dist_km = round(total_steps * 0.7 / 1000, 2)
                else:
                    dist_km = "N/A"
            else:
                dist_km = round(safe_float(total_distance) / 1000, 2)
            active_calories = stats.get("activeKilocalories", "N/A")
            total_calories = stats.get("totalKilocalories", "N/A")

            hr_stats = heart_rate.get("heartRateValues") or []
            hr_values = [h[1] for h in hr_stats if h[1] and h[1] > 30]
            if hr_values:
                avg_hr = round(sum(hr_values) / len(hr_values))
                max_hr = max(hr_values)
                min_hr = min(hr_values)
            else:
                avg_hr = max_hr = min_hr = "N/A"

            daily_sleep = sleep_data.get("dailySleepDTO") or {}
            sleep_time_secs = daily_sleep.get("sleepTimeSeconds") or 0
            sleep_hours = round(sleep_time_secs / 3600, 1) if sleep_time_secs else "N/A"
            sleep_score = ((daily_sleep.get("sleepScores") or {}).get("overall") or {}).get("value", "N/A")
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
    return _run


def health_heart_rate_days(client_manager: GarminClientManager, days: int) -> str:
    """生成 N 天心率趋势。"""
    async def _run():
        try:
            client = await client_manager.get_client()
        except Exception as e:
            return f"❌ Garmin连接失败: {e}"
        ndays = clamp_int(days, 7, 1, 30)
        try:
            lines = [f"💓 最近{ndays}天心率趋势", "━━━━━━━━━━━━━━"]
            for i in range(ndays):
                day = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
                hr_data = await client_manager.call(client.get_heart_rates, day)
                hr_vals = [h[1] for h in (hr_data.get("heartRateValues") or []) if h[1] and h[1] > 30]
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
    return _run


def health_sleep_days(client_manager: GarminClientManager, days: int) -> str:
    """生成 N 天睡眠报告。"""
    async def _run():
        try:
            client = await client_manager.get_client()
        except Exception as e:
            return f"❌ Garmin连接失败: {e}"
        ndays = clamp_int(days, 7, 1, 30)
        try:
            lines = [f"😴 最近{ndays}天睡眠报告", "━━━━━━━━━━━━━━"]
            for i in range(ndays):
                day = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
                sleep_data = await client_manager.call(client.get_sleep_data, day)
                daily = sleep_data.get("dailySleepDTO") or {}
                sleep_secs = daily.get("sleepTimeSeconds") or 0
                hours = round(sleep_secs / 3600, 1) if sleep_secs else "N/A"
                score = ((daily.get("sleepScores") or {}).get("overall") or {}).get("value", "N/A")
                deep = round((daily.get("deepSleepSeconds") or 0) / 60, 1)
                light = round((daily.get("lightSleepSeconds") or 0) / 60, 1)
                rem = round((daily.get("remSleepSeconds") or 0) / 60, 1)
                lines.append(f"{day}: {hours}h 评分{score} (深{deep}/浅{light}/REM{rem}min)")
            return "\n".join(lines)
        except Exception as e:
            return f"❌ 获取睡眠数据失败: {e}"
    return _run


def health_steps_days(client_manager: GarminClientManager, days: int) -> str:
    """生成 N 天步数报告。"""
    async def _run():
        try:
            client = await client_manager.get_client()
        except Exception as e:
            return f"❌ Garmin连接失败: {e}"
        ndays = clamp_int(days, 7, 1, 30)
        try:
            lines = [f"👣 最近{ndays}天步数报告", "━━━━━━━━━━━━━━"]
            for i in range(ndays):
                day = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
                stats = await client_manager.call(client.get_stats, day)
                steps = stats.get("totalSteps", "N/A")
                dist = safe_float(stats.get("totalDistance", 0))
                if dist <= 0 and isinstance(steps, (int, float)) and steps > 0:
                    dist = steps * 0.7
                dist_km = round(dist / 1000, 2)
                cal = stats.get("activeKilocalories", "N/A")
                lines.append(f"{day}: {steps}步 / {dist_km}km / {cal}kcal")
            return "\n".join(lines)
        except Exception as e:
            return f"❌ 获取步数数据失败: {e}"
    return _run


def detailed_health_report(client_manager: GarminClientManager) -> str:
    """综合健康诊断报告。"""
    async def _run():
        try:
            client = await client_manager.get_client()
        except Exception as e:
            return f"❌ Garmin连接失败: {e}"
        try:
            report_lines = ["📋 Garmin 综合健康报告", "━━━━━━━━━━━━━━"]
            today = _today_str()

            stats = await client_manager.call(client.get_stats, today)
            hr_data = await client_manager.call(client.get_heart_rates, today)
            sleep_data = await client_manager.call(client.get_sleep_data, today)

            steps = stats.get("totalSteps", "N/A")
            raw_dist = stats.get("totalDistance", "N/A")
            if raw_dist == "N/A" or safe_float(raw_dist) <= 0:
                if isinstance(steps, (int, float)) and steps > 0:
                    dist = round(steps * 0.7 / 1000, 2)
                else:
                    dist = "N/A"
            else:
                dist = round(safe_float(raw_dist) / 1000, 2)
            cal = stats.get("activeKilocalories", "N/A")
            report_lines.append(f"📅 今日 ({today})")
            report_lines.append(f"  👣 步数: {steps}步 | {dist}km | {cal}kcal")

            hr_vals = [h[1] for h in (hr_data.get("heartRateValues") or []) if h[1] and h[1] > 30]
            if hr_vals:
                avg_hr = round(sum(hr_vals) / len(hr_vals))
                max_hr = max(hr_vals)
                min_hr = min(hr_vals)
                report_lines.append(f"  💓 心率: avg{avg_hr}/max{max_hr}/min{min_hr}bpm")
            else:
                report_lines.append("  💓 心率: 暂无数据")

            daily_sleep = sleep_data.get("dailySleepDTO") or {}
            sleep_hours = round((daily_sleep.get("sleepTimeSeconds") or 0) / 3600, 1)
            sleep_score = ((daily_sleep.get("sleepScores") or {}).get("overall") or {}).get("value", "N/A")
            report_lines.append(f"  😴 睡眠: {sleep_hours}h (评分{sleep_score})")

            # 7 天平均
            total_steps_7d, total_sleep_7d = [], []
            for i in range(1, 7):
                day = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
                stats_7d = await client_manager.call(client.get_stats, day)
                hr_7d = await client_manager.call(client.get_heart_rates, day)
                sd_7d = await client_manager.call(client.get_sleep_data, day)
                total_steps_7d.append(stats_7d.get("totalSteps", 0) or 0)
                total_sleep_7d.append((sd_7d.get("dailySleepDTO") or {}).get("sleepTimeSeconds") or 0)

            avg_steps = round(sum(total_steps_7d) / len(total_steps_7d)) if total_steps_7d else "N/A"
            avg_sleep_h = round(sum(total_sleep_7d) / len(total_sleep_7d) / 3600, 1) if total_sleep_7d else "N/A"
            report_lines.append("")
            report_lines.append("📊 7天平均数据")
            report_lines.append(f"  👣 日均步数: {avg_steps}")
            report_lines.append(f"  😴 日均睡眠: {avg_sleep_h}h")

            # 建议
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
    return _run


# ─── 活动 ───────────────────────────────────────────

def get_filtered_activities(
    client_manager: GarminClientManager,
    keyword: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    activity_type: Optional[str] = None,
    max_count: int = 200,
) -> list:
    """获取过滤后的活动列表。"""
    async def _run():
        client = await client_manager.get_client()
        activities = await client_manager.get_activities()
        if not activities:
            return []

        matched = []
        for act in activities:
            act_type = (act.get("activityType") or {}).get("typeKey", "")
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

        return matched[:max_count]
    return _run


def build_activity_line(act: dict, formatter=None) -> str:
    """格式化单条活动信息为多行字符串。"""
    act_type = (act.get("activityType") or {}).get("typeKey", "未知")
    act_name = (act.get("activityName", "无名称") or "")[:18]
    start_time = act.get("startTimeLocal", "")
    date_str = start_time[:10] if start_time else "未知日期"

    distance = (act.get("distance", 0) or 0) / 1000
    duration = act.get("duration", 0) or 0
    avg_hr = act.get("averageHeartRate", None)
    elevation = act.get("elevationGain", 0) or 0
    avg_speed = act.get("averageSpeed", 0) or 0

    if formatter:
        pace_str = formatter(avg_speed)
    else:
        pace_str = pace_from_speed(avg_speed)

    line = f"  {date_str} {act_name}"
    line += f"\n  📏 {distance:.2f}km | ⏱ {_format_duration(duration)}"
    if avg_hr:
        line += f" | 💓 {avg_hr}bpm"
    if elevation:
        line += f" | ⛰ {round(elevation)}m"
    line += f" | 🏃 {pace_str}"
    return line


def activities_report(
    activities: list,
    header: str,
    formatter=None,
    max_items: int = 200,
) -> str:
    """生成活动列表报告。"""
    if not activities:
        return "❌ 暂无活动数据"
    lines = [header, "━━━━━━━━━━━━━━"]
    for i, act in enumerate(activities[:max_items], 1):
        lines.append(f"\n#{i} {build_activity_line(act, formatter)}")
    if len(activities) > max_items:
        lines.append(f"\n...还有{len(activities) - max_items}条未显示")
    return "\n".join(lines)


# ─── 体积统计（跑量/徒步/步行/骑行/游泳）────────────

def compute_volume(
    activities: list,
    type_keys: set,
    start_date: Optional[str],
    end_date: Optional[str],
) -> dict:
    """通用统计计算，返回 {dist, count, elev, duration}。"""
    result = {"dist": 0.0, "count": 0, "elev": 0.0, "duration": 0.0}
    for act in activities:
        act_type = (act.get("activityType") or {}).get("typeKey", "")
        if act_type not in type_keys:
            continue
        date_str = (act.get("startTimeLocal", "") or "")[:10]
        if start_date and date_str < start_date:
            continue
        if end_date and date_str > end_date:
            continue
        result["dist"] += safe_float(act.get("distance", 0)) / 1000
        result["count"] += 1
        result["elev"] += safe_float(act.get("elevationGain", 0))
        result["duration"] += safe_float(act.get("duration", 0)) / 3600
    return result


def build_volume_report(
    title: str,
    road: dict = None,
    trail: dict = None,
    single: dict = None,
    label: str = "",
) -> str:
    """生成统计报告，支持路跑/越野跑分开或单一类型。"""
    lines = []
    if label:
        lines.append(label)
    lines.append(f"📊 {title}")
    lines.append("━━━━━━━━━━━━━━")

    if road is not None:
        combined_dist = road["dist"] + trail["dist"]
        combined_cnt = road["count"] + trail["count"]
        combined_elev = road["elev"] + trail["elev"]
        combined_dur = road["duration"] + trail["duration"]
        lines.append(f"🏃 路跑: {road['dist']:.2f}km ({road['count']}次)")
        lines.append(f"   ⛰ 爬升{round(road['elev'])}m ⏱{round(road['duration'], 1)}h")
        lines.append(f"🏔 越野跑: {trail['dist']:.2f}km ({trail['count']}次)")
        lines.append(f"   ⛰ 爬升{round(trail['elev'])}m ⏱{round(trail['duration'], 1)}h")
        lines.append("───")
        lines.append(f"📌 合计: {combined_dist:.2f}km ({combined_cnt}次)")
        lines.append(f"   ⛰ 爬升{round(combined_elev)}m ⏱{round(combined_dur, 1)}h")
        if combined_cnt > 0:
            lines.append(f"   📏 均次 {combined_dist/combined_cnt:.2f}km")
    elif single is not None:
        d = single
        lines.append(f"📏 距离: {d['dist']:.2f}km ({d['count']}次)")
        lines.append(f"⛰ 爬升: {round(d['elev'])}m")
        lines.append(f"⏱ 时长: {round(d['duration'], 1)}h")
        if d["count"] > 0:
            lines.append(f"📏 均次: {d['dist']/d['count']:.2f}km")

    return "\n".join(lines)


# ─── 个人最佳 ──────────────────────────────────────

def personal_best_report(client_manager: GarminClientManager) -> str:
    """个人最佳记录。"""
    async def _run():
        try:
            client = await client_manager.get_client()
        except Exception as e:
            return f"❌ Garmin连接失败: {e}"
        try:
            activities = await client_manager.get_activities()
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

            pace_str = format_pace(max_pace_val) if max_pace_val > 0 else "N/A"

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
    return _run


# ─── 年度报告 ──────────────────────────────────────

def yearly_report(client_manager: GarminClientManager, year: int) -> str:
    """年度运动报告。"""
    async def _run():
        try:
            client = await client_manager.get_client()
        except Exception as e:
            return f"❌ Garmin 连接失败: {e}"
        try:
            activities = await client_manager.get_activities()
            if not activities:
                return "❌ 暂无活动数据"

            period_start = f"{year}-01-01"
            period_end = f"{year}-12-31"

            total_dist = total_dur = total_elev = total_cal = 0.0
            count = 0
            monthly = {m: 0.0 for m in range(1, 13)}

            for act in activities:
                date_str = (act.get("startTimeLocal", "") or "")[:10]
                if period_start <= date_str <= period_end:
                    dist = safe_float(act.get("distance", 0)) / 1000
                    total_dist += dist
                    total_dur += safe_float(act.get("duration", 0)) / 3600
                    total_elev += safe_float(act.get("elevationGain", 0))
                    total_cal += safe_float(act.get("calories", 0))
                    count += 1
                    if len(date_str) >= 7 and date_str[5:7].isdigit():
                        monthly[int(date_str[5:7])] += dist

            if count == 0:
                return f"📅 {year}年暂无可统计的活动"

            month_lines = [f"  {m}月: {monthly[m]:.1f}km" for m in range(1, 13) if monthly[m] > 0]
            month_text = "\n".join(month_lines) if month_lines else "  无距离数据"

            return (
                f"📅 {year}年运动报告\n"
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
    return _run


# ─── 重命名 ─────────────────────────────────────────

def rename_activity(client_manager: GarminClientManager, keyword: str, new_name: str) -> str:
    """重命名活动。"""
    async def _run():
        try:
            client = await client_manager.get_client()
        except Exception as e:
            return f"❌ Garmin连接失败: {e}"
        try:
            activities = await client_manager.get_activities(max_activities=200)
            matched = []
            for act in activities:
                act_name = (act.get("activityName", "") or "")
                if keyword.lower() in act_name.lower():
                    matched.append(act)
            if not matched:
                return f"❌ 未找到包含「{keyword}」的活动"
            act = matched[0]
            act_id = act.get("activityId", "")
            act_name = act.get("activityName", "")
            await client_manager.call(client.set_activity_name, act_id, new_name)
            logger.info(f"重命名活动 {act_id}: {act_name} -> {new_name}")
            return f"✅ 已将活动「{act_name}」重命名为「{new_name}」"
        except Exception as e:
            logger.error(f"重命名活动失败: {e}", exc_info=True)
            return f"❌ 重命名失败: {e}"
    return _run
