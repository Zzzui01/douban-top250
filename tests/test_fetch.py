# -*- coding: utf-8 -*-
"""抓取层测试：cookie 持久化、反爬识别、失败分类与 last_error 判断。

全部使用 StubSession，既不联网也不真的 sleep。
"""

from __future__ import annotations

import json
import time

import pytest
import requests

from douban_top250 import fetch as fetch_module
from douban_top250.config import COOKIE_FILE
from douban_top250.exceptions import AntiBotError, FetchError
from douban_top250.fetch import (
    Fetcher,
    apply_cookie_string,
    load_cookies,
    load_proxy_file,
    parse_cookie_string,
    save_cookies,
)


@pytest.fixture(autouse=True)
def no_real_sleep(monkeypatch):
    """拦截真实 sleep，并记录退避时长供断言。"""
    recorded = []

    def fake_sleep(seconds):
        recorded.append(seconds)

    monkeypatch.setattr(fetch_module.time, "sleep", fake_sleep)
    return recorded


def fetch_ok(text="<html><ol class='grid_view'></ol></html>", status=200, url=None):
    """构造一个 StubResponse（复用 conftest 中的替身类）。"""
    from conftest import StubResponse

    return StubResponse(status_code=status, text=text, url=url or "https://movie.douban.com/top250")


def make_fetcher(session, **kwargs):
    kwargs.setdefault("delay", (0, 0))
    kwargs.setdefault("warmup", False)
    kwargs.setdefault("retries", 2)
    return Fetcher(session=session, **kwargs)


# --------------------------------------------------------------------------- #
# cookie 持久化
# --------------------------------------------------------------------------- #
def test_save_and_load_cookies_round_trip(tmp_path):
    path = tmp_path / "cookies.json"
    session = requests.Session()
    session.cookies.set("bid", "abc123", domain=".douban.com", path="/")
    session.cookies.set("ll", "118234", domain=".douban.com", path="/")

    assert save_cookies(session, path) == 2

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["cookies"][0]["name"] == "bid"
    assert "saved_at" in payload

    restored = requests.Session()
    assert load_cookies(restored, path) == 2
    assert restored.cookies.get("bid") == "abc123"


def test_load_cookies_handles_missing_expired_and_broken(tmp_path):
    missing = tmp_path / "missing.json"
    assert load_cookies(requests.Session(), missing) == 0

    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert load_cookies(requests.Session(), broken) == 0

    expired = tmp_path / "expired.json"
    expired.write_text(
        json.dumps({"cookies": [{"name": "bid", "value": "x", "expires": time.time() - 10}]}),
        encoding="utf-8",
    )
    assert load_cookies(requests.Session(), expired) == 0


def test_warm_up_reuses_existing_cookie_file(tmp_path, stub_session_factory):
    cookie_file = tmp_path / "cookies.json"
    cookie_file.write_text(
        json.dumps({"cookies": [{"name": "bid", "value": "abc", "path": "/"}]}), encoding="utf-8"
    )
    session = stub_session_factory([])

    fetcher = Fetcher(session=session, warmup=True, cookie_file=cookie_file, delay=(0, 0))
    fetcher.warm_up()

    assert session.calls == []                       # 有可用 cookie 就不再请求首页
    assert fetcher.session.cookies.get("bid") == "abc"


def test_warm_up_fetches_home_and_persists_cookie(tmp_path, stub_session_factory):
    from douban_top250.config import HOME_URL

    cookie_file = tmp_path / "cookies.json"
    session = stub_session_factory([fetch_ok("<html>home</html>")])

    fetcher = Fetcher(session=session, warmup=True, cookie_file=cookie_file, delay=(0, 0))
    fetcher.warm_up()

    assert len(session.calls) == 1
    assert session.calls[0]["url"] == HOME_URL
    assert cookie_file.is_file()


# --------------------------------------------------------------------------- #
# 请求与失败分类
# --------------------------------------------------------------------------- #
def test_get_returns_html_and_reuses_session(stub_session_factory):
    session = stub_session_factory([fetch_ok("<html>ok 肖申克</html>")])
    fetcher = make_fetcher(session)

    html = fetcher.get("https://movie.douban.com/top250", params={"start": 0})

    assert "肖申克" in html
    assert len(session.calls) == 1
    assert session.calls[0]["params"] == {"start": 0}
    assert fetcher.last_error is None


def test_blocked_response_raises_antibbot_and_stops_early(stub_session_factory):
    session = stub_session_factory([fetch_ok("", status=403), fetch_ok("", status=403),
                                    fetch_ok("", status=403), fetch_ok("", status=403)])
    fetcher = make_fetcher(session, retries=4, max_block_retries=2)

    with pytest.raises(AntiBotError) as excinfo:
        fetcher.get("https://movie.douban.com/top250")

    assert len(session.calls) == 2                     # 达到拦截上限即停止，不再加重封禁
    assert "IP 已被豆瓣限流" in str(excinfo.value)
    assert isinstance(fetcher.last_error, AntiBotError)


