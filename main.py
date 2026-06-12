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

# 子类型中文别名 → Garmin typeKey 精确匹配（用于 /活动 子类型筛选）
SUBTYPE_ALIAS = {
    # ── 跑步类 ──
    "跑步":       "running",
    "路跑":       "street_running",
    "场地跑":     "track_running",
    "室内跑":     "indoor_running",
    "跑步机":     "treadmill_running",
    "虚拟跑":     "virtual_run",
    "越野跑":     "trail_running",
    "超马":       "ultra_run",
    "障碍跑":     "obstacle_run",
    # ── 徒步类 ──
    "徒步":       "hiking",
    "负重徒步":   "rucking",
    # ── 步行类 ──
    "步行":       "walking",
    "竞走":       "speed_walking",
    "散步":       "casual_walking",
    # ── 骑行类 ──
    "骑行":       "cycling",
    "公路车":     "road_biking",
    "公路自行车": "road_biking",
    "山地车":     "mountain_biking",
    "山地自行车": "mountain_biking",
    "gravel":     "gravel_cycling",
    "室内骑行":   "indoor_cycling",
    "室内自行车": "indoor_cycling",
    "bmx":        "bmx",
    "电动自行车": "e_bike_fitness",
    "速降":       "downhill_biking",
    "躺车":       "recumbent_cycling",
    "公路越野":   "cyclocross",
    "虚拟骑行":   "virtual_ride",
    "场地自行车": "track_cycling",
    "手摇自行车": "hand_cycling",
    "室内手摇":   "indoor_hand_cycling",
    "e-enduro":   "e_enduro_mtb",
    "enduro":     "enduro_mtb",
    "e-mtb":      "e_bike_mountain",
    # ── 游泳类 ──
    "游泳":       "swimming",
    "泳池":       "lap_swimming",
    "泳池游泳":   "lap_swimming",
    "公开水域":   "open_water_swimming",
}


