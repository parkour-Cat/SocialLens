from __future__ import annotations

from .base import PlatformAdapter
from .bilibili import BilibiliAdapter
from .system import SystemAdapter
from .douyin import DouyinAdapter
from .kuaishou import KuaishouAdapter
from .weixin_channels import WeixinChannelsAdapter
from .weixin_mp import WeixinMpAdapter
from .x import XAdapter
from .youtube import YoutubeAdapter
from .xiaohongshu import XiaohongshuAdapter
from .reddit import RedditAdapter
from .zhihu import ZhihuAdapter
from .tiktok import TiktokAdapter
from .instagram import InstagramAdapter
from .linkedin import LinkedinAdapter
from .toutiao import ToutiaoAdapter


class PlatformRegistry:
    def __init__(self, adapters: list[PlatformAdapter]):
        self._by_id = {a.id: a for a in adapters}

    def get(self, platform_id: str) -> PlatformAdapter | None:
        return self._by_id.get(platform_id)

    def ids(self) -> list[str]:
        return [pid for pid in self._by_id if not pid.startswith("_")]

    def all(self) -> list[PlatformAdapter]:
        return [a for pid, a in self._by_id.items() if not pid.startswith("_")]

    def all_including_system(self) -> list[PlatformAdapter]:
        return list(self._by_id.values())


def build_registry() -> PlatformRegistry:
    return PlatformRegistry([SystemAdapter(), BilibiliAdapter(), XiaohongshuAdapter(), DouyinAdapter(), WeixinMpAdapter(), KuaishouAdapter(), WeixinChannelsAdapter(), YoutubeAdapter(), XAdapter(), RedditAdapter(), ZhihuAdapter(), TiktokAdapter(), InstagramAdapter(), LinkedinAdapter(), ToutiaoAdapter()])
