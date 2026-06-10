"""Garmin Health 插件公共工具函数。"""

from datetime import datetime, timedelta
from typing import Optional
import calendar
import re


def safe_float(value, default: float = 0.0) -> float:
    """把 Garmin 返回的数字字段安全转成 float，兼容 None/字符串/N/A。"""
    try:
        if value in (None, "", "N/A"):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def clamp_int(value, default: int, min_value: int, max_value: int) -> int:
    """把 LLM/配置传入的数字参数安全限制在指定范围内。"""
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = default
    return max(min_value, min(value, max_value))


def format_pace(pace_min_per_km: float) -> str:
    """把十进制配速分钟格式化为跑者习惯的 M'SS\"/km。"""
    try:
        pace = float(pace_min_per_km)
    except (TypeError, ValueError):
        return "N/A"
    if pace <= 0 or pace >= 60:
        return "N/A"
    total_seconds = int(round(pace * 60))
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return f"{minutes}'{seconds:02d}\"/km"


def pace_from_speed(avg_speed_mps) -> str:
    """用 Garmin averageSpeed(m/s) 计算并格式化配速。"""
    speed = safe_float(avg_speed_mps)
    if speed <= 0:
        return "N/A"
    return format_pace(1000 / speed / 60)


def normalize_date(value: Optional[str], field_name: str, *, end_of_period: bool = False) -> Optional[str]:
    """校验并规范化日期参数为 YYYY-MM-DD。

    支持格式：YYYY-MM-DD、YYYY-MM、YYYY。end_of_period=True 时，年月/年份补到月末/年末。
    """
    if not value:
        return None
    value = str(value).strip().replace("/", "-")
    try:
        dt = datetime.strptime(value, "%Y-%m-%d")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        pass
    try:
        dt = datetime.strptime(value, "%Y-%m")
        if end_of_period:
            last_day = calendar.monthrange(dt.year, dt.month)[1]
            return f"{dt.year:04d}-{dt.month:02d}-{last_day:02d}"
        return dt.strftime("%Y-%m-01")
    except ValueError:
        pass
    try:
        dt = datetime.strptime(value, "%Y")
        return f"{dt.year:04d}-12-31" if end_of_period else f"{dt.year:04d}-01-01"
    except ValueError:
        pass
    raise ValueError(f"{field_name} 日期格式应为 YYYY-MM-DD、YYYY-MM 或 YYYY")


def normalize_date_range(start_date: Optional[str], end_date: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """规范化日期范围。

    - 只传 start_date=2026：返回 2026-01-01 ~ 2026-12-31
    - 只传 start_date=2026-06：返回 2026-06-01 ~ 2026-06-30
    - 只传 end_date=2026-06：返回 None ~ 2026-06-30
    - start_date > end_date：抛出 ValueError，避免误统计全部数据
    """
    if start_date is None and end_date is None:
        return None, None

    sd = normalize_date(start_date, "start_date") if start_date else None
    ed = normalize_date(end_date, "end_date", end_of_period=True) if end_date else None

    if start_date and end_date is None:
        s_val = str(start_date).strip().replace("/", "-")
        if re.fullmatch(r"\d{4}", s_val):
            ed = f"{int(s_val):04d}-12-31"
        elif re.fullmatch(r"\d{4}-\d{1,2}", s_val):
            y, m = map(int, s_val.split("-"))
            ed = f"{y:04d}-{m:02d}-{calendar.monthrange(y, m)[1]:02d}"
        else:
            ed = sd

    if sd is not None and ed is not None and sd > ed:
        raise ValueError("start_date 不能晚于 end_date")
    return sd, ed


def parse_volume_arg(arg: str) -> tuple[str, str, str]:
    """解析固定命令的时间参数，返回 (start_date, end_date, label)。"""
    now = datetime.now()
    arg = (arg or "").strip()
    if not arg:
        end = datetime.now().strftime("%Y-%m-%d")
        start = (now - timedelta(days=6)).strftime("%Y-%m-%d")
        return start, end, f"📅 近7天 ({start} ~ {end})"
    if arg.lower() == "all":
        return "", "9999-12-31", "📅 全部记录"
    if re.fullmatch(r"\d{4}", arg):
        return f"{arg}-01-01", f"{arg}-12-31", f"📅 {arg}全年"
    month_match = re.fullmatch(r"(\d{4})[年/\-](\d{1,2})月?", arg)
    if month_match:
        y, m = map(int, month_match.groups())
        last_day = calendar.monthrange(y, m)[1]
        return f"{y:04d}-{m:02d}-01", f"{y:04d}-{m:02d}-{last_day:02d}", f"📅 {y}年{m}月"
    date_match = re.fullmatch(r"(\d{4})[年/-]?(\d{1,2})[月/-]?(\d{1,2})日?", arg)
    if date_match:
        y, m, d = map(int, date_match.groups())
        target = f"{y:04d}-{m:02d}-{d:02d}"
        return target, target, f"📅 {target}"
    if arg.isdigit():
        n = clamp_int(arg, 7, 1, 3660)
        end = datetime.now().strftime("%Y-%m-%d")
        start = (now - timedelta(days=n - 1)).strftime("%Y-%m-%d")
        return start, end, f"📅 近{n}天 ({start} ~ {end})"
    end = datetime.now().strftime("%Y-%m-%d")
    start = (now - timedelta(days=6)).strftime("%Y-%m-%d")
    return start, end, f"📅 近7天 ({start} ~ {end})"
