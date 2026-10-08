# -*- coding: utf-8 -*-
"""pytest 公共夹具：把项目根目录加入 sys.path，并提供解析用 HTML 与样例数据。

fixture 中的 HTML 忠实还原豆瓣当前列表页结构（评分容器无 class、评价人数在裸 span、
短评是 p.quote 下的普通 span），同时保留一组旧版结构（div.star / v:votes / span.inq）。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from douban_top250.config import BASE_URL  # noqa: E402
from douban_top250.models import Movie  # noqa: E402

# --------------------------------------------------------------------------- #
# HTML 片段
# --------------------------------------------------------------------------- #
MODERN_ITEM = """
<div class="item">
  <div class="pic">
    <em class="">1</em>
    <a href="https://movie.douban.com/subject/1292052/">
      <img width="100" alt="肖申克的救赎" src="https://img9.doubanio.com/view/photo/s_ratio_poster/public/p480747492.jpg" class="">
    </a>
  </div>
  <div class="info">
    <div class="hd">
      <a href="https://movie.douban.com/subject/1292052/" class="">
        <span class="title">肖申克的救赎</span>
        <span class="title">&nbsp;/&nbsp;The Shawshank Redemption</span>
        <span class="other">&nbsp;/&nbsp;月黑高飞(港)  /  刺激1995(台)</span>
      </a>
    </div>
    <div class="bd">
      <p class="">导演: 弗兰克·德拉邦特 Frank Darabont&nbsp;&nbsp;&nbsp;主演: 蒂姆·罗宾斯 Tim Robbins /...<br>1994&nbsp;/&nbsp;美国&nbsp;/&nbsp;犯罪 剧情</p>
      <div class=""><span class="rating_num" property="v:average">9.7</span><span>3347760人评价</span></div>
      <p class="quote"><span>希望让人自由。</span></p>
    </div>
  </div>
</div>
"""

OLD_ITEM = """
<div class="item">
  <div class="pic">
    <em class="">2</em>
    <a href="/subject/1291546/"><img width="100" alt="霸王别姬" src="https://img9.doubanio.com/view/photo/s_ratio_poster/public/p2561716440.jpg" class=""></a>
  </div>
  <div class="info">
    <div class="hd">
      <a href="/subject/1291546/" class="">
        <span class="title">霸王别姬</span>
        <span class="title">&nbsp;/&nbsp;Farewell My Concubine</span>
        <span class="other">&nbsp;/&nbsp;再见，我的妾</span>
      </a>
    </div>
    <div class="bd">
      <p class="">导演: 陈凯歌 Kaige Chen&nbsp;&nbsp;&nbsp;主演: 张国荣 Leslie Cheung /...<br>1993&nbsp;/&nbsp;中国大陆 中国香港&nbsp;/&nbsp;剧情 爱情 同性</p>
      <div class="star"><span class="rating5-t"></span><span class="rating_num" property="v:average">9.6</span><span property="v:votes">2210000</span></div>
      <p class="quote"><span class="inq">风华绝代。</span></p>
    </div>
  </div>
</div>
"""

SPARSE_ITEM = """
<div class="item">
  <div class="pic">
    <a href="/subject/9999999/"><img width="100" alt="无名之辈" src="https://img9.doubanio.com/view/photo/s_ratio_poster/public/p2539508468.jpg" class=""></a>
  </div>
  <div class="info">
    <div class="hd"><a href="/subject/9999999/"><span class="title">无名之辈</span></a></div>
    <div class="bd">
      <p class="">导演: 饶晓志 Xiaozhi Rao<br>2018&nbsp;/&nbsp;中国大陆&nbsp;/&nbsp;剧情 喜剧</p>
      <div class="star"><span class="rating_num" property="v:average">8.1</span><span>100人评价</span></div>
    </div>
  </div>