def test_captcha_page_is_treated_as_blocked(stub_session_factory):
    session = stub_session_factory([fetch_ok("<html><title>检测到有异常请求</title></html>")] * 3)
    fetcher = make_fetcher(session, retries=3, max_block_retries=3)

    with pytest.raises(AntiBotError):
        fetcher.get("https://movie.douban.com/top250")


def test_antibbot_dominates_later_network_error(stub_session_factory):
    """回归测试：先被风控、后遇网络错误时，必须仍然抛 AntiBotError。

    旧实现用 `"反爬" in str(last_error)` 判断，最后一条错误会覆盖主导原因，
    导致退出时只看到 "ConnectionError"，用户无从判断是被限流了。
    """
    session = stub_session_factory([fetch_ok("", status=403),
                                    requests.ConnectionError("connection reset")])
    fetcher = make_fetcher(session, retries=2, max_block_retries=5)

    with pytest.raises(AntiBotError) as excinfo:
        fetcher.get("https://movie.douban.com/top250")

    assert "被反爬拦截" in str(excinfo.value)
    assert "IP 已被豆瓣限流" in str(excinfo.value)


def test_network_errors_raise_fetcherror_with_reason(stub_session_factory):
    session = stub_session_factory([requests.ConnectionError("boom"),
                                    requests.ConnectionError("boom")])
    fetcher = make_fetcher(session, retries=2)

    with pytest.raises(FetchError) as excinfo:
        fetcher.get("https://movie.douban.com/top250")

    message = str(excinfo.value)
    assert "ConnectionError" in message
    assert "boom" in message
    assert not isinstance(excinfo.value, AntiBotError)


def test_http_error_is_retried_then_raised(stub_session_factory):
    session = stub_session_factory([fetch_ok("", status=500, url="https://movie.douban.com/top250")] * 2)
    fetcher = make_fetcher(session, retries=2)

    with pytest.raises(FetchError) as excinfo:
        fetcher.get("https://movie.douban.com/top250")

    assert "HTTP 500" in str(excinfo.value)
    assert len(session.calls) == 2


def test_blocked_then_success_is_retried(stub_session_factory, no_real_sleep):
    session = stub_session_factory([fetch_ok("", status=403), fetch_ok("<html>ok</html>")])
    fetcher = make_fetcher(session, retries=3, max_block_retries=5)

    html = fetcher.get("https://movie.douban.com/top250")

    assert html == "<html>ok</html>"
    assert len(session.calls) == 2
    assert no_real_sleep and no_real_sleep[0] >= 10    # 被限流时退避更长（>=10s）


# --------------------------------------------------------------------------- #
# 会话与代理
# --------------------------------------------------------------------------- #
def test_default_fetcher_builds_direct_fallback_session():
    fetcher = Fetcher(delay=(0, 0), warmup=False, use_cookies=False)

    assert len(fetcher.sessions) == 2
    assert fetcher.sessions[0].trust_env is True       # 优先尊重系统代理
    assert fetcher.sessions[1].trust_env is False      # 代理不可用时自动回退直连


def test_direct_mode_skips_system_proxy():
    fetcher = Fetcher(direct=True, delay=(0, 0), warmup=False, use_cookies=False)

    assert len(fetcher.sessions) == 1
    assert fetcher.sessions[0].trust_env is False


def test_proxy_mode_uses_given_proxy():
    fetcher = Fetcher(proxy="http://127.0.0.1:7890", delay=(0, 0), warmup=False, use_cookies=False)

    assert fetcher.sessions[0].proxies["https"] == "http://127.0.0.1:7890"


def test_default_cookie_file_constant_points_into_cache_dir():
    assert COOKIE_FILE.name == "douban_cookies.json"


# --------------------------------------------------------------------------- #
# 手工 cookie（把浏览器登录态塞进来）
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "raw, expected",
    [
        ("bid=abc123; ll=118234", {"bid": "abc123", "ll": "118234"}),
        ("bid=abc123\nll=118234", {"bid": "abc123", "ll": "118234"}),
        ("Cookie: bid=abc123; dbcl2=12345:abcdef", {"bid": "abc123", "dbcl2": "12345:abcdef"}),
        ("ck=abc=def", {"ck": "abc=def"}),                     # 值里含 = 也要完整保留
        ("bid = abc123 ; ", {"bid": "abc123"}),
        ("", {}),
        ("没有等号的垃圾", {}),
    ],
)
def test_parse_cookie_string(raw, expected):
    assert parse_cookie_string(raw) == expected


