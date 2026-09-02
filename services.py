"""Garmin Health 插件业务逻辑层。

负责所有数据查询、统计计算和报告生成。
main.py 和 tools.py 通过调用这里的函数来工作，避免重复。
"""

from datetime import datetime, timedelta, timezone
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


def _sleep_time_range(daily_sleep: dict) -> str:
    """将 dailySleepDTO 中的起止毫秒时间戳转为可读的 12 小时制时间范围。
    优先用 Local 时间戳，fallback 到 GMT 和裸字段。
    """
    def _ts_to_time(ts_ms):
        if ts_ms and ts_ms > 0:
            dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
            return dt.strftime("%I:%M%p").lstrip("0")
        return None
    for start_key, end_key in [
        ("sleepStartTimestampLocal", "sleepEndTimestampLocal"),
        ("sleepStartTimestampGMT", "sleepEndTimestampGMT"),
        ("sleepStartTimestamp", "sleepEndTimestamp"),
    ]:
        start_ts = daily_sleep.get(start_key, 0)
        end_ts = daily_sleep.get(end_key, 0)
        if start_ts and end_ts:
            t_start = _ts_to_time(start_ts)
            t_end = _ts_to_time(end_ts)
            if t_start and t_end:
                return f"{t_start}-{t_end}"
    return None


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
            if sleep_time_secs:
                sleep_hours = round(sleep_time_secs / 3600, 1)
                sleep_score = ((daily_sleep.get("sleepScores") or {}).get("overall") or {}).get("value", "N/A")
                deep_sleep = round((daily_sleep.get("deepSleepSeconds") or 0) / 60, 1)
                light_sleep = round((daily_sleep.get("lightSleepSeconds") or 0) / 60, 1)
                rem_sleep = round((daily_sleep.get("remSleepSeconds") or 0) / 60, 1)
                sleep_range = _sleep_time_range(daily_sleep)
                sleep_range_str = f" ({sleep_range})" if sleep_range else ""
                sleep_line = f"😴 睡眠: {sleep_hours}h 评分{sleep_score}{sleep_range_str}\n   深睡{deep_sleep}min / 浅睡{light_sleep}min / REM{rem_sleep}min"
            else:
                sleep_line = "😴 睡眠: N/Ah"
            return (
                f"📊 今日健康概览 ({today})\n"
                f"━━━━━━━━━━━━━━\n"
                f"👣 步数: {total_steps} 步 | {dist_km} km\n"
                f"🔥 卡路里: {active_calories}/{total_calories} kcal\n"
                f"💓 心率: avg {avg_hr} / max {max_hr} / min {min_hr} bpm\n"
                f"{sleep_line}"
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
                if sleep_secs:
                    hours = round(sleep_secs / 3600, 1)
                    score = ((daily.get("sleepScores") or {}).get("overall") or {}).get("value", "N/A")
                    deep = round((daily.get("deepSleepSeconds") or 0) / 60, 1)
                    light = round((daily.get("lightSleepSeconds") or 0) / 60, 1)
                    rem = round((daily.get("remSleepSeconds") or 0) / 60, 1)
                    sleep_range = _sleep_time_range(daily)
                    range_str = f" ({sleep_range})" if sleep_range else ""
                    lines.append(f"{day}: {hours}h 评分{score}{range_str} (深{deep}/浅{light}/REM{rem}min)")
                else:
                    lines.append(f"{day}: N/Ah")
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







async def _generate_health_tips(
    context, ai_provider_name: str, client, client_manager,
    today: str, avg_steps, avg_sleep_h, sleep_score, sleep_days_with_data: int,
) -> list:
    """用 AI 或规则生成健康小贴士。"""
    # ── 未配置 AI → 规则模式 ──
    if not ai_provider_name or not context:
        return _rule_based_tips(avg_steps, avg_sleep_h, sleep_score)

    # ── 收集详细数据供 AI 参考 ──
    detailed_lines = []
    today_hr_vals = []
    today_sleep_val = "N/A"
    today_steps_val = "N/A"
    daily_hr_avg = []  # 收集每天的平均心率
    hr_days_with_data = 0  # 有心率数据的天数
    try:
        # 取今天数据用于今日速览
        today_day = datetime.now().strftime("%Y-%m-%d")
        today_stats = await client_manager.call(client.get_stats, today_day)
        today_hr_resp = await client_manager.call(client.get_heart_rates, today_day)
        today_sleep_resp = await client_manager.call(client.get_sleep_data, today_day)
        today_steps_val = str(today_stats.get("totalSteps", 0) or 0)
        today_hr_vals = [h[1] for h in (today_hr_resp.get("heartRateValues") or []) if h[1] and h[1] > 30]
        sleep_secs_today = (today_sleep_resp.get("dailySleepDTO") or {}).get("sleepTimeSeconds") or 0
        today_sleep_val = f"{round(sleep_secs_today / 3600, 1)}h" if sleep_secs_today > 0 else "无数据"

        # 取过去 7 天明细
        for i in range(1, 8):
            day = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            stats_d = await client_manager.call(client.get_stats, day)
            hr_d = await client_manager.call(client.get_heart_rates, day)
            sd_d = await client_manager.call(client.get_sleep_data, day)
            steps_d = stats_d.get("totalSteps", 0) or 0
            sleep_secs = (sd_d.get("dailySleepDTO") or {}).get("sleepTimeSeconds") or 0
            sleep_d = round(sleep_secs / 3600, 1) if sleep_secs > 0 else 0
            hr_vals = [h[1] for h in (hr_d.get("heartRateValues") or []) if h[1] and h[1] > 30]
            hr_avg = round(sum(hr_vals) / len(hr_vals)) if hr_vals else "N/A"
            hr_max = max(hr_vals) if hr_vals else "N/A"
            sleep_str = f"{sleep_d}h" if sleep_d > 0 else "无数据"
            detailed_lines.append(f"{day}: {steps_d}步 | HR avg{hr_avg}/max{hr_max} | 睡眠{sleep_str}")

            # 收集每天的平均心率
            if hr_vals:
                day_avg_hr = round(sum(hr_vals) / len(hr_vals))
                daily_hr_avg.append(day_avg_hr)
                hr_days_with_data += 1
        # 已去掉 if i == 0 块，今天数据提前拿了
    except Exception as e:
        logger.warning(f"收集AI健康数据失败: {e}")

    hr_avg_str = str(round(sum(today_hr_vals) / len(today_hr_vals))) if today_hr_vals else "N/A"
    hr_max_str = str(max(today_hr_vals)) if today_hr_vals else "N/A"

    # ── 计算7天日均心率 ──
    if daily_hr_avg:
        avg_hr_7d = round(sum(daily_hr_avg) / len(daily_hr_avg))
        max_hr_7d = max(daily_hr_avg)
        min_hr_7d = min(daily_hr_avg)
        hr_no_data_days = 7 - hr_days_with_data
        hr_no_data_note = f" ({hr_no_data_days}天无记录)" if hr_no_data_days > 0 else ""
    else:
        avg_hr_7d = "N/A"
        max_hr_7d = "N/A"
        min_hr_7d = "N/A"
        hr_no_data_note = " (无记录)"

    # ── 获取提示词模板 ──
    config = getattr(client_manager, "config", {})
    template = config.get("health_ai_prompt_template", "") if isinstance(config, dict) else ""
    if not template or not template.strip():
        template = (
            "你是一个专业的健康分析师。请基于以下7天的健康数据给出3-5条个性化健康建议。\n\n"
            "{health_data}\n\n"
            "## 要求\n"
            "1. 根据数据给出具体、可操作的建议，每条一行，用\"🔸\"开头\n"
            "2. 好的地方也要肯定，用\"✅\"开头\n"
            "3. 语气温和鼓励，每条建议简洁明了\n"
            "4. 不要输出Markdown格式，纯文本即可\n"
            "5. 仅输出建议内容，每行一条"
        )

    # ── 打包数据为一个占位符 {health_data} ──
    health_data = (
        f"## 今日数据\n"
        f"- 步数：{today_steps_val}\n"
        f"- 心率：avg {hr_avg_str} / max {hr_max_str}\n"
        f"- 睡眠：{today_sleep_val}（评分{sleep_score}）\n"
        f"\n"
        f"## 过去7天数据\n"
        f"- 日均步数：{avg_steps}\n"
        f"- 日均心率：avg{avg_hr_7d}/max{max_hr_7d}/min{min_hr_7d}bpm{hr_no_data_note}\n"
        f"- 日均睡眠：{avg_sleep_h}h\n"
        f"- 有睡眠数据的天数：{sleep_days_with_data}/7\n"
        f"- 有心率数据的天数：{hr_days_with_data}/7\n"
        f"\n"
        f"## 每日明细\n"
        f"{chr(10).join(detailed_lines)}"
    )
    prompt = template.format(health_data=health_data)

    # ── 调用 AI ──
    try:
        provider = context.get_provider_by_id(ai_provider_name)
        if not provider:
            logger.warning(f"健康小贴士AI: 未找到模型 '{ai_provider_name}'，回退规则模式")
            return _rule_based_tips(avg_steps, avg_sleep_h, sleep_score)
        token = await provider.text_chat(prompt=prompt)
        response = token.completion_text.strip()
        # 解析 AI 返回的每一行作为一条建议
        tips = [line.strip() for line in response.split("\n") if line.strip()]
        # 如果 AI 返回了空内容，回退
        if not tips:
            return _rule_based_tips(avg_steps, avg_sleep_h, sleep_score)
        return tips
    except Exception as e:
        logger.error(f"健康小贴士AI调用失败: {e}，回退规则模式", exc_info=True)
        return _rule_based_tips(avg_steps, avg_sleep_h, sleep_score)


def _rule_based_tips(avg_steps, avg_sleep_h, sleep_score) -> list:
    """规则模式：根据阈值生成健康小贴士。"""
    tips = []
    if isinstance(avg_steps, int) and avg_steps < 8000:
        tips.append("\U0001f538 日均步数偏少，建议多走动")
    elif isinstance(avg_steps, int) and avg_steps >= 10000:
        tips.append("\u2705 步数达标，继续保持")
    if isinstance(avg_sleep_h, float) and avg_sleep_h < 7:
        tips.append("\U0001f538 睡眠不足7小时，建议早睡")
    elif isinstance(avg_sleep_h, float) and avg_sleep_h >= 8:
        tips.append("\u2705 睡眠充足，状态不错")
    if isinstance(sleep_score, (int, float)) and sleep_score < 70:
        tips.append("\U0001f538 睡眠质量偏低，注意改善睡眠环境")
    return tips if tips else ["\u2705 整体状态良好，继续保持"]



def detailed_health_report(client_manager: GarminClientManager, context=None, ai_provider_name: str = "") -> str:
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
            total_steps_7d, total_sleep_7d, sleep_days_with_data = [], [], 0
            daily_hr_avg = []  # 收集每天的平均心率
            hr_days_with_data = 0  # 有心率数据的天数
            for i in range(1, 8):
                day = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
                stats_7d = await client_manager.call(client.get_stats, day)
                hr_7d = await client_manager.call(client.get_heart_rates, day)
                sd_7d = await client_manager.call(client.get_sleep_data, day)
                total_steps_7d.append(stats_7d.get("totalSteps", 0) or 0)

                # 收集心率数据：计算每天的平均心率
                hr_vals = [h[1] for h in (hr_7d.get("heartRateValues") or []) if h[1] and h[1] > 30]
                if hr_vals:
                    day_avg_hr = round(sum(hr_vals) / len(hr_vals))
                    daily_hr_avg.append(day_avg_hr)
                    hr_days_with_data += 1

                sleep_secs = (sd_7d.get("dailySleepDTO") or {}).get("sleepTimeSeconds") or 0
                total_sleep_7d.append(sleep_secs)
                if sleep_secs > 0:
                    sleep_days_with_data += 1

            avg_steps = round(sum(total_steps_7d) / len(total_steps_7d)) if total_steps_7d else "N/A"
            if sleep_days_with_data > 0:
                avg_sleep_h = round(sum(s for s in total_sleep_7d if s > 0) / sleep_days_with_data / 3600, 1)
                no_data_days = len(total_sleep_7d) - sleep_days_with_data
                no_data_note = f" ({no_data_days}天无记录)" if no_data_days > 0 else ""
            else:
                avg_sleep_h = "N/A"
                no_data_note = ""

            # 计算日均心率（每天平均心率的平均）
            if daily_hr_avg:
                avg_hr_7d = round(sum(daily_hr_avg) / len(daily_hr_avg))
                max_hr_7d = max(daily_hr_avg)
                min_hr_7d = min(daily_hr_avg)
                hr_no_data_days = 7 - hr_days_with_data
                hr_no_data_note = f" ({hr_no_data_days}天无记录)" if hr_no_data_days > 0 else ""
            else:
                avg_hr_7d = "N/A"
                max_hr_7d = "N/A"
                min_hr_7d = "N/A"
                hr_no_data_note = " (无记录)"

            report_lines.append("")
            yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
            week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
            report_lines.append(f"📊 过去7天 ({week_ago} ~ {yesterday})")
            report_lines.append(f"  👣 日均步数: {avg_steps}")
            report_lines.append(f"  💓 日均心率: avg{avg_hr_7d}/max{max_hr_7d}/min{min_hr_7d}bpm{hr_no_data_note}")
            report_lines.append(f"  😴 日均睡眠: {avg_sleep_h}h{no_data_note}")

            # 建议（AI 或 规则）
            report_lines.append("")
            report_lines.append("💡 健康小贴士")
            tips = await _generate_health_tips(
                context=context,
                ai_provider_name=ai_provider_name,
                client=client,
                client_manager=client_manager,
                today=today,
                avg_steps=avg_steps,
                avg_sleep_h=avg_sleep_h,
                sleep_score=sleep_score,
                sleep_days_with_data=sleep_days_with_data,
            )
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
    # 子类型 → 父类型映射（Garmin API 只接受父类型作为 activity_type 参数）
    SUBTYPE_TO_PARENT = {
        "street_running": "running", "track_running": "running", "indoor_running": "running",
        "treadmill_running": "running", "virtual_run": "running", "trail_running": "running",
        "ultra_run": "running", "obstacle_run": "running",
        "rucking": "hiking",
        "speed_walking": "walking", "casual_walking": "walking",
        "road_biking": "cycling", "mountain_biking": "cycling", "gravel_cycling": "cycling",
        "indoor_cycling": "cycling", "bmx": "cycling", "e_bike_fitness": "cycling",
        "downhill_biking": "cycling", "recumbent_cycling": "cycling", "cyclocross": "cycling",
        "virtual_ride": "cycling", "track_cycling": "cycling", "hand_cycling": "cycling",
        "indoor_hand_cycling": "cycling", "e_enduro_mtb": "cycling", "enduro_mtb": "cycling",
        "e_bike_mountain": "cycling",
        "lap_swimming": "swimming", "open_water_swimming": "swimming",
    }

    async def _run():
        client = await client_manager.get_client()
        # 子类型用父类型查 API（Garmin API 不接受子类型），Python 层再过滤
        api_type = SUBTYPE_TO_PARENT.get(activity_type, activity_type)
        activities = await client_manager.get_activities(activity_type=api_type)
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
    act_name = act.get("activityName", "无名称") or "无名称"
    start_time = act.get("startTimeLocal", "")
    date_str = start_time[:10] if start_time else "未知日期"

    distance = (act.get("distance", 0) or 0) / 1000
    duration = act.get("duration", 0) or 0
    avg_hr = act.get("averageHeartRate") or act.get("averageHR")
    elevation = act.get("elevationGain", 0) or 0
    avg_speed = act.get("averageSpeed", 0) or 0
    calories = act.get("calories", 0) or 0
    pack_weight = safe_float(act.get("beginPackWeight", 0)) / 1000 if act_type == "rucking" else 0
    step_types = {"walking", "hiking", "running", "trail_running", "rucking"}
    steps = int(act.get("steps", 0) or 0)

    if formatter:
        pace_str = formatter(avg_speed)
    else:
        pace_str = pace_from_speed(avg_speed)

    line = f"  {date_str} {act_name}"
    line += f"\n  📏 {distance:.2f}km | ⏱ {_format_duration(duration)}"
    if avg_hr:
        line += f" | 💓 {avg_hr}bpm"
    no_elev_types = {"indoor_running", "track_running", "virtual_running", "treadmill_running",
                     "indoor_cycling", "virtual_cycling"}
    if elevation and act_type not in no_elev_types:
        line += f" | ⛰ {round(elevation)}m"
    if pack_weight > 0:
        line += f" | 🏋️{round(pack_weight, 1)}kg"
    if steps > 0 and act_type in step_types:
        line += f" | 👣{steps}步"
    if calories >= 0:
        line += f" | 🔥{round(calories)}kcal"
    dur_h = duration / 3600
    if distance > 0 and dur_h > 0:
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
    idx = 0
    for act in activities[:max_items]:
        idx += 1
        lines.append(f"\n#{idx} {build_activity_line(act, formatter)}")
    if len(activities) > max_items:
        lines.append(f"\n...还有{len(activities) - max_items}条未显示")
    return "\n".join(lines)


# ─── 体积统计（跑步/徒步/步行/骑行/游泳）───────

def compute_volume(
    activities: list,
    type_keys: set,
    start_date: Optional[str],
    end_date: Optional[str],
) -> dict:
    """通用统计计算，返回 {dist, count, elev, duration, calories, steps, weight, hr_weighted, hr_dur, strokes}。"""
    result = {"dist": 0.0, "count": 0, "elev": 0.0, "duration": 0.0, "calories": 0.0, "steps": 0, "weight": 0.0, "hr_weighted": 0.0, "hr_dur": 0.0, "strokes": 0}
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
        act_dur_s = safe_float(act.get("duration", 0))
        result["duration"] += act_dur_s / 3600
        result["calories"] += safe_float(act.get("calories", 0))
        result["steps"] += int(safe_float(act.get("steps", 0)))
        bw = safe_float(act.get("beginPackWeight", 0)) / 1000  # 克→千克
        if bw > result["weight"]:
            result["weight"] = bw  # 取最大值（每次活动背包重量独立，不累加）
        # 心率：duration 加权平均
        avg_hr = act.get("averageHeartRate") or act.get("averageHR")
        if avg_hr and act_dur_s > 0:
            result["hr_weighted"] += avg_hr * act_dur_s
            result["hr_dur"] += act_dur_s
        # 游泳划水次数
        result["strokes"] += int(safe_float(act.get("strokes", 0)))
    return result


# ─── typeKey 映射表（唯一权威来源）─────────────

TYPEKEY_MAP = {
    "running": [
        ("running",          "🏃 跑步",     {"running"}),
        ("indoor_running",   "🏠 室内跑步", {"indoor_running"}),
        ("track_running",    "🏟 场地跑步", {"track_running"}),
        ("virtual_run",      "💻 虚拟跑步", {"virtual_run"}),
        ("street_running",   "🛣 路跑",     {"street_running"}),
        ("ultra_run",        "⚡ 超马",     {"ultra_run"}),
        ("trail_running",    "🏔 越野跑",   {"trail_running"}),
        ("treadmill_running","🏋 跑步机",   {"treadmill_running"}),
        ("obstacle_run",     "🚧 障碍跑",   {"obstacle_run"}),
    ],
    "hiking": [
        ("hiking",   "🥾 徒步",      {"hiking"}),
        ("rucking",  "🎒 负重徒步",  {"rucking"}),
    ],
    "walking": [
        ("walking",         "🚶 步行",    {"walking"}),
        ("speed_walking",   "🏃 竞走",    {"speed_walking"}),
        ("casual_walking",  "🚶‍♂️ 散步",  {"casual_walking"}),
    ],
    "swimming": [
        ("swimming",              "🏊 游泳",         {"swimming"}),
        ("open_water_swimming",   "🌊 公开水域游泳", {"open_water_swimming"}),
        ("lap_swimming",          "🏊‍♂️ 泳池游泳",   {"lap_swimming"}),
    ],
    "cycling": [
        ("cycling",             "🚲 骑行",             {"cycling"}),
        ("e_enduro_mtb",        "⚡ e-Enduro",         {"e_enduro_mtb"}),
        ("enduro_mtb",          "🔋 Enduro",           {"enduro_mtb"}),
        ("road_biking",         "🚴 公路自行车",       {"road_biking"}),
        ("track_cycling",       "🏟 场地自行车",       {"track_cycling"}),
        ("indoor_hand_cycling", "✋🏠 室内手摇自行车", {"indoor_hand_cycling"}),
        ("indoor_cycling",      "🏠 室内自行车",       {"indoor_cycling"}),
        ("bmx",                 "🔄 BMX",              {"bmx"}),
        ("mountain_biking",     "⛰ 山地自行车",       {"mountain_biking"}),
        ("hand_cycling",        "✋ 手摇自行车",       {"hand_cycling"}),
        ("e_bike_fitness",      "⚡ 电动自行车",       {"e_bike_fitness"}),
        ("e_bike_mountain",     "⛰⚡ e-MTB",          {"e_bike_mountain"}),
        ("gravel_cycling",      "🪨 Gravel",           {"gravel_cycling"}),
        ("virtual_ride",        "💻 虚拟自行车",       {"virtual_ride"}),
        ("cyclocross",          "🏁 公路越野",         {"cyclocross"}),
        ("recumbent_cycling",   "🛋 躺车",             {"recumbent_cycling"}),
        ("downhill_biking",     "⏬ 速降",             {"downhill_biking"}),
    ],
}



def build_volume_report(title: str, **kwargs) -> str:
    """通用运动统计报告生成器。

    根据提供的关键字参数自动判断报告类型并格式化输出。
    支持：跑步类、徒步类（含步数+负重重量）、步行类、骑行类、游泳类、单类型。"""
    lines = [f"📊 {title}", "━━━━━━━━━━━━━━"]

    # ── 辅助函数 ──
    def _pace_str(dist_km: float, dur_h: float) -> str:
        if dist_km > 0 and dur_h > 0:
            return f" {dur_h * 60 / dist_km:.1f}min/km"
        if dur_h >= 0:
            return f" 0.0min/km"
        return ""

    def _swim_pace_str(dist_km: float, dur_h: float) -> str:
        if dist_km > 0 and dur_h > 0:
            pace = dur_h * 6 / dist_km  # min/100m（1km=10×100m）
            return f" {pace:.1f}min/100m"
        return ""

    def _elev_str(label: str, elev: float, no_elev: set = None) -> str:
        if no_elev and label in no_elev:
            return ""
        return f" ⛰ {round(elev)}m" if elev > 0 else ""

    def _cal_str(cal: float) -> str:
        return f" 🔥{round(cal)}kcal" if cal >= 0 else ""

    def _steps_str(steps: int) -> str:
        return f" 👣{steps}步" if steps >= 0 else ""

    def _weight_str(w: float) -> str:
        return f" 🏋️{round(w, 1)}kg" if w >= 0 else ""

    def _hr_str(d: dict) -> str:
        """返回持续时间加权的平均心率字符串。"""
        if d.get("hr_dur", 0) > 0:
            avg = round(d["hr_weighted"] / d["hr_dur"])
            return f" 💓{avg}bpm"
        return ""

    def _stroke_str(strokes: int) -> str:
        return f" 🤿{strokes}strokes" if strokes > 0 else ""

    RUNNING_NO_ELEV = {"🏠 室内跑步", "🏟 场地跑步", "💻 虚拟跑步", "🏋 跑步机"}
    CYCLING_NO_ELEV = {"🏠 室内自行车", "💻 虚拟自行车", "🏟 场地自行车", "✋🏠 室内手摇自行车", "🔄 BMX"}

    # ── 跑步类（九类细分） ──
    if kwargs.get("running") is not None:
        sections = [
            ("🏃 跑步",       kwargs.get("running")),
            ("🛣 路跑",       kwargs.get("street_running")),
            ("🏔 越野跑",     kwargs.get("trail_running")),
            ("⚡ 超马",       kwargs.get("ultra_running")),
            ("🏠 室内跑步",   kwargs.get("indoor_running")),
            ("🏟 场地跑步",   kwargs.get("track_running")),
            ("🏋 跑步机",     kwargs.get("treadmill_running")),
            ("💻 虚拟跑步",   kwargs.get("virtual_running")),
            ("🚧 障碍跑",     kwargs.get("obstacle_racing")),
        ]
        total_dist = total_cnt = total_elev = total_dur = total_cal = 0.0
        for _label, data in sections:
            if data and data["count"] > 0:
                pace = _pace_str(data["dist"], data["duration"])
                elev = _elev_str(_label, data["elev"], RUNNING_NO_ELEV)
                hr = _hr_str(data)
                cal = _cal_str(data["calories"])
                lines.append(f"{_label}: {data['dist']:.2f}km ({data['count']}次){pace}")
                lines.append(f"  {elev}{hr}⏱{round(data['duration'], 1)}h{cal}")
                total_dist += data["dist"]
                total_cnt += data["count"]
                total_elev += data["elev"]
                total_dur += data["duration"]
                total_cal += data["calories"]
        lines.append("───")
        lines.append(f"📌 合计: {total_dist:.2f}km ({int(total_cnt)}次)")
        if total_elev > 0:
            lines.append(f"   ⛰ {round(total_elev)}m ⏱{round(total_dur, 1)}h{_cal_str(total_cal)}")
        else:
            lines.append(f"   ⏱{round(total_dur, 1)}h{_cal_str(total_cal)}")
        if total_cnt > 0:
            lines.append(f"   📏 均次 {total_dist/total_cnt:.2f}km")

    # ── 徒步类（含步数，负重徒步含重量） ──
    elif kwargs.get("hike_normal") is not None:
        sections = [
            ("🥾 徒步",     kwargs.get("hike_normal")),
            ("🎒 负重徒步", kwargs.get("hike_ruck")),
        ]
        total_dist = total_cnt = total_elev = total_dur = total_cal = 0.0
        total_steps = 0
        for _label, data in sections:
            if data and data["count"] > 0:
                steps = _steps_str(data.get("steps", 0))
                weight = _weight_str(data.get("weight", 0)) if "负重" in _label else ""
                hr = _hr_str(data)
                cal = _cal_str(data["calories"])
                lines.append(f"{_label}: {data['dist']:.2f}km ({data['count']}次)")
                lines.append(f"   {steps}{weight}{hr}⛰ {round(data['elev'])}m ⏱{round(data['duration'], 1)}h{cal}")
                total_dist += data["dist"]
                total_cnt += data["count"]
                total_elev += data["elev"]
                total_dur += data["duration"]
                total_cal += data["calories"]
                total_steps += data.get("steps", 0)
        lines.append("───")
        lines.append(f"📌 合计: {total_dist:.2f}km ({int(total_cnt)}次){_steps_str(total_steps)}")
        if total_elev > 0:
            lines.append(f"   ⛰ {round(total_elev)}m ⏱{round(total_dur, 1)}h{_cal_str(total_cal)}")
        else:
            lines.append(f"   ⏱{round(total_dur, 1)}h{_cal_str(total_cal)}")
        if total_cnt > 0:
            lines.append(f"   📏 均次 {total_dist/total_cnt:.2f}km")

    # ── 步行类（三分类，含步数） ──
    elif kwargs.get("walk_normal") is not None:
        sections = [
            ("🚶 步行",   kwargs.get("walk_normal")),
            ("🏃 竞走",   kwargs.get("walk_speed")),
            ("🚶\u200d♂️ 散步", kwargs.get("walk_casual")),
        ]
        total_dist = total_cnt = total_elev = total_dur = total_cal = 0.0
        total_steps = 0
        for _label, data in sections:
            if data and data["count"] > 0:
                steps = _steps_str(data.get("steps", 0))
                cal = _cal_str(data["calories"])
                lines.append(f"{_label}: {data['dist']:.2f}km ({data['count']}次){steps}")
                hr = _hr_str(data)
                elev = _elev_str(_label, data["elev"])
                lines.append(f"  {elev}{hr}⏱{round(data['duration'], 1)}h{cal}")
                total_dist += data["dist"]
                total_cnt += data["count"]
                total_elev += data["elev"]
                total_dur += data["duration"]
                total_cal += data["calories"]
                total_steps += data.get("steps", 0)
        lines.append("───")
        lines.append(f"📌 合计: {total_dist:.2f}km ({int(total_cnt)}次){_steps_str(total_steps)}")
        if total_elev > 0:
            lines.append(f"   ⛰ {round(total_elev)}m ⏱{round(total_dur, 1)}h{_cal_str(total_cal)}")
        else:
            lines.append(f"   ⏱{round(total_dur, 1)}h{_cal_str(total_cal)}")
        if total_cnt > 0:
            lines.append(f"   📏 均次 {total_dist/total_cnt:.2f}km")

    # ── 游泳类 ──
    elif kwargs.get("swim_generic") is not None:
        sections = [
            ("🏊 游泳",         kwargs.get("swim_generic")),
            ("🌊 公开水域游泳", kwargs.get("swim_open")),
            ("🏊\u200d♂️ 泳池游泳",  kwargs.get("swim_pool")),
        ]
        total_dist = total_cnt = total_dur = total_cal = 0.0
        for _label, data in sections:
            if data and data["count"] > 0:
                pace = _swim_pace_str(data["dist"], data["duration"])
                strokes = _stroke_str(data.get("strokes", 0))
                cal = _cal_str(data["calories"])
                hr = _hr_str(data)
                lines.append(f"{_label}: {data['dist']:.2f}km ({data['count']}次){pace}{strokes}")
                lines.append(f"   {hr}⏱{round(data['duration'], 1)}h{cal}")
                total_dist += data["dist"]
                total_cnt += data["count"]
                total_dur += data["duration"]
                total_cal += data["calories"]
        lines.append("───")
        lines.append(f"📌 合计: {total_dist:.2f}km ({int(total_cnt)}次)")
        lines.append(f"   ⏱{round(total_dur, 1)}h{_cal_str(total_cal)}")
        if total_cnt > 0:
            lines.append(f"   📏 均次 {total_dist/total_cnt:.2f}km")

    # ── 骑行类（17类细分） ──
    elif kwargs.get("cycling_generic") is not None or kwargs.get("cycling_road") is not None:
        sections = [
            ("🚲 骑行",       kwargs.get("cycling_generic")),
            ("🚴 公路自行车", kwargs.get("cycling_road")),
            ("⛰ 山地自行车", kwargs.get("cycling_mountain")),
            ("🪨 Gravel",     kwargs.get("cycling_gravel")),
            ("🔋 Enduro",     kwargs.get("cycling_enduro")),
            ("⚡ e-Enduro",   kwargs.get("cycling_eenduro")),
            ("⛰⚡ e-MTB",    kwargs.get("cycling_emtb")),
            ("⚡ 电动自行车", kwargs.get("cycling_ebike")),
            ("🏁 公路越野",   kwargs.get("cycling_cyclocross")),
            ("⏬ 速降",       kwargs.get("cycling_downhill")),
            ("🔄 BMX",        kwargs.get("cycling_bmx")),
            ("🏟 场地自行车", kwargs.get("cycling_track")),
            ("🏠 室内自行车", kwargs.get("cycling_indoor")),
            ("✋🏠 室内手摇", kwargs.get("cycling_indoor_hand")),
            ("✋ 手摇自行车", kwargs.get("cycling_hand")),
            ("🛋 躺车",       kwargs.get("cycling_recumbent")),
            ("💻 虚拟自行车", kwargs.get("cycling_virtual")),
        ]
        total_dist = total_cnt = total_elev = total_dur = total_cal = 0.0
        for _label, data in sections:
            if data and data["count"] > 0:
                pace = _pace_str(data["dist"], data["duration"])
                elev = _elev_str(_label, data["elev"], CYCLING_NO_ELEV)
                hr = _hr_str(data)
                cal = _cal_str(data["calories"])
                lines.append(f"{_label}: {data['dist']:.2f}km ({data['count']}次){pace}")
                lines.append(f"  {elev}{hr}⏱{round(data['duration'], 1)}h{cal}")
                total_dist += data["dist"]
                total_cnt += data["count"]
                total_elev += data["elev"]
                total_dur += data["duration"]
                total_cal += data["calories"]
        lines.append("───")
        lines.append(f"📌 合计: {total_dist:.2f}km ({int(total_cnt)}次)")
        if total_elev > 0:
            lines.append(f"   ⛰ {round(total_elev)}m ⏱{round(total_dur, 1)}h{_cal_str(total_cal)}")
        else:
            lines.append(f"   ⏱{round(total_dur, 1)}h{_cal_str(total_cal)}")
        if total_cnt > 0:
            lines.append(f"   📏 均次 {total_dist/total_cnt:.2f}km")

    # ── 单类型（通用） ──
    elif kwargs.get("single") is not None:
        d = kwargs["single"]
        pace = _pace_str(d["dist"], d["duration"])
        cal = _cal_str(d["calories"])
        steps = _steps_str(d.get("steps", 0))
        lines.append(f"📏 距离: {d['dist']:.2f}km ({d['count']}次){pace}{steps}")
        lines.append(f"⛰ 爬升: {round(d['elev'])}m")
        lines.append(f"⏱ 时长: {round(d['duration'], 1)}h{cal}")
        if d["count"] > 0:
            lines.append(f"📏 均次: {d['dist']/d['count']:.2f}km")

    # ── 徒步+步行混合（旧兼容） ──
    elif kwargs.get("hiking") is not None and kwargs.get("walking") is not None:
        for _label, d in [("🥾 徒步", kwargs["hiking"]), ("🚶 步行", kwargs["walking"])]:
            steps = _steps_str(d.get("steps", 0))
            lines.append(f"{_label}: {d['dist']:.2f}km ({d['count']}次){steps}")
            lines.append(f"   ⛰ {round(d['elev'])}m ⏱{round(d['duration'], 1)}h{_cal_str(d['calories'])}")
        h, w = kwargs["hiking"], kwargs["walking"]
        total_dist = h["dist"] + w["dist"]
        total_cnt = h["count"] + w["count"]
        total_elev = h["elev"] + w["elev"]
        total_dur = h["duration"] + w["duration"]
        total_cal = h["calories"] + w["calories"]
        lines.append("───")
        lines.append(f"📌 合计: {total_dist:.2f}km ({int(total_cnt)}次)")
        lines.append(f"   ⛰ {round(total_elev)}m ⏱{round(total_dur, 1)}h{_cal_str(total_cal)}")
        if total_cnt > 0:
            lines.append(f"   📏 均次 {total_dist/total_cnt:.2f}km")

    else:
        lines.append("暂无统计数据")

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