</div>
"""


def wrap_items(*items: str) -> str:
    """把 item 片段包进完整页面骨架。"""
    return (
        "<!DOCTYPE html><html><head><title>豆瓣电影 Top 250</title></head><body>"
        '<div id="content"><ol class="grid_view">' + "".join(items) + "</ol></div>"
        "</body></html>"
    )


# --------------------------------------------------------------------------- #
# 夹具
# --------------------------------------------------------------------------- #
@pytest.fixture
def modern_item() -> str:
    return MODERN_ITEM


@pytest.fixture
def old_item() -> str:
    return OLD_ITEM


@pytest.fixture
def sparse_item() -> str:
    return SPARSE_ITEM


@pytest.fixture
def sample_html() -> str:
    return wrap_items(MODERN_ITEM, OLD_ITEM, SPARSE_ITEM)


@pytest.fixture
def sample_movies() -> List[Movie]:
    return [
        Movie(
            rank=1, title="肖申克的救赎", foreign_title="The Shawshank Redemption",
            aliases="月黑高飞(港) / 刺激1995(台)", year="1994", country="美国",
            genres="犯罪 剧情", rating=9.7, votes=3347760, quote="希望让人自由。",
            staff="导演: 弗兰克·德拉邦特 Frank Darabont 主演: 蒂姆·罗宾斯 Tim Robbins /...",
            url="https://movie.douban.com/subject/1292052/",
            cover="https://img9.doubanio.com/view/photo/public/p480747492.jpg",
        ),
        Movie(
            rank=2, title="霸王别姬", foreign_title="Farewell My Concubine",
            aliases="再见，我的妾", year="1993", country="中国大陆 中国香港",
            genres="剧情 爱情 同性", rating=9.6, votes=2210000, quote="风华绝代。",
            staff="导演: 陈凯歌 Kaige Chen 主演: 张国荣 Leslie Cheung /...",
            url="https://movie.douban.com/subject/1291546/",
            cover="https://img9.doubanio.com/view/photo/public/p2561716440.jpg",
        ),
        Movie(
            rank=3, title="无名之辈", year="2018", country="中国大陆", genres="剧情 喜剧",
            rating=8.1, votes=100, quote="",
            staff="导演: 饶晓志 Xiaozhi Rao",
            url="https://movie.douban.com/subject/9999999/",
            cover="https://img9.doubanio.com/view/photo/public/p2539508468.jpg",
        ),
    ]


@pytest.fixture
def sample_payload(sample_movies: List[Movie]) -> Dict[str, object]:
    from douban_top250.storage import build_payload

    return build_payload(sample_movies, source=BASE_URL, crawled_at="2026-01-01 00:00:00")


# --------------------------------------------------------------------------- #
# 网络桩：让抓取逻辑可以在无网络、无 sleep 的情况下被测试
# --------------------------------------------------------------------------- #
class StubResponse:
    """最小可用的 requests.Response 替身。"""

    def __init__(self, status_code: int = 200, text: str = "", url: str = BASE_URL,
                 apparent_encoding: str = "utf-8") -> None:
        self.status_code = status_code
        self.text = text
        self.url = url
        self.encoding = None
        self.apparent_encoding = apparent_encoding
        self.content = text.encode("utf-8")

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return "<StubResponse {}>".format(self.status_code)


class StubSession:
    """按顺序返回预设响应（Exception 实例会被抛出）并记录调用。"""

    def __init__(self, responses, cookies=None) -> None:
        from requests.cookies import RequestsCookieJar

        self.headers: Dict[str, str] = {}
        self.cookies = cookies if cookies is not None else RequestsCookieJar()
        self.responses = list(responses)
        self.calls = []
        self.trust_env = False

    def get(self, url, params=None, timeout=None, **kwargs):
        self.calls.append({
            "url": url,
            "params": params,
            "timeout": timeout,
            "referer": self.headers.get("Referer"),
            "user_agent": self.headers.get("User-Agent"),
        })
        if not self.responses:
            raise AssertionError("StubSession 预设响应已用尽，共调用 {} 次".format(len(self.calls)))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def stub_session_factory():
    def factory(responses, cookies=None):
        return StubSession(responses, cookies=cookies)

    return factory
