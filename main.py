"""
佳明健康看板
通过 Garmin Connect 查询健康数据（心率、睡眠、步数、活动统计等）并生成分析报告

双模式架构：
  🏛 固定命令 — 保留全部 /xxx 命令，兼容老用户习惯
  🧠 工具链调用 — 注册 FunctionTool，大模型可自动调用，支持自然语言灵活查询
"""

import os
import re
from datetime import datetime, timedelta

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger

from .client_manager import GarminClientManager, _today_str, _format_duration
from .tools import create_all_tools


@register("astrbot_plugin_garmin_health", "Jonathan-614", "佳明健康看板 - 通过Garmin Connect查询健康数据（心率、睡眠、步数、活动统计等）并生成分析报告，支持自然语言查询", "1.0.0")
class GarminHealthPlugin(Star):
    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        self.config = config or {}
        session_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), ".garmin_session"
        )
        self.client_manager = GarminClientManager(self.config, session_dir)
        # 注册 LLM 工具链
        self._register_llm_tools()

    def _register_llm_tools(self):
        """注册所有 FunctionTool 到大模型"""
        try:
            tools = create_all_tools(self.client_manager)
            self.context.add_llm_tools(*tools)
            logger.info(f"✅ 已注册 {len(tools)} 个 Garmin 工具链")
        except Exception as e:
            logger.error(f"❌ 注册 LLM 工具失败: {e}", exc_info=True)

    # ═══════════════════════════════════════════
    # 固定命令区（兼容老用户）
    # ═══════════════════════════════════════════

    @filter.command("garmin")
    async def garmin_help(self, event: AstrMessageEvent):
        """显示 Garmin 插件帮助信息"""
        help_text = (
            "🏃 Garmin Health 插件使用指南\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "🧠 推荐方式：直接说自然语言\n"
            "  例如「我今天状态怎么样」「去年跑了多少」「帮我查梧桐山的活动」\n"
            "  大模型会自动调用工具查询，无需记命令\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "📊 健康数据\n"
            "  /健康       — 今日健康概览（步数/心率/睡眠）\n"
            "  /心率       — 最近7天心率趋势\n"
            "  /睡眠       — 最近7天睡眠报告\n"
            "  /步数       — 最近7天步数数据\n"
            "  /身体报告   — 综合健康诊断（含7天平均和建议）\n"
            "🏃 活动统计\n"
            "  /活动       — 查看活动\n"
            "    默认: 最近5条\n"
            "    /活动 N: 最近N条（上限200）\n"
            "    /活动 日期: 按日期筛选，如 /活动 2026-06-08\n"
            "    /活动 关键词: 按活动名模糊搜索，如 /活动 梧桐山\n"
            "  /跑量 [参数] — 跑量统计（路跑+越野跑）\n"
            "    /跑量         近7天\n"
            "    /跑量 all     全部记录\n"
            "    /跑量 2025    全年\n"
            "    /跑量 2025-06 整月\n"
            "    /跑量 2025-06-08 单日\n"
            "    /跑量 30      近30天\n"
            "  /徒步 [参数] — 徒步统计，参数规则同 /跑量\n"
            "  /步行 [参数] — 步行统计，参数规则同 /跑量\n"
            "  /骑行 [参数] — 骑行统计，参数规则同 /跑量\n"
            "  /游泳 [参数] — 游泳统计，参数规则同 /跑量\n"
            "  /PB         — 个人最佳记录（最长距离/最快配速/最大爬升/最长时长）\n"
            "  /年度报告 [年份]  — 年度运动报告（默认今年），如 /年度报告 2025\n"
            "📌 配置\n"
            "  请在插件配置中填写 Garmin 账号密码\n"
            "━━━━━━━━━━━━━━━━━━━━━"
        )
        yield event.plain_result(help_text)

    @filter.command("健康")
    async def health_today(self, event: AstrMessageEvent):
        """显示今日健康概览（心率+步数+睡眠）"""
        try:
            client = await self.client_manager.get_client()
        except ValueError as e:
            yield event.plain_result(f"❌ {e}")
            return
        except Exception as e:
            yield event.plain_result(f"❌ Garmin连接失败: {e}")
            return

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

            report = (
                f"📊 今日健康概览 ({today})\n"
                f"━━━━━━━━━━━━━━\n"
                f"👣 步数: {total_steps} 步 | {dist_km} km\n"
                f"🔥 卡路里: {active_calories}/{total_calories} kcal\n"
                f"💓 心率: avg {avg_hr} / max {max_hr} / min {min_hr} bpm\n"
                f"😴 睡眠: {sleep_hours}h (评分{sleep_score})\n"
                f"   深睡{deep_sleep}min / 浅睡{light_sleep}min / REM{rem_sleep}min"
            )
            yield event.plain_result(report)
        except Exception as e:
            logger.error(f"获取健康数据失败: {e}", exc_info=True)
            yield event.plain_result(f"❌ 获取数据失败: {e}")

    @filter.command("心率")
    async def heart_rate_report(self, event: AstrMessageEvent):
        """显示最近7天心率数据"""
        try:
            client = await self.client_manager.get_client()
        except Exception as e:
            yield event.plain_result(f"❌ Garmin连接失败: {e}")
            return

        try:
            lines = ["💓 最近7天心率趋势", "━━━━━━━━━━━━━━"]
            for i in range(7):
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
            yield event.plain_result("\n".join(lines))
        except Exception as e:
            yield event.plain_result(f"❌ 获取心率数据失败: {e}")

    @filter.command("睡眠")
    async def sleep_report(self, event: AstrMessageEvent):
        """显示最近7天睡眠数据"""
        try:
            client = await self.client_manager.get_client()
        except Exception as e:
            yield event.plain_result(f"❌ Garmin连接失败: {e}")
            return

        try:
            lines = ["😴 最近7天睡眠报告", "━━━━━━━━━━━━━━"]
            for i in range(7):
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
            yield event.plain_result("\n".join(lines))
        except Exception as e:
            yield event.plain_result(f"❌ 获取睡眠数据失败: {e}")

    @filter.command("步数")
    async def steps_report(self, event: AstrMessageEvent):
        """显示最近7天步数数据"""
        try:
            client = await self.client_manager.get_client()
        except Exception as e:
            yield event.plain_result(f"❌ Garmin连接失败: {e}")
            return

        try:
            lines = ["👣 最近7天步数报告", "━━━━━━━━━━━━━━"]
            for i in range(7):
                day = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
                stats = client.get_stats(day)
                steps = stats.get("totalSteps", "N/A")
                dist = stats.get("totalDistance", 0)
                dist_km = round(dist / 1000, 2) if isinstance(dist, (int, float)) else "N/A"
                cal = stats.get("activeKilocalories", "N/A")
                lines.append(f"{day}: {steps}步 / {dist_km}km / {cal}kcal")
            yield event.plain_result("\n".join(lines))
        except Exception as e:
            yield event.plain_result(f"❌ 获取步数数据失败: {e}")

    @filter.command("身体报告")
    async def detailed_report(self, event: AstrMessageEvent):
        """详细健康诊断报告（7天综合）"""
        try:
            client = await self.client_manager.get_client()
        except Exception as e:
            yield event.plain_result(f"❌ Garmin连接失败: {e}")
            return

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

            yield event.plain_result("\n".join(report_lines))
        except Exception as e:
            logger.error(f"生成综合报告失败: {e}", exc_info=True)
            yield event.plain_result(f"❌ 生成报告失败: {e}")

    # ═══════════════════════════════════════════
    # 活动统计命令
    # ═══════════════════════════════════════════

    def _format_activity(self, act: dict) -> str:
        """格式化单条活动信息"""
        act_type = act.get("activityType", {}).get("typeKey", "未知")
        act_name = (act.get("activityName", "无名称") or "")[:18]
        start_time = act.get("startTimeLocal", "")
        date_str = start_time[:10] if start_time else "未知日期"

        distance = (act.get("distance", 0) or 0) / 1000
        duration = act.get("duration", 0) or 0
        avg_hr = act.get("averageHeartRate", None)
        elevation = act.get("elevationGain", 0) or 0
        avg_speed = act.get("averageSpeed", 0) or 0

        pace_str = "N/A"
        if avg_speed > 0:
            pace = 1000 / avg_speed / 60
            if pace < 60:
                pace_str = f"{pace:.2f}min/km"

        line = f"  {date_str} {act_name}"
        line += f"\n  📏 {distance:.2f}km | ⏱ {_format_duration(duration)}"
        if avg_hr:
            line += f" | 💓 {avg_hr}bpm"
        if elevation:
            line += f" | ⛰ {round(elevation)}m"
        line += f" | 🏃 {pace_str}"
        return line

    @filter.command("活动")
    async def recent_activities(self, event: AstrMessageEvent):
        """查看活动。用法: /活动 (最近5条) | /活动 N | /活动 日期 | /活动 活动名"""
        try:
            client = await self.client_manager.get_client()
        except Exception as e:
            yield event.plain_result(f"❌ 连接失败: {e}")
            return

        try:
            msg = event.message_str.strip()
            parts = msg.split(maxsplit=1)
            arg = parts[1].strip() if len(parts) >= 2 else ""

            # 无参数：默认最近5条
            if not arg:
                activities = client.get_activities(0, 5)
                if not activities:
                    yield event.plain_result("❌ 暂无活动数据")
                    return
                lines = ["🏃 最近5条活动", "━━━━━━━━━━━━━━"]
                for i, act in enumerate(activities, 1):
                    lines.append(f"\n#{i} {self._format_activity(act)}")
                yield event.plain_result("\n".join(lines))
                return

            # 纯数字：拉取N条
            if arg.isdigit():
                n = min(int(arg), 200)
                activities = client.get_activities(0, n)
                if not activities:
                    yield event.plain_result("❌ 暂无活动数据")
                    return
                lines = [f"🏃 最近{n}条活动", "━━━━━━━━━━━━━━"]
                for i, act in enumerate(activities, 1):
                    lines.append(f"\n#{i} {self._format_activity(act)}")
                yield event.plain_result("\n".join(lines))
                return

            # 按日期
            date_match = re.search(r'(\d{4})[年/-]?(\d{1,2})[月/-]?(\d{1,2})日?', arg)
            if date_match:
                y, m, d = date_match.groups()
                target = f"{y}-{int(m):02d}-{int(d):02d}"
                activities = client.get_activities(0, 200)
                matched = [a for a in activities if (a.get("startTimeLocal", "") or "")[:10] == target]
                if not matched:
                    yield event.plain_result(f"📅 {target} 暂无活动记录")
                    return
                lines = [f"📅 {target} 共{len(matched)}条活动", "━━━━━━━━━━━━━━"]
                for i, act in enumerate(matched, 1):
                    lines.append(f"\n#{i} {self._format_activity(act)}")
                yield event.plain_result("\n".join(lines))
                return

            # 按活动名模糊搜索
            activities = client.get_activities(0, 200)
            kw = arg.lower()
            matched = [a for a in activities if kw in ((a.get("activityName", "") or "").lower())]
            if not matched:
                yield event.plain_result(f"🔍 未找到含「{arg}」的活动")
                return
            lines = [f"🔍 搜索「{arg}」共{len(matched)}条", "━━━━━━━━━━━━━━"]
            for i, act in enumerate(matched[:20], 1):
                lines.append(f"\n#{i} {self._format_activity(act)}")
            if len(matched) > 20:
                lines.append(f"\n...还有{len(matched)-20}条未显示")
            yield event.plain_result("\n".join(lines))

        except Exception as e:
            logger.error(f"获取活动失败: {e}", exc_info=True)
            yield event.plain_result(f"❌ 获取活动失败: {e}")

    # ─── 跑量命令通用辅助方法 ──────────────────────

    def _parse_volume_arg(self, arg: str) -> tuple:
        """解析时间参数，返回 (start_date, end_date, label)
        支持格式：
          '' / '7'       — 近7天（默认）
          '30'           — 近30天
          'all'          — 全部
          '2026'         — 2026全年
          '2026-06'      — 2026年6月
          '2026-06-01'   — 单日
        """
        now = datetime.now()
        if not arg:
            end = _today_str()
            start = (now - timedelta(days=6)).strftime("%Y-%m-%d")
            return start, end, f"📅 近7天 ({start} ~ {end})"

        arg = arg.strip()

        if arg.lower() == "all":
            return "", "9999-12-31", "📅 全部记录"

        if re.match(r'^\d{4}$', arg):
            return f"{arg}-01-01", f"{arg}-12-31", f"📅 {arg}全年"

        month_match = re.match(r'^(\d{4})-(\d{1,2})$', arg)
        if month_match:
            y, m = month_match.groups()
            last_day = 30
            if int(m) in (1, 3, 5, 7, 8, 10, 12):
                last_day = 31
            elif int(m) == 2:
                last_day = 29 if (int(y) % 4 == 0 and (int(y) % 100 != 0 or int(y) % 400 == 0)) else 28
            return f"{y}-{int(m):02d}-01", f"{y}-{int(m):02d}-{last_day:02d}", f"📅 {y}年{int(m)}月"

        date_match = re.match(r'^(\d{4})-(\d{1,2})-(\d{1,2})$', arg)
        if date_match:
            y, m, d = date_match.groups()
            target = f"{y}-{int(m):02d}-{int(d):02d}"
            return target, target, f"📅 {target}"

        if arg.isdigit():
            n = int(arg)
            end = _today_str()
            start = (now - timedelta(days=n-1)).strftime("%Y-%m-%d")
            return start, end, f"📅 近{n}天 ({start} ~ {end})"

        # 默认近7天
        end = _today_str()
        start = (now - timedelta(days=6)).strftime("%Y-%m-%d")
        return start, end, f"📅 近7天 ({start} ~ {end})"

    def _compute_volume(self, activities: list, type_keys: set, start_date: str, end_date: str) -> dict:
        """通用统计计算，返回 {dist, count, elev, duration, entries: [...]}"""
        result = {"dist": 0.0, "count": 0, "elev": 0.0, "duration": 0.0, "entries": []}
        for act in activities:
            act_type = act.get("activityType", {}).get("typeKey", "")
            if act_type not in type_keys:
                continue
            date_str = (act.get("startTimeLocal", "") or "")[:10]
            if date_str < start_date or date_str > end_date:
                continue
            dist = (act.get("distance", 0) or 0) / 1000
            elev = act.get("elevationGain", 0) or 0
            duration = (act.get("duration", 0) or 0) / 3600
            result["dist"] += dist
            result["count"] += 1
            result["elev"] += elev
            result["duration"] += duration
            result["entries"].append({
                "name": (act.get("activityName", "") or "")[:18],
                "date": date_str,
                "dist": dist,
                "elev": elev,
                "duration": duration,
            })
        return result

    def _volume_report(self, title: str, road: dict, trail: dict = None) -> str:
        """生成统计报告。支持路跑/越野跑分开显示，也支持单一类型"""
        lines = [f"📊 {title}", "━━━━━━━━━━━━━━"]

        if trail is not None:
            # 跑步：分路跑 + 越野跑
            combined_dist = road["dist"] + trail["dist"]
            combined_cnt = road["count"] + trail["count"]
            combined_elev = road["elev"] + trail["elev"]
            combined_dur = road["duration"] + trail["duration"]

            lines.append(f"🏃 路跑: {road['dist']:.2f}km ({road['count']}次)")
            lines.append(f"   ⛰爬升{round(road['elev'])}m ⏱{round(road['duration'], 1)}h")
            lines.append(f"🏔 越野跑: {trail['dist']:.2f}km ({trail['count']}次)")
            lines.append(f"   ⛰爬升{round(trail['elev'])}m ⏱{round(trail['duration'], 1)}h")
            lines.append(f"───")
            lines.append(f"📌 合计: {combined_dist:.2f}km ({combined_cnt}次)")
            lines.append(f"   ⛰爬升{round(combined_elev)}m ⏱{round(combined_dur, 1)}h")
            if combined_cnt > 0:
                lines.append(f"   📏均次{combined_dist/combined_cnt:.2f}km")
        else:
            d = road
            lines.append(f"📏 距离: {d['dist']:.2f}km ({d['count']}次)")
            lines.append(f"⛰ 爬升: {round(d['elev'])}m")
            lines.append(f"⏱ 时长: {round(d['duration'], 1)}h")
            if d['count'] > 0:
                lines.append(f"📏 均次: {d['dist']/d['count']:.2f}km")

        return "\n".join(lines)

    # ─── 跑量 / 徒步 / 步行 / 骑行 / 游泳 ────────────

    @filter.command("跑量")
    async def running_volume(self, event: AstrMessageEvent):
        """查看跑量统计（路跑+越野跑）。用法: /跑量 [all|年份|月份|日期|天数]"""
        try:
            client = await self.client_manager.get_client()
        except Exception as e:
            yield event.plain_result(f"❌ 连接失败: {e}")
            return

        try:
            msg = event.message_str.strip()
            parts = msg.split(maxsplit=1)
            arg = parts[1].strip() if len(parts) >= 2 else ""
            start_date, end_date, label = self._parse_volume_arg(arg)

            activities = client.get_activities(0, 200)
            if not activities:
                yield event.plain_result("❌ 暂无活动数据")
                return

            road = self._compute_volume(activities, {"running"}, start_date, end_date)
            trail = self._compute_volume(activities, {"trail_running"}, start_date, end_date)

            if road["count"] == 0 and trail["count"] == 0:
                yield event.plain_result(f"{label}\n━━━━━━━━━━━━━━\n暂无跑步记录")
                return

            report = f"{label}\n" + self._volume_report("跑量统计", road, trail)
            yield event.plain_result(report)
        except Exception as e:
            logger.error(f"跑量统计失败: {e}", exc_info=True)
            yield event.plain_result(f"❌ 跑量统计失败: {e}")

    @filter.command("徒步")
    async def hiking_volume(self, event: AstrMessageEvent):
        """查看徒步统计。用法: /徒步 [all|年份|月份|日期|天数]"""
        try:
            client = await self.client_manager.get_client()
        except Exception as e:
            yield event.plain_result(f"❌ 连接失败: {e}")
            return

        try:
            msg = event.message_str.strip()
            parts = msg.split(maxsplit=1)
            arg = parts[1].strip() if len(parts) >= 2 else ""
            start_date, end_date, label = self._parse_volume_arg(arg)

            activities = client.get_activities(0, 200)
            if not activities:
                yield event.plain_result("❌ 暂无活动数据")
                return

            stats = self._compute_volume(activities, {"hiking"}, start_date, end_date)

            if stats["count"] == 0:
                yield event.plain_result(f"{label}\n━━━━━━━━━━━━━━\n暂无徒步记录")
                return

            report = f"{label}\n" + self._volume_report("徒步统计", stats)
            yield event.plain_result(report)
        except Exception as e:
            logger.error(f"徒步统计失败: {e}", exc_info=True)
            yield event.plain_result(f"❌ 徒步统计失败: {e}")

    @filter.command("步行")
    async def walking_volume(self, event: AstrMessageEvent):
        """查看步行统计。用法: /步行 [all|年份|月份|日期|天数]"""
        try:
            client = await self.client_manager.get_client()
        except Exception as e:
            yield event.plain_result(f"❌ 连接失败: {e}")
            return

        try:
            msg = event.message_str.strip()
            parts = msg.split(maxsplit=1)
            arg = parts[1].strip() if len(parts) >= 2 else ""
            start_date, end_date, label = self._parse_volume_arg(arg)

            activities = client.get_activities(0, 200)
            if not activities:
                yield event.plain_result("❌ 暂无活动数据")
                return

            stats = self._compute_volume(activities, {"walking"}, start_date, end_date)

            if stats["count"] == 0:
                yield event.plain_result(f"{label}\n━━━━━━━━━━━━━━\n暂无步行记录")
                return

            report = f"{label}\n" + self._volume_report("步行统计", stats)
            yield event.plain_result(report)
        except Exception as e:
            logger.error(f"步行统计失败: {e}", exc_info=True)
            yield event.plain_result(f"❌ 步行统计失败: {e}")

    @filter.command("骑行")
    async def cycling_volume(self, event: AstrMessageEvent):
        """查看骑行统计。用法: /骑行 [all|年份|月份|日期|天数]"""
        try:
            client = await self.client_manager.get_client()
        except Exception as e:
            yield event.plain_result(f"❌ 连接失败: {e}")
            return

        try:
            msg = event.message_str.strip()
            parts = msg.split(maxsplit=1)
            arg = parts[1].strip() if len(parts) >= 2 else ""
            start_date, end_date, label = self._parse_volume_arg(arg)

            activities = client.get_activities(0, 200)
            if not activities:
                yield event.plain_result("❌ 暂无活动数据")
                return

            stats = self._compute_volume(activities, {"cycling"}, start_date, end_date)

            if stats["count"] == 0:
                yield event.plain_result(f"{label}\n━━━━━━━━━━━━━━\n暂无骑行记录")
                return

            report = f"{label}\n" + self._volume_report("骑行统计", stats)
            yield event.plain_result(report)
        except Exception as e:
            logger.error(f"骑行统计失败: {e}", exc_info=True)
            yield event.plain_result(f"❌ 骑行统计失败: {e}")

    @filter.command("游泳")
    async def swimming_volume(self, event: AstrMessageEvent):
        """查看游泳统计。用法: /游泳 [all|年份|月份|日期|天数]"""
        try:
            client = await self.client_manager.get_client()
        except Exception as e:
            yield event.plain_result(f"❌ 连接失败: {e}")
            return

        try:
            msg = event.message_str.strip()
            parts = msg.split(maxsplit=1)
            arg = parts[1].strip() if len(parts) >= 2 else ""
            start_date, end_date, label = self._parse_volume_arg(arg)

            activities = client.get_activities(0, 200)
            if not activities:
                yield event.plain_result("❌ 暂无活动数据")
                return

            stats = self._compute_volume(activities, {"swimming", "lap_swimming", "open_water_swimming"}, start_date, end_date)

            if stats["count"] == 0:
                yield event.plain_result(f"{label}\n━━━━━━━━━━━━━━\n暂无游泳记录")
                return

            report = f"{label}\n" + self._volume_report("游泳统计", stats)
            yield event.plain_result(report)
        except Exception as e:
            logger.error(f"游泳统计失败: {e}", exc_info=True)
            yield event.plain_result(f"❌ 游泳统计失败: {e}")

    @filter.command("PB")
    @filter.command("pb")
    @filter.command("Pb")
    @filter.command("pB")
    async def personal_best(self, event: AstrMessageEvent):
        """查看个人最佳记录"""
        try:
            client = await self.client_manager.get_client()
        except Exception as e:
            yield event.plain_result(f"❌ 连接失败: {e}")
            return

        try:
            activities = client.get_activities(0, 200)
            if not activities:
                yield event.plain_result("❌ 暂无活动数据")
                return

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
                    max_dist = dist; max_dist_info = (date, name)
                if speed > 0:
                    pace = 1000 / speed / 60
                    if max_pace_val == 0 or pace < max_pace_val:
                        max_pace_val = pace; max_pace_info = (date, name)
                if elev > max_elev:
                    max_elev = elev; max_elev_info = (date, name)
                dur_h = duration / 3600
                if dur_h > max_dur:
                    max_dur = dur_h; max_dur_info = (date, name)

            pace_str = f"{max_pace_val:.2f}min/km" if max_pace_val > 0 else "N/A"

            report = (
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
            yield event.plain_result(report)
        except Exception as e:
            logger.error(f"PB统计失败: {e}", exc_info=True)
            yield event.plain_result(f"❌ PB统计失败: {e}")

    @filter.command("年度报告")
    async def yearly_stats(self, event: AstrMessageEvent):
        """查看年度运动报告。用法: /年度报告 (默认今年) | /年度报告 2025"""
        try:
            client = await self.client_manager.get_client()
        except Exception as e:
            yield event.plain_result(f"❌ 连接失败: {e}")
            return

        try:
            msg = event.message_str.strip()
            parts = msg.split(maxsplit=1)
            arg = parts[1].strip() if len(parts) >= 2 else ""

            now_year = datetime.now().year
            target_year = now_year

            if arg:
                year_match = re.search(r'(\d{4})', arg)
                if year_match:
                    target_year = int(year_match.group(1))

            activities = client.get_activities(0, 200)
            if not activities:
                yield event.plain_result("❌ 暂无活动数据")
                return

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
                yield event.plain_result(f"📅 {target_year}年暂无可统计的活动")
                return

            month_lines = [f"  {m}月: {monthly[m]:.1f}km" for m in range(1, 13) if monthly[m] > 0]

            report = (
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
            yield event.plain_result(report)
        except Exception as e:
            logger.error(f"年度统计失败: {e}", exc_info=True)
            yield event.plain_result(f"❌ 年度统计失败: {e}")

