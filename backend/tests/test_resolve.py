from sociallens.api.resolve import resolve


def r(text: str):
    d = resolve(text)
    return d["platform"], d["kind"], d["id"]


def test_bilibili():
    assert r("https://www.bilibili.com/video/BV1cXNW6XEeC/?spm_id_from=333.1007") == ("bilibili", "post", "BV1cXNW6XEeC")
    assert r("BV1cXNW6XEeC") == ("bilibili", "post", "BV1cXNW6XEeC")
    assert r("https://www.bilibili.com/video/av170001") == ("bilibili", "post", "170001")
    assert r("https://space.bilibili.com/1864674231/video") == ("bilibili", "user", "1864674231")
    assert r("https://b23.tv/abc123") == ("bilibili", "short_link", None)


def test_xiaohongshu_keeps_token():
    d = resolve("https://www.xiaohongshu.com/explore/6a789b0e000000002701c9f7?xsec_token=ABtHm=&xsec_source=pc_search")
    assert (d["platform"], d["kind"], d["id"], d["xsec_token"]) == ("xiaohongshu", "post", "6a789b0e000000002701c9f7", "ABtHm=")
    assert r("https://www.xiaohongshu.com/user/profile/62faf470000000000f005ed4") == ("xiaohongshu", "user", "62faf470000000000f005ed4")


def test_douyin_kuaishou_weixin():
    assert r("https://www.douyin.com/video/7663480658576264457") == ("douyin", "post", "7663480658576264457")
    assert r("https://www.douyin.com/user/MS4wLjABAAAAPj4K0HRsDV5w0VVjsnGqaXR47NyP-ZzzvJQaZea1yI8") == ("douyin", "user", "MS4wLjABAAAAPj4K0HRsDV5w0VVjsnGqaXR47NyP-ZzzvJQaZea1yI8")
    assert r("https://v.douyin.com/iAbCdEf/") == ("douyin", "short_link", None)
    assert r("https://www.kuaishou.com/short-video/3xmwbc2xn8j8rxa?authorId=3xejqygemg9uwi2") == ("kuaishou", "post", "3xmwbc2xn8j8rxa")
    assert r("https://www.kuaishou.com/profile/3xejqygemg9uwi2") == ("kuaishou", "user", "3xejqygemg9uwi2")
    assert r("https://mp.weixin.qq.com/s/tshKjQrbxo1WtjBSTeagDA") == ("weixin_mp", "post", "tshKjQrbxo1WtjBSTeagDA")


def test_youtube_x():
    assert r("https://www.youtube.com/watch?v=gFvK4D1xIw8&t=12s") == ("youtube", "post", "gFvK4D1xIw8")
    assert r("https://youtu.be/gFvK4D1xIw8") == ("youtube", "post", "gFvK4D1xIw8")
    assert r("https://www.youtube.com/shorts/abcdefghijk") == ("youtube", "post", "abcdefghijk")
    assert r("https://www.youtube.com/@OutdoorBoys/videos") == ("youtube", "user", "@OutdoorBoys")
    assert r("https://www.youtube.com/channel/UC4QobU6STFB0P71PMvOGN5A") == ("youtube", "user", "UC4QobU6STFB0P71PMvOGN5A")
    assert r("https://x.com/NASA/status/2095890073031966734") == ("x", "post", "2095890073031966734")
    assert r("https://twitter.com/i/web/status/2095890073031966734") == ("x", "post", "2095890073031966734")
    assert r("x.com/NASA") == ("x", "user", "NASA")
    assert r("https://x.com/home") == ("x", None, None)


def test_plain_words_are_keywords():
    assert r("露营 装备") == (None, "keyword", None)
    assert r("") == (None, "keyword", None)
