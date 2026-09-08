"""视频号 adapter (probing stage). Interface notes: docs/platforms/weixin_channels.md"""

from __future__ import annotations

from typing import Any

from ..base import Capability, PlatformAdapter, RateLimit


class WeixinChannelsAdapter(PlatformAdapter):
    id = "weixin_channels"
    name = "视频号"
    home_url = "https://channels.weixin.qq.com/"
    login_url = "https://channels.weixin.qq.com/"
    login_hint = "打开 channels.weixin.qq.com（视频号网页版），用微信扫码登录"
    domains = ("channels.weixin.qq.com",)
    risk_level = "high"
    rate_limit = RateLimit(interval_s=5.0, jitter_s=2.0, page_loads=12)
    capabilities = {
        "echo": Capability("echo", "call", "Round-trip through a 视频号 tab", 30000),
        "probe": Capability("probe", "call", "Dev: page globals and visible text", 20000),
    }

    def parse(self, action: str, raw: Any) -> Any:
        return raw
