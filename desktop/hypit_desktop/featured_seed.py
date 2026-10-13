"""Sample entries for the internal featured library; real ones are added in the app."""

FEATURED_PLATFORMS = [
    ("douyin", "抖音"), ("kuaishou", "快手"), ("channels", "视频号"), ("xiaohongshu", "小红书"),
    ("pdd", "拼多多"), ("x", "推特 / X"), ("youtube", "YouTube"),
]
PLATFORM_NAMES = dict(FEATURED_PLATFORMS)

SEED = [
    ("douyin", "示例:口播排行榜", "20 秒口播加排行榜板,节奏快,多次反转",
     "https://www.douyin.com/video/7684610633048342905",
     {"scene": "口播排行榜", "duration": "20 秒", "aspect": "9:16", "language": "中文", "market": "中国大陆"}),
    ("kuaishou", "示例:剧情反转短剧", "30 秒短剧,结尾反转", "https://example.com/hot/kuaishou",
     {"scene": "家庭剧情", "duration": "30 秒", "aspect": "9:16", "language": "中文", "market": "中国大陆"}),
    ("channels", "示例:知识讲解", "把一个知识点讲清楚,配字幕和图示", "https://example.com/hot/channels",
     {"scene": "知识讲解", "duration": "60 秒", "aspect": "16:9", "language": "中文", "market": "中国大陆"}),
    ("xiaohongshu", "示例:产品种草", "生活场景里自然带出产品", "https://example.com/hot/xhs",
     {"scene": "居家好物", "duration": "15 秒", "aspect": "9:16", "language": "中文", "market": "中国大陆"}),
    ("pdd", "示例:商品卖点展示", "15 秒突出价格与卖点", "https://example.com/hot/pdd",
     {"scene": "商品展示", "duration": "15 秒", "aspect": "9:16", "language": "中文", "market": "中国大陆"}),
    ("x", "示例:Meme 短视频", "短平快的梗视频", "https://example.com/hot/x",
     {"scene": "meme", "duration": "15 秒", "aspect": "16:9", "language": "English", "market": "美国"}),
    ("youtube", "示例:Shorts 解说", "30 秒竖屏解说", "https://example.com/hot/youtube",
     {"scene": "解说", "duration": "30 秒", "aspect": "9:16", "language": "English", "market": "美国"}),
]


def seed_featured(store, settings) -> None:
    if settings.get("featured_seeded"):
        return
    for platform, title, desc, url, params in SEED:
        store.add_featured(platform, title, desc, url, "", params)
    settings.set("featured_seeded", True)