def test_cookie_string_is_injected_into_every_session(tmp_path):
    from conftest import StubSession

    session = StubSession([fetch_ok()])
    fetcher = Fetcher(session=session, delay=(0, 0), warmup=False,
                      cookie_string="bid=abc123; dbcl2=12345:xyz")

    assert session.cookies.get("bid") == "abc123"
    assert session.cookies.get("dbcl2") == "12345:xyz"


def test_apply_cookie_string_returns_count():
    session = requests.Session()

    assert apply_cookie_string(session, "a=1; b=2") == 2
    assert apply_cookie_string(session, "") == 0


# --------------------------------------------------------------------------- #
# 代理池与出口轮换
# --------------------------------------------------------------------------- #
def test_load_proxy_file_ignores_comments_and_blanks(tmp_path):
    path = tmp_path / "proxies.txt"
    path.write_text("# 注释\nhttp://127.0.0.1:7890\n\n  socks5://127.0.0.1:1080  \n",
                    encoding="utf-8")

    assert load_proxy_file(path) == ["http://127.0.0.1:7890", "socks5://127.0.0.1:1080"]


def test_load_proxy_file_rejects_missing_or_empty(tmp_path):
    with pytest.raises(FetchError):
        load_proxy_file(tmp_path / "没有这个文件.txt")

    empty = tmp_path / "empty.txt"
    empty.write_text("# 只有注释\n", encoding="utf-8")
    with pytest.raises(FetchError):
        load_proxy_file(empty)


def test_proxy_pool_builds_one_session_per_proxy():
    fetcher = Fetcher(proxy_pool=["http://a:1", "http://b:2"], delay=(0, 0),
                      warmup=False, use_cookies=False)

    assert len(fetcher.sessions) == 2
    assert fetcher.sessions[0].proxies["https"] == "http://a:1"
    assert fetcher.sessions[1].proxies["https"] == "http://b:2"
    assert all(session.trust_env is False for session in fetcher.sessions)


def test_block_rotates_to_next_proxy_and_succeeds():
    from conftest import StubResponse, StubSession

    blocked = "<html><body>检测到有异常请求</body></html>"
    first = StubSession([StubResponse(status_code=403, text=blocked)])
    second = StubSession([fetch_ok("<html>ok</html>")])
    fetcher = Fetcher(session=first, delay=(0, 0), warmup=False, use_cookies=False,
                      retries=4, max_block_retries=1)
    fetcher.sessions.append(second)

    assert fetcher.get("https://movie.douban.com/top250") == "<html>ok</html>"
    assert len(first.calls) == 1
    assert len(second.calls) == 1
    assert fetcher._index == 1


def test_block_stops_when_no_more_exit_available():
    from conftest import StubResponse, StubSession

    session = StubSession([
        StubResponse(status_code=403, text="检测到有异常请求"),
        StubResponse(status_code=403, text="检测到有异常请求"),
    ])
    fetcher = make_fetcher(session, max_block_retries=2)

    with pytest.raises(AntiBotError):
        fetcher.get("https://movie.douban.com/top250")

    assert len(session.calls) == 2          # 同一出口只给 max_block_retries 次机会


def test_referer_chain_follows_previous_page():
    from conftest import StubSession

    first_url = "https://movie.douban.com/top250?start=0&filter="
    second_url = "https://movie.douban.com/top250?start=25&filter="
    session = StubSession([fetch_ok("<html>1</html>", url=first_url),
                           fetch_ok("<html>2</html>", url=second_url)])
    fetcher = make_fetcher(session, retries=1)

    fetcher.get("https://movie.douban.com/top250", params={"start": 0, "filter": ""})
    fetcher.get("https://movie.douban.com/top250", params={"start": 25, "filter": ""})

    assert session.calls[0]["referer"] == "https://movie.douban.com/"
    assert session.calls[1]["referer"] == first_url      # 第二次带着上一页的 URL


def test_referer_chain_can_be_disabled():
    from conftest import StubSession

    session = StubSession([fetch_ok("<html>1</html>", url="https://movie.douban.com/top250?start=0"),
                           fetch_ok("<html>2</html>")])
    fetcher = make_fetcher(session, retries=1, referer_chain=False)

    fetcher.get("https://movie.douban.com/top250", params={"start": 0, "filter": ""})
    fetcher.get("https://movie.douban.com/top250", params={"start": 25, "filter": ""})

    assert session.calls[1]["referer"] == "https://movie.douban.com/"


def test_user_agent_is_randomized_per_request():
    from conftest import StubSession

    session = StubSession([fetch_ok(), fetch_ok()])
    fetcher = make_fetcher(session, retries=1)

    fetcher.get("https://movie.douban.com/top250", params={"start": 0, "filter": ""})
    fetcher.get("https://movie.douban.com/top250", params={"start": 25, "filter": ""})

    assert all(call["user_agent"] for call in session.calls)
