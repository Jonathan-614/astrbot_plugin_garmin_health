"""
佳明健康看板
通过 Garmin Connect 查询健康数据（心率、睡眠、步数、活动统计等）并生成分析报告

双模式架构：
  🏛 固定命令 — 保留全部 /xxx 命令，兼容老用户习惯
  🧠 工具链调用 — 注册 FunctionTool，大模型可自动调用，支持自然语言灵活查询

架构：main.py 只负责命令路由与参数解析，业务逻辑在 services.py 中。
"""

import calendar
import os
import re
from datetime import datetime, timedelta

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger

from .client_manager import GarminClientManager
from .tools import create_all_tools
from .utils import parse_volume_arg
from .services import (
    health_today_data,
    health_heart_rate_days,
    health_sleep_days,
    health_steps_days,
    detailed_health_report,
    get_filtered_activities,
    activities_report,
    compute_volume,
    build_volume_report,
    personal_best_report,
    yearly_report,
)


@register("astrbot_plugin_garmin_health", "Jonathan-614", "佳明健康看板 - 通过Garmin Connect查询健康数据（心率、睡眠、步数、活动统计等）并生成分析报告，支持自然语言查询", "1.0.1")
class GarminHealthPlugin(Star):
    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        self.config = config or {}
        session_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), ".garmin_session"
        )
        self.client_manager = GarminClientManager(self.config, session_dir)
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
    # 帮助
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
            "    /活动 日期: 按日期筛选（支持 2026 全年 / 2026-06 整月 / 2026年6月 中文月 / 2026-06-08 单日 / 2026年6月8日 中文单日 / 2026/06/08 斜杠单日）\n"
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

    # ═══════════════════════════════════════════
    # 健康数据命令
    # ═══════════════════════════════════════════

    @filter.command("健康")
    async def health_today(self, event: AstrMessageEvent):
        """今日健康概览（步数/心率/睡眠）。无参数，直接查询当日数据。"""
        result = await health_today_data(self.client_manager)()
        yield event.plain_result(result)

    @filter.command("心率")
    async def heart_rate_report(self, event: AstrMessageEvent):
        """最近7天心率趋势。参数：days（天数，默认7天）。"""
        result = await health_heart_rate_days(self.client_manager, 7)()
        yield event.plain_result(result)

    @filter.command("睡眠")
    async def sleep_report(self, event: AstrMessageEvent):
        """最近7天睡眠报告。参数：days（天数，默认7天）。"""
        result = await health_sleep_days(self.client_manager, 7)()
        yield event.plain_result(result)

    @filter.command("步数")
    async def steps_report(self, event: AstrMessageEvent):
        """最近7天步数数据。参数：days（天数，默认7天）。"""
        result = await health_steps_days(self.client_manager, 7)()
        yield event.plain_result(result)

    @filter.command("身体报告")
    async def detailed_report(self, event: AstrMessageEvent):
        """综合健康诊断报告（含7天平均和建议）"""
        result = await detailed_health_report(self.client_manager)()
        yield event.plain_result(result)

    # ═══════════════════════════════════════════
    # 活动查询命令
    # ═══════════════════════════════════════════

    @filter.command("活动")
    async def recent_activities(self, event: AstrMessageEvent):
        """查看活动记录（支持按日期/关键词/数量筛选）"""
        msg = event.message_str.strip()
        parts = msg.split(maxsplit=1)
        arg = parts[1].strip() if len(parts) >= 2 else ""

        try:
            if not arg:
                # 默认最近 5 条
                activities = await get_filtered_activities(
                    self.client_manager, max_count=5
                )()
            elif re.fullmatch(r'\d{4}', arg):
                # 四位数字优先按年份处理，避免 /活动 2026 被误判为近2026条
                y = int(arg)
                start = f"{y:04d}-01-01"
                end = f"{y:04d}-12-31"
                label = f"📅 {y}年"
                activities = await get_filtered_activities(
                    self.client_manager, start_date=start, end_date=end
                )()
                if not activities:
                    yield event.plain_result(f"{label} 暂无活动记录")
                    return
                result = activities_report(activities, f"{label} 共{len(activities)}条活动")
                yield event.plain_result(result)
                return
            elif arg.isdigit():
                n = min(int(arg), 200)
                activities = await get_filtered_activities(
                    self.client_manager, max_count=n
                )()
            else:
                # 按日期筛选：整月→单日，最后兜底模糊搜索
                # 整月：2026-06 / 2026/06 / 2026年6月
                month_match = re.fullmatch(r'(\d{4})[年/\-](\d{1,2})月?', arg)
                if month_match:
                    y, m = map(int, month_match.groups())
                    last_day = calendar.monthrange(y, m)[1]
                    start = f"{y:04d}-{m:02d}-01"
                    end = f"{y:04d}-{m:02d}-{last_day:02d}"
                    label = f"📅 {y}年{m}月"
                    activities = await get_filtered_activities(
                        self.client_manager, start_date=start, end_date=end
                    )()
                    if not activities:
                        yield event.plain_result(f"{label} 暂无活动记录")
                        return
                    result = activities_report(activities, f"{label} 共{len(activities)}条活动")
                    yield event.plain_result(result)
                    return
                # 单日：2026-06-08 / 2026年6月8日 / 2026/06/08
                date_match = re.search(r'(\d{4})[年/-]?(\d{1,2})[月/-]?(\d{1,2})日?', arg)
                if date_match:
                    y, m, d = date_match.groups()
                    target = f"{y}-{int(m):02d}-{int(d):02d}"
                    activities = await get_filtered_activities(
                        self.client_manager, start_date=target, end_date=target
                    )()
                    if not activities:
                        yield event.plain_result(f"📅 {target} 暂无活动记录")
                        return
                    result = activities_report(activities, f"📅 {target} 共{len(activities)}条活动")
                    yield event.plain_result(result)
                    return
                else:
                    # 按活动名模糊搜索
                    activities = await get_filtered_activities(
                        self.client_manager, keyword=arg, max_count=20
                    )()

            if not activities:
                yield event.plain_result("❌ 暂无活动数据")
                return

            header = f"🏃 最近{len(activities)}条活动" if (not arg or (arg.isdigit() and not re.fullmatch(r'\d{4}', arg))) else f"🔍 搜索「{arg}」共{len(activities)}条"
            result = activities_report(activities, header)
            yield event.plain_result(result)
        except Exception as e:
            logger.error(f"获取活动失败: {e}", exc_info=True)
            yield event.plain_result(f"❌ 获取活动失败: {e}")

    # ═══════════════════════════════════════════
    # 运动量统计命令（跑量/徒步/步行/骑行/游泳）
    # ═══════════════════════════════════════════

    @filter.command("跑量")
    async def running_volume(self, event: AstrMessageEvent):
        """跑量统计（路跑+越野跑，支持按日期筛选）"""
        msg = event.message_str.strip()
        parts = msg.split(maxsplit=1)
        arg = parts[1].strip() if len(parts) >= 2 else ""
        try:
            start_date, end_date, label = parse_volume_arg(arg)
            activities = await self.client_manager.get_activities()
            if not activities:
                yield event.plain_result("❌ 暂无活动数据")
                return
            road = compute_volume(activities, {"running"}, start_date, end_date)
            trail = compute_volume(activities, {"trail_running"}, start_date, end_date)
            if road["count"] == 0 and trail["count"] == 0:
                yield event.plain_result(f"{label}\n━━━━━━━━━━━━━━\n暂无跑步记录")
                return
            yield event.plain_result(f"{label}\n" + build_volume_report("跑量统计", road=road, trail=trail))
        except Exception as e:
            logger.error(f"跑量统计失败: {e}", exc_info=True)
            yield event.plain_result(f"❌ 跑量统计失败: {e}")

    @filter.command("徒步")
    async def hiking_volume(self, event: AstrMessageEvent):
        """徒步统计（支持按日期筛选）"""
        msg = event.message_str.strip()
        parts = msg.split(maxsplit=1)
        arg = parts[1].strip() if len(parts) >= 2 else ""
        try:
            start_date, end_date, label = parse_volume_arg(arg)
            activities = await self.client_manager.get_activities()
            if not activities:
                yield event.plain_result("❌ 暂无活动数据")
                return
            stats = compute_volume(activities, {"hiking"}, start_date, end_date)
            if stats["count"] == 0:
                yield event.plain_result(f"{label}\n━━━━━━━━━━━━━━\n暂无徒步记录")
                return
            yield event.plain_result(f"{label}\n" + build_volume_report("徒步统计", single=stats))
        except Exception as e:
            logger.error(f"徒步统计失败: {e}", exc_info=True)
            yield event.plain_result(f"❌ 徒步统计失败: {e}")

    @filter.command("步行")
    async def walking_volume(self, event: AstrMessageEvent):
        """步行统计（支持按日期筛选）"""
        msg = event.message_str.strip()
        parts = msg.split(maxsplit=1)
        arg = parts[1].strip() if len(parts) >= 2 else ""
        try:
            start_date, end_date, label = parse_volume_arg(arg)
            activities = await self.client_manager.get_activities()
            if not activities:
                yield event.plain_result("❌ 暂无活动数据")
                return
            stats = compute_volume(activities, {"walking"}, start_date, end_date)
            if stats["count"] == 0:
                yield event.plain_result(f"{label}\n━━━━━━━━━━━━━━\n暂无步行记录")
                return
            yield event.plain_result(f"{label}\n" + build_volume_report("步行统计", single=stats))
        except Exception as e:
            logger.error(f"步行统计失败: {e}", exc_info=True)
            yield event.plain_result(f"❌ 步行统计失败: {e}")

    @filter.command("骑行")
    async def cycling_volume(self, event: AstrMessageEvent):
        """骑行统计（支持按日期筛选）"""
        msg = event.message_str.strip()
        parts = msg.split(maxsplit=1)
        arg = parts[1].strip() if len(parts) >= 2 else ""
        try:
            start_date, end_date, label = parse_volume_arg(arg)
            activities = await self.client_manager.get_activities()
            if not activities:
                yield event.plain_result("❌ 暂无活动数据")
                return
            stats = compute_volume(activities, {"cycling"}, start_date, end_date)
            if stats["count"] == 0:
                yield event.plain_result(f"{label}\n━━━━━━━━━━━━━━\n暂无骑行记录")
                return
            yield event.plain_result(f"{label}\n" + build_volume_report("骑行统计", single=stats))
        except Exception as e:
            logger.error(f"骑行统计失败: {e}", exc_info=True)
            yield event.plain_result(f"❌ 骑行统计失败: {e}")

    @filter.command("游泳")
    async def swimming_volume(self, event: AstrMessageEvent):
        """游泳统计（支持按日期筛选）"""
        msg = event.message_str.strip()
        parts = msg.split(maxsplit=1)
        arg = parts[1].strip() if len(parts) >= 2 else ""
        try:
            start_date, end_date, label = parse_volume_arg(arg)
            activities = await self.client_manager.get_activities()
            if not activities:
                yield event.plain_result("❌ 暂无活动数据")
                return
            stats = compute_volume(activities, {"swimming", "lap_swimming", "open_water_swimming"}, start_date, end_date)
            if stats["count"] == 0:
                yield event.plain_result(f"{label}\n━━━━━━━━━━━━━━\n暂无游泳记录")
                return
            yield event.plain_result(f"{label}\n" + build_volume_report("游泳统计", single=stats))
        except Exception as e:
            logger.error(f"游泳统计失败: {e}", exc_info=True)
            yield event.plain_result(f"❌ 游泳统计失败: {e}")

    # ═══════════════════════════════════════════
    # 个人最佳 / 年度报告
    # ═══════════════════════════════════════════

    @filter.command("PB")
    @filter.command("pb")
    @filter.command("Pb")
    @filter.command("pB")
    async def personal_best(self, event: AstrMessageEvent):
        """个人最佳记录（最长距离/最快配速/最大爬升/最长时长）"""
        result = await personal_best_report(self.client_manager)()
        yield event.plain_result(result)

    @filter.command("年度报告")
    async def yearly_stats(self, event: AstrMessageEvent):
        """年度运动报告（总活动/距离/时长/爬升/月度分布）"""
        msg = event.message_str.strip()
        parts = msg.split(maxsplit=1)
        arg = parts[1].strip() if len(parts) >= 2 else ""

        target_year = datetime.now().year
        if arg:
            year_match = re.search(r'(\d{4})', arg)
            if year_match:
                target_year = int(year_match.group(1))

        result = await yearly_report(self.client_manager, target_year)()
        yield event.plain_result(result)