@register("astrbot_plugin_garmin_health", "Jonathan-614", "佳明健康看板 - 通过Garmin Connect查询健康数据（心率、睡眠、步数、活动统计等）并生成分析报告，支持自然语言查询", "1.0.2")
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

    @filter.command("garmin", alias={"Garmin", "GARMIN"})
    async def garmin_help(self, event: AstrMessageEvent):
        """显示插件帮助信息"""
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
            "    /活动 all: 取全部活动记录（不限类型）\n"
            "    /活动 子类型: 按子类型筛选，如 /活动 越野跑 2026、/活动 公路车 5、/活动 泳池\n"
            "    /活动 子类型 all: 取全部该类型活动，如 /活动 跑步 all\n"
            "    🏷 支持子类型：\n"
            "      🏃 跑步/路跑/场地跑/室内跑/跑步机/虚拟跑/越野跑/超马/障碍跑\n"
            "      🥾 徒步/负重徒步\n"
            "      🚶 步行/竞走/散步\n"
            "      🚴 骑行/公路车/山地车/gravel/室内骑行/bmx/电动自行车/速降/躺车/公路越野/虚拟骑行/场地自行车/手摇自行车/室内手摇/e-enduro/enduro/e-mtb\n"
            "      🏊 游泳/泳池/公开水域\n"
            "  /跑步 [参数] — 跑步统计（九类细分：跑步/室内跑步/场地跑步/虚拟跑步/路跑/超马/越野跑/跑步机/障碍跑）\n"
            "    /跑步         近7天\n"
            "    /跑步 all     全部记录\n"
            "    /跑步 2025    全年\n"
            "    /跑步 2025-06 整月\n"
            "    /跑步 2025-06-08 单日\n"
            "    /跑步 30      近30天\n"
            "  /徒步 [参数] — 徒步统计（徒步+负重徒步），参数规则同 /跑步\n"
            "  /步行 [参数] — 步行统计（步行+散步+竞走），参数规则同 /跑步\n"
            "  /骑行 [参数] — 骑行统计（17类细分：骑行/公路骑行/碎石未铺路/越野骑行/山地骑行/下坡山地/Enduro山地/小轮车/室内骑行/虚拟骑行/电动自行车/电助力山地车/eEnduro山地/场地骑行/手轮车/室内手轮车/躺车骑行），参数规则同 /跑步\n"
            "  /游泳 [参数] — 游泳统计，参数规则同 /跑步\n"
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
        """今日健康概览（步数/心率/睡眠）"""
        result = await health_today_data(self.client_manager)()
        yield event.plain_result(result)

    @filter.command("心率")
    async def heart_rate_report(self, event: AstrMessageEvent):
        """近7天心率趋势（天数，默认7天）"""
        result = await health_heart_rate_days(self.client_manager, 7)()
        yield event.plain_result(result)

    @filter.command("睡眠")
    async def sleep_report(self, event: AstrMessageEvent):
        """近7天睡眠报告（天数，默认7天）"""
        result = await health_sleep_days(self.client_manager, 7)()
        yield event.plain_result(result)

    @filter.command("步数")
    async def steps_report(self, event: AstrMessageEvent):
        """近7天步数数据（天数，默认7天）"""
        result = await health_steps_days(self.client_manager, 7)()
        yield event.plain_result(result)

    @filter.command("身体报告")
    async def detailed_report(self, event: AstrMessageEvent):
        """综合健康诊断报告（7天平均与建议）"""
        result = await detailed_health_report(self.client_manager)()
        yield event.plain_result(result)

    # ═══════════════════════════════════════════
    # 活动查询命令
    # ═══════════════════════════════════════════

    @filter.command("活动")
    async def recent_activities(self, event: AstrMessageEvent):
        """查看活动记录（日期/关键词/数量/子类型）"""
        msg = event.message_str.strip()
        parts = msg.split(maxsplit=1)
        arg = parts[1].strip() if len(parts) >= 2 else ""

        # ── 子类型别名解析：第一个 token 匹配则提取 typeKey ──
        subtype_typekey = None
        subtype_label = ""
        if arg:
            _sp = arg.find(" ")
            first_token = arg[:_sp].strip().lower() if _sp != -1 else arg.strip().lower()
            rest = arg[_sp:].strip() if _sp != -1 else ""
            if first_token in SUBTYPE_ALIAS:
                subtype_typekey = SUBTYPE_ALIAS[first_token]
                subtype_label = first_token
                arg = rest  # 剩余参数继续走原有解析

        # 裸 all → 取全部活动（不限类型）
        if not subtype_typekey and arg and arg.strip().lower() == "all":
            activities = await get_filtered_activities(
                self.client_manager, max_count=9999,
            )()
            if not activities:
                yield event.plain_result("❌ 暂无活动记录")
                return
            result = activities_report(activities, f"🏃 全部活动记录 共{len(activities)}条")
            yield event.plain_result(result)
            return

        # 子类型 + "all" → 取全部该类型活动
        if subtype_typekey and arg and arg.strip().lower() == "all":
            activities = await get_filtered_activities(
                self.client_manager, max_count=9999,
                activity_type=subtype_typekey,
            )()
            if not activities:
                yield event.plain_result(f"[{subtype_label}] 暂无活动记录")
                return
            result = activities_report(activities, f"[{subtype_label}] 全部活动记录 共{len(activities)}条")
            yield event.plain_result(result)
            return

        try:
            if not arg:
                # 默认最近 5 条
                activities = await get_filtered_activities(
                    self.client_manager, max_count=5,
                    activity_type=subtype_typekey,
                )()
            elif re.fullmatch(r'\d{4}', arg):
                # 四位数字优先按年份处理，避免 /活动 2026 被误判为近2026条
                y = int(arg)
                start = f"{y:04d}-01-01"
                end = f"{y:04d}-12-31"
                label = f"📅 {y}年"
                activities = await get_filtered_activities(
                    self.client_manager, start_date=start, end_date=end,
                    activity_type=subtype_typekey,
                )()
                if not activities:
                    yield event.plain_result(f"{label} 暂无活动记录")
                    return
                _sub_pre = f"[{subtype_label}] " if subtype_label else ""
                result = activities_report(activities, f"{_sub_pre}{label} 共{len(activities)}条活动")
                yield event.plain_result(result)
                return
            elif arg.isdigit():
                n = min(int(arg), 200)
                activities = await get_filtered_activities(
                    self.client_manager, max_count=n,
                    activity_type=subtype_typekey,
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
                        self.client_manager, start_date=start, end_date=end,
                        activity_type=subtype_typekey,
                    )()
                    if not activities:
                        yield event.plain_result(f"{label} 暂无活动记录")
                        return
                    _sub_pre = f"[{subtype_label}] " if subtype_label else ""
                    result = activities_report(activities, f"{_sub_pre}{label} 共{len(activities)}条活动")
                    yield event.plain_result(result)
                    return
                # 单日：2026-06-08 / 2026年6月8日 / 2026/06/08
                date_match = re.search(r'(\d{4})[年/-]?(\d{1,2})[月/-]?(\d{1,2})日?', arg)
                if date_match:
                    y, m, d = date_match.groups()
                    target = f"{y}-{int(m):02d}-{int(d):02d}"
                    activities = await get_filtered_activities(
                        self.client_manager, start_date=target, end_date=target,
                        activity_type=subtype_typekey,
                    )()
                    if not activities:
                        yield event.plain_result(f"📅 {target} 暂无活动记录")
                        return
                    _sub_pre = f"[{subtype_label}] " if subtype_label else ""
                    result = activities_report(activities, f"{_sub_pre}📅 {target} 共{len(activities)}条活动")
                    yield event.plain_result(result)
                    return
                else:
                    # 按活动名模糊搜索（可与子类型筛选叠加）
                    activities = await get_filtered_activities(
                        self.client_manager, keyword=arg, max_count=20,
                        activity_type=subtype_typekey,
                    )()

            if not activities:
                yield event.plain_result("❌ 暂无活动数据")
                return

            _sub_pre = f"[{subtype_label}] " if subtype_label else ""
            if not arg or (arg.isdigit() and not re.fullmatch(r'\d{4}', arg)):
                header = f"{_sub_pre}🏃 最近{len(activities)}条活动"
            else:
                header = f"{_sub_pre}🔍 搜索「{arg}」共{len(activities)}条"
            result = activities_report(activities, header)
            yield event.plain_result(result)
        except Exception as e:
            logger.error(f"获取活动失败: {e}", exc_info=True)
            yield event.plain_result(f"❌ 获取活动失败: {e}")

    # ═══════════════════════════════════════════
    # 运动量统计命令（跑步/徒步/步行/骑行/游泳）
    # ═══════════════════════════════════════════

    @filter.command("跑步")
    async def running_volume(self, event: AstrMessageEvent):
        """跑步统计（路跑/越野跑/室内跑等九类细分）"""
        msg = event.message_str.strip()
        parts = msg.split(maxsplit=1)
        arg = parts[1].strip() if len(parts) >= 2 else ""
        try:
            start_date, end_date, label = parse_volume_arg(arg)
            activities = await self.client_manager.get_activities()
            if not activities:
                yield event.plain_result("❌ 暂无活动数据")
                return
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
                yield event.plain_result(f"{label}\n━━━━━━━━━━━━━━\n暂无跑步记录")
                return
            yield event.plain_result(f"{label}\n" + build_volume_report("跑步统计", running=running, street_running=street_run, track_running=track_run, indoor_running=indoor_run, treadmill_running=treadmill, virtual_running=virtual_run, trail_running=trail_run, ultra_running=ultra_run, obstacle_racing=obstacle))
        except Exception as e:
            logger.error(f"跑步统计失败: {e}", exc_info=True)
            yield event.plain_result(f"❌ 跑步统计失败: {e}")

    @filter.command("徒步")
    async def hike_volume(self, event: AstrMessageEvent):
        """徒步统计（徒步+负重徒步）"""
        msg = event.message_str.strip()
        parts = msg.split(maxsplit=1)
        arg = parts[1].strip() if len(parts) >= 2 else ""
        try:
            start_date, end_date, label = parse_volume_arg(arg)
            activities = await self.client_manager.get_activities()
            if not activities:
                yield event.plain_result("❌ 暂无活动数据")
                return
            hike_normal = compute_volume(activities, {"hiking"}, start_date, end_date)
            hike_ruck = compute_volume(activities, {"rucking"}, start_date, end_date)
            if hike_normal["count"] == 0 and hike_ruck["count"] == 0:
                yield event.plain_result(f"{label}\n━━━━━━━━━━━━━━\n暂无徒步记录")
                return
            yield event.plain_result(f"{label}\n" + build_volume_report("徒步统计", hike_normal=hike_normal, hike_ruck=hike_ruck))
        except Exception as e:
            logger.error(f"徒步统计失败: {e}", exc_info=True)
            yield event.plain_result(f"❌ 徒步统计失败: {e}")

    @filter.command("步行")
    async def walk_volume(self, event: AstrMessageEvent):
        """步行统计（步行+散步+竞走）"""
        msg = event.message_str.strip()
        parts = msg.split(maxsplit=1)
        arg = parts[1].strip() if len(parts) >= 2 else ""
        try:
            start_date, end_date, label = parse_volume_arg(arg)
            activities = await self.client_manager.get_activities()
            if not activities:
                yield event.plain_result("❌ 暂无活动数据")
                return
            walk_normal = compute_volume(activities, {"walking"}, start_date, end_date)
            walk_casual = compute_volume(activities, {"casual_walking"}, start_date, end_date)
            walk_speed = compute_volume(activities, {"speed_walking"}, start_date, end_date)
            if walk_normal["count"] == 0 and walk_casual["count"] == 0 and walk_speed["count"] == 0:
                yield event.plain_result(f"{label}\n━━━━━━━━━━━━━━\n暂无步行记录")
                return
            yield event.plain_result(f"{label}\n" + build_volume_report("步行统计", walk_normal=walk_normal, walk_casual=walk_casual, walk_speed=walk_speed))
        except Exception as e:
            logger.error(f"步行统计失败: {e}", exc_info=True)
            yield event.plain_result(f"❌ 步行统计失败: {e}")

    @filter.command("骑行")
    async def cycling_volume(self, event: AstrMessageEvent):
        """骑行统计（公路车/山地车/室内骑行等17类细分）"""
        msg = event.message_str.strip()
        parts = msg.split(maxsplit=1)
        arg = parts[1].strip() if len(parts) >= 2 else ""
        try:
            start_date, end_date, label = parse_volume_arg(arg)
            activities = await self.client_manager.get_activities()
            if not activities:
                yield event.plain_result("❌ 暂无活动数据")
                return
            cycling_downhill = compute_volume(activities, {"downhill_biking"}, start_date, end_date)
            cycling_recumbent = compute_volume(activities, {"recumbent_cycling"}, start_date, end_date)
            cycling_cyclocross = compute_volume(activities, {"cyclocross"}, start_date, end_date)
            cycling_virtual = compute_volume(activities, {"virtual_ride"}, start_date, end_date)
            cycling_gravel = compute_volume(activities, {"gravel_cycling"}, start_date, end_date)
            cycling_emtb = compute_volume(activities, {"e_bike_mountain"}, start_date, end_date)
            cycling_ebike = compute_volume(activities, {"e_bike_fitness"}, start_date, end_date)
            cycling_hand = compute_volume(activities, {"hand_cycling"}, start_date, end_date)
            cycling_mountain = compute_volume(activities, {"mountain_biking"}, start_date, end_date)
            cycling_bmx = compute_volume(activities, {"bmx"}, start_date, end_date)
            cycling_indoor = compute_volume(activities, {"indoor_cycling"}, start_date, end_date)
            cycling_indoor_hand = compute_volume(activities, {"indoor_hand_cycling"}, start_date, end_date)
            cycling_track = compute_volume(activities, {"track_cycling"}, start_date, end_date)
            cycling_road = compute_volume(activities, {"road_biking"}, start_date, end_date)
            cycling_enduro = compute_volume(activities, {"enduro_mtb"}, start_date, end_date)
            cycling_eenduro = compute_volume(activities, {"e_enduro_mtb"}, start_date, end_date)
            cycling_generic = compute_volume(activities, {"cycling"}, start_date, end_date)
            all_zero = all(d["count"] == 0 for d in [cycling_downhill, cycling_recumbent, cycling_cyclocross, cycling_virtual, cycling_gravel, cycling_emtb, cycling_ebike, cycling_hand, cycling_mountain, cycling_bmx, cycling_indoor, cycling_indoor_hand, cycling_track, cycling_road, cycling_enduro, cycling_eenduro, cycling_generic])
            if all_zero:
                yield event.plain_result(f"{label}\n━━━━━━━━━━━━━━\n暂无骑行记录")
                return
            yield event.plain_result(f"{label}\n" + build_volume_report("骑行统计", cycling_downhill=cycling_downhill, cycling_recumbent=cycling_recumbent, cycling_cyclocross=cycling_cyclocross, cycling_virtual=cycling_virtual, cycling_gravel=cycling_gravel, cycling_emtb=cycling_emtb, cycling_ebike=cycling_ebike, cycling_hand=cycling_hand, cycling_mountain=cycling_mountain, cycling_bmx=cycling_bmx, cycling_indoor=cycling_indoor, cycling_indoor_hand=cycling_indoor_hand, cycling_track=cycling_track, cycling_road=cycling_road, cycling_enduro=cycling_enduro, cycling_eenduro=cycling_eenduro, cycling_generic=cycling_generic))
        except Exception as e:
            logger.error(f"骑行统计失败: {e}", exc_info=True)
            yield event.plain_result(f"❌ 骑行统计失败: {e}")

    @filter.command("游泳")
    async def swimming_volume(self, event: AstrMessageEvent):
        """游泳统计（通用/泳池/公开水域）"""
        msg = event.message_str.strip()
        parts = msg.split(maxsplit=1)
        arg = parts[1].strip() if len(parts) >= 2 else ""
        try:
            start_date, end_date, label = parse_volume_arg(arg)
            activities = await self.client_manager.get_activities()
            if not activities:
                yield event.plain_result("❌ 暂无活动数据")
                return
            swim_generic = compute_volume(activities, {"swimming"}, start_date, end_date)
            swim_pool = compute_volume(activities, {"pool_swim", "lap_swimming"}, start_date, end_date)
            swim_open = compute_volume(activities, {"open_water_swimming"}, start_date, end_date)
            all_zero = all(d["count"] == 0 for d in [swim_generic, swim_pool, swim_open])
            if all_zero:
                yield event.plain_result(f"{label}\n━━━━━━━━━━━━━━\n暂无游泳记录")
                return
            yield event.plain_result(f"{label}\n" + build_volume_report("游泳统计", swim_generic=swim_generic, swim_pool=swim_pool, swim_open=swim_open))
        except Exception as e:
            logger.error(f"游泳统计失败: {e}", exc_info=True)
            yield event.plain_result(f"❌ 游泳统计失败: {e}")

    # ═══════════════════════════════════════════
    # 个人最佳 / 年度报告
    # ═══════════════════════════════════════════

    @filter.command("PB", alias={"pb", "Pb", "pB"})
    async def personal_best(self, event: AstrMessageEvent):
        """个人最佳记录（最长距离/配速/爬升/时长）"""
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
