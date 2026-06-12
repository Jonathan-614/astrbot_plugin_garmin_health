"""
Garmin 客户端管理器
处理 Garmin Connect 登录、Session 持久化、客户端复用
"""

import os
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Callable, TypeVar

from .utils import clamp_int

from astrbot.api import logger
from garminconnect import Garmin


T = TypeVar("T")


class GarminClientManager:
    """Garmin 客户端管理器，支持 session 持久化和多工具共享"""

    def __init__(self, config: dict, session_dir: str):
        self.config = config
        self._session_dir = session_dir
        self._client: Optional[Garmin] = None
        self._lock = asyncio.Lock()
        self._request_lock = asyncio.Lock()

    async def call(self, func: Callable[..., T], *args, **kwargs) -> T:
        """在线程池中串行执行 GarminConnect 的同步阻塞请求。

        garminconnect/garth 是同步库，直接在 async handler 中调用会阻塞
        AstrBot 事件循环；同时复用同一个 client 时也避免并发请求互相踩 session。
        """
        async with self._request_lock:
            return await asyncio.to_thread(func, *args, **kwargs)

    async def get_client(self) -> Garmin:
        """获取或初始化 Garmin 客户端（线程安全 + session 持久化）"""
        async with self._lock:
            # 尝试复用现有客户端
            if self._client is not None:
                try:
                    await self.call(self._client.get_stats, _today_str())
                    return self._client
                except Exception:
                    logger.info("Garmin session 已过期，尝试重新登录")
                    self._client = None

            email = self.config.get("garmin_email", "")
            password = self.config.get("garmin_password", "")

            if not email or not password:
                raise ValueError("请先在插件配置中填写 Garmin 账号和密码")

            is_cn = self.config.get("garmin_is_cn", True)
            client = Garmin(email, password, is_cn=is_cn)

            # Garmin.login() 自带 tokenstore 参数，会自动加载/保存 session 文件
            session_file = os.path.join(self._session_dir, "tokenstore.json")
            if os.path.exists(session_file):
                try:
                    await self.call(client.login, tokenstore=session_file)
                    await self.call(client.get_stats, _today_str())
                    logger.info("从 tokenstore 文件加载登录态成功")
                except FileNotFoundError:
                    # tokenstore 文件损坏或格式不对，删除后重新登录
                    logger.warning("tokenstore 文件损坏，重新登录")
                    os.remove(session_file)
                    await self.call(client.login, tokenstore=session_file)
                except Exception as e:
                    logger.warning(f"加载或验证 tokenstore 文件失败: {e}，尝试重新登录")
                    await self.call(client.login, tokenstore=session_file)
            else:
                await self.call(client.login, tokenstore=session_file)

            # 验证登录态
            try:
                await self.call(client.get_stats, _today_str())
            except Exception as e:
                logger.warning(f"验证登录态失败: {e}，重新登录")
                await self.call(client.login, tokenstore=session_file)

            self._client = client
            return client

    async def get_activities(self, max_activities: int = None, page_size: int = 100, activity_type: str = None) -> list:
        """分页获取活动列表，避免只统计最近 200 条导致年度/PB 漏算。

        max_activities 不传时读取配置 garmin_max_activities，默认 600。
        activity_type 指定时传给 Garmin API 服务端过滤（如 running/hiking/walking 等 typeKey）。
        """
        default_max = clamp_int(self.config.get("garmin_max_activities", 600), 600, 1, 10000)
        max_activities = clamp_int(max_activities, default_max, 1, 10000)
        page_size = clamp_int(page_size, 100, 1, 100)
        client = await self.get_client()
        activities = []
        start = 0
        while len(activities) < max_activities:
            limit = min(page_size, max_activities - len(activities))
            batch = await self.call(client.get_activities, start, limit, activity_type)
            if not batch:
                break
            activities.extend(batch)
            if len(batch) < limit:
                break
            start += len(batch)
        return activities

    def invalidate(self):
        """使当前客户端失效（下次 get_client 会重新登录）"""
        self._client = None


def _today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _format_duration(seconds: float) -> str:
    """将秒数格式化为可读时长"""
    if not seconds:
        return "0min"
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    if hours > 0:
        return f"{hours}h{minutes}min"
    return f"{minutes}min"
