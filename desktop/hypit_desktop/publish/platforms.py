from dataclasses import dataclass


@dataclass(frozen=True)
class Platform:
    id: str
    name: str
    region: str  # "domestic" | "overseas"
    upload_url: str = ""  # creator / upload page for manual posting; verify before release


PLATFORMS = [
    Platform("douyin", "抖音", "domestic", "https://creator.douyin.com/"),
    Platform("kuaishou", "快手", "domestic", "https://cp.kuaishou.com/"),
    Platform("channels", "视频号", "domestic", "https://channels.weixin.qq.com/"),
    Platform("xiaohongshu", "小红书", "domestic", "https://creator.xiaohongshu.com/"),
    Platform("pdd", "拼多多", "domestic"),
    Platform("tiktok", "TikTok", "overseas", "https://www.tiktok.com/upload"),
    Platform("youtube", "YouTube", "overseas", "https://studio.youtube.com/"),
    Platform("x", "X", "overseas", "https://x.com/compose/post"),
]

BY_ID = {p.id: p for p in PLATFORMS}
