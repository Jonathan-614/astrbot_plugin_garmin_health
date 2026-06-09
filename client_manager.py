"""
Garmin 客户端管理器
处理 Garmin Connect 登录、Session 持久化、客户端复用
"""

import os
import asyncio
from datetime import datetime, timedelta
from typing import Optional

from astrbot.api import logger
from garminconnect import Garmin


class GarminClientManager:
    """Garmin 客户端管理器，支持 session 持久化和多工具共享"""

    def __init__(self, config: dict, session_dir: str):
        self.config = config
        self._session_dir = session_dir
        self._client: Optional[Garmin] = None
        self._lock = asyncio.Lock()

    async def get_client(self) -> Garmin:
        """获取或初始化 Garmin 客户端（线程安全 + session 持久化）"""
        async with self._lock:
            # 尝试复用现有客户端
            if self._client is not None:
                try:
                    self._client.get_stats(_today_str())
                    return self._client
                except Exception:
                    logger.info("Garmin session 已过期，尝试重新登录")

            email = self.config.get("garmin_email", "")
            password = self.config.get("garmin_password", "")

            if not email or not password:
                raise ValueError("请先在插件配置中填写 Garmin 账号和密码")

            is_cn = self.config.get("garmin_is_cn", True)
            client = Garmin(email, password, is_cn=is_cn)

            # 尝试从 session 文件加载
            session_file = os.path.join(self._session_dir, "garth_session")
            if os.path.exists(session_file):
                try:
                    client.garth.load(session_file)
                    logger.info("从 session 文件加载登录态成功")
                except Exception as e:
                    logger.warning(f"加载 session 文件失败: {e}，尝试重新登录")
                    client.login()
            else:
                client.login()

            # 保存 session
            os.makedirs(self._session_dir, exist_ok=True)
            try:
                client.garth.dump(session_file)
            except Exception as e:
                logger.warning(f"保存 session 文件失败: {e}")

            self._client = client
            return client

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
