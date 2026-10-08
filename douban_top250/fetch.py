# -*- coding: utf-8 -*-
"""网络抓取层。

职责
----
1. 会话管理：预热带 cookie（bid/ll）、cookie 持久化到本地文件、代理池轮换、代理/直连自动回退；
2. 反爬对抗：随机 UA、Referer 链式伪装、每次请求前随机延时、失败指数退避；
3. 失败分类：结构化抛出 AntiBotError / FetchError，调用方无需对错误文本做字符串匹配；
4. 限流止损：同一出口 IP 被风控拦截最多重试 max_block_retries 次；若还有别的出口会话
   （代理池/直连备用）就换 IP 重试，否则立即放弃，避免延长 IP 封禁。
"""

from __future__ import annotations

import json
import random
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import requests

from .config import (
    ANTI_BOT_MARKS,
    BLOCK_STATUS_CODES,
    COOKIE_FILE,
    DEFAULT_DELAY,
    DEFAULT_MAX_BLOCK_RETRIES,
    DEFAULT_RETRIES,
    DEFAULT_TIMEOUT,
    HOME_URL,
    USER_AGENTS,
)
from .exceptions import AntiBotError, CrawlError, FetchError
from .logging_setup import get_logger

logger = get_logger(__name__)

COOKIE_DOMAIN = ".douban.com"          # 登录 cookie（dbcl2/ck）都是这个域

BLOCK_HINT = (
    "IP 已被豆瓣限流。已自动停止重试以避免加重封禁。建议按顺序尝试：\n"
    "      1) 立刻停手，等 30 分钟以上再跑（IP 级限流通常几十分钟到数小时自动解除）；\n"
    "      2) 换出口 IP：把可用代理写进文件后 --proxy-file proxies.txt（被拦自动轮换），\n"
    "         或者直接用手机热点/路由器重播号换个公网 IP；\n"
    "      3) 带上浏览器里的登录 Cookie：--cookie-string \"bid=...; dbcl2=...; ck=...\"，\n"
    "         登录态的请求权重远高于匿名请求；\n"
    "      4) 分批慢抓 + 断点续传：--resume --pages 3 --delay 5 10 --cooldown-every 2 --cooldown 60 120；\n"
    "      5) 榜单变化很慢，建议每天只刷前 2-3 页，用 --resume 累积补齐其余页。"
)


# --------------------------------------------------------------------------- #
# cookie 持久化
# --------------------------------------------------------------------------- #
def save_cookies(session: requests.Session, path=COOKIE_FILE) -> int:
    """把会话 cookie 写入 JSON 文件，返回写入条数（失败只告警，不影响抓取）。"""
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        cookies = [
            {
                "name": cookie.name,
                "value": cookie.value,
                "domain": cookie.domain,
                "path": cookie.path,
                "expires": cookie.expires,
                "secure": bool(cookie.secure),
            }
            for cookie in session.cookies
        ]
        payload = {"saved_at": time.strftime("%Y-%m-%d %H:%M:%S"), "cookies": cookies}
        with open(str(path), "w", encoding="utf-8") as fp:
            json.dump(payload, fp, ensure_ascii=False, indent=2)
        logger.debug("已持久化 %d 个 cookie -> %s", len(cookies), path)
        return len(cookies)
    except OSError as exc:
        logger.warning("cookie 持久化失败（忽略）：%s", exc)
        return 0


def load_cookies(session: requests.Session, path=COOKIE_FILE) -> int:
    """从 JSON 文件恢复 cookie，返回恢复条数（已过期的自动跳过）。"""
    path = Path(path)
    if not path.is_file():
        logger.debug("cookie 文件不存在，跳过恢复：%s", path)
        return 0
    try:
        with open(str(path), encoding="utf-8") as fp:
            payload = json.load(fp)
    except (OSError, ValueError) as exc:
        logger.warning("cookie 文件不可读（忽略）：%s", exc)
        return 0

    restored = 0
    now = time.time()
    for item in payload.get("cookies") or []:
        name = item.get("name")
        if not name:
            continue
        expires = item.get("expires")
        if expires is not None and expires < now:
            continue
        try:
            session.cookies.set(
                name,
                item.get("value") or "",
                # 注意：requests 的 create_cookie 会对 domain 调 .startswith，
                # 传 None 会抛 AttributeError，所以没有 domain 时必须给空字符串。
                domain=item.get("domain") or "",
                path=item.get("path") or "/",
                expires=expires,
                secure=bool(item.get("secure")),
            )
            restored += 1
        except Exception as exc:  # cookie 字段异常不应中断启动
            logger.debug("跳过无效 cookie %s：%s", name, exc)
    logger.debug("从 %s 恢复 %d 个 cookie", path, restored)
    return restored


def parse_cookie_string(text: str) -> Dict[str, str]:
    """把浏览器复制出来的 Cookie 串（``a=1; b=2``）解析成字典。

    支持 ``;`` / 换行 / 制表符分隔，忽略 ``Cookie:`` 前缀与多余空白；
    值里含有 ``=`` 也能正确保留（只按第一个 ``=`` 切分）。
    """
    cookies: Dict[str, str] = {}
    if not text:
        return cookies
    text = text.strip()
    if text.lower().startswith("cookie:"):      # 允许直接粘贴 "Cookie: a=1; b=2"
        text = text.split(":", 1)[1]
    normalized = text.replace("\r", "\n").replace("\n", ";").replace("\t", ";")
    for chunk in normalized.split(";"):
        chunk = chunk.strip()
        if not chunk or "=" not in chunk:
            continue
        name, _, value = chunk.partition("=")
        name = name.strip()
        if name.lower() == "cookie":            # 兼容 "a=1; Cookie=..." 这类误粘贴
            continue
        if name:
            cookies[name] = value.strip()
    return cookies


def apply_cookie_string(session: requests.Session, text: str) -> int:
    """把 Cookie 串写进会话，返回写入条数。"""
    cookies = parse_cookie_string(text)
    for name, value in cookies.items():
        session.cookies.set(name, value, domain=COOKIE_DOMAIN, path="/")
    if cookies:
        logger.info("已注入 %d 个手工 cookie（%s）", len(cookies), ", ".join(sorted(cookies)))
    return len(cookies)


def load_proxy_file(path) -> List[str]:
    """读取代理列表文件：每行一个代理，``#`` 开头为注释。"""
    path = Path(path)
    if not path.is_file():
        raise FetchError("代理文件不存在：{}".format(path))
    proxies: List[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        item = line.strip()
        if item and not item.startswith("#"):
            proxies.append(item)
    if not proxies:
        raise FetchError("代理文件里没有任何可用代理：{}".format(path))
    logger.info("从 %s 读取 %d 个代理", path, len(proxies))
    return proxies


# --------------------------------------------------------------------------- #
# 抓取器
# --------------------------------------------------------------------------- #
class Fetcher:
    """带预热、cookie 持久化、随机延时与失败分类的抓取器。

    :param proxy: 指定代理，如 http://127.0.0.1:7890
    :param proxy_pool: 代理池；被风控拦截时自动轮换到下一个出口 IP
    :param direct: 忽略系统代理强制直连
    :param session: 注入自定义会话（测试或复用外部会话时使用）
    :param cookie_file: cookie 持久化路径
    :param use_cookies: 是否启用 cookie 读写
    :param cookie_string: 浏览器复制的 Cookie 串，优先级高于 cookie 文件
    :param referer_chain: 是否让 Referer 指向上一次访问的页面（更像人工翻页）
    """

    def __init__(
        self,
        proxy: Optional[str] = None,
        direct: bool = False,
        timeout: int = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
        max_block_retries: int = DEFAULT_MAX_BLOCK_RETRIES,
        delay: tuple = DEFAULT_DELAY,
        warmup: bool = True,
        use_cookies: bool = True,
        cookie_file=COOKIE_FILE,
        cookie_string: Optional[str] = None,
        proxy_pool: Optional[Sequence[str]] = None,
        referer_chain: bool = True,
        session: Optional[requests.Session] = None,
        quiet: bool = False,
    ) -> None:
        self.timeout = timeout
        self.retries = max(1, int(retries))
        self.max_block_retries = max(1, int(max_block_retries))
        self.delay = delay
        self.warmup = warmup
        self.use_cookies = use_cookies
        self.cookie_file = Path(cookie_file) if cookie_file else None
        self.cookie_string = cookie_string or ""
        self.referer_chain = referer_chain
        self.quiet = quiet
        self.last_error: Optional[BaseException] = None   # 最近一次失败原因（供调用方诊断）
        self._index = 0
        self._last_url: Optional[str] = HOME_URL          # 下一个请求的 Referer
        self.sessions: List[requests.Session] = []

        pool = [item for item in (proxy_pool or []) if item]
        if session is not None:
            self.sessions.append(session)
        elif pool:
            for item in pool:
                self._append_proxy_session(item)
            logger.info("启用代理池：%d 个出口，被拦截时自动轮换", len(pool))
        elif proxy:
            self._append_proxy_session(proxy)
        else:
            plain = requests.Session()
            plain.trust_env = not direct
            self.sessions.append(plain)
            if not direct:
                # 系统代理不可用时（例如代理 TLS 报错）自动回退直连
                fallback = requests.Session()
                fallback.trust_env = False
                self.sessions.append(fallback)

        for sess in self.sessions:
            sess.headers.update(
                {
                    "User-Agent": random.choice(USER_AGENTS),
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                    "Connection": "keep-alive",
                    "Referer": HOME_URL,
                }
            )
            if self.cookie_string:
                apply_cookie_string(sess, self.cookie_string)

    def _append_proxy_session(self, proxy: str) -> None:
        session = requests.Session()
        session.trust_env = False
        session.proxies = {"http": proxy, "https": proxy}
        self.sessions.append(session)

    # -- 内部工具 ---------------------------------------------------------- #
    @property
    def session(self) -> requests.Session:
        return self.sessions[self._index]

    def _switch_session(self, reason: str) -> bool:
        """切换到下一个出口会话，返回是否切换成功。"""
        if self._index + 1 >= len(self.sessions):
            return False
        self._index += 1
        self._last_url = HOME_URL          # 换出口后 Referer 重新从首页起算
        logger.info("切换出口会话（第 %d/%d 个）：%s", self._index + 1, len(self.sessions), reason)
        return True

    def _sleep_before_request(self) -> None:
        if self.delay and self.delay[1] > 0:
            time.sleep(random.uniform(self.delay[0], self.delay[1]))

    @staticmethod
    def _is_blocked(response: requests.Response, text: str) -> bool:
        if response.status_code in BLOCK_STATUS_CODES:
            return True
        if any(mark in text for mark in ANTI_BOT_MARKS):
            return True
        return any(mark in str(response.url) for mark in ANTI_BOT_MARKS)

    def _build_error(self, last_error: Optional[BaseException], blocked_error: Optional[AntiBotError],
                     url: str, params: Optional[dict]) -> CrawlError:
        """把循环中记录的错误翻译成对外异常。

        被限流是主导原因，只要本次请求过程中出现过风控拦截，就抛 AntiBotError，
        即使后续重试报的是网络错误——避免调用方被最后一个错误误导。
        """
        if blocked_error is not None:
            return AntiBotError("{}\n    {}".format(blocked_error, BLOCK_HINT))
        if last_error is None:
            return FetchError("抓取失败 {} params={}：未知原因（未记录到错误）".format(url, params))
        return FetchError("抓取失败 {} params={}：{}".format(url, params, last_error))

    # -- 对外接口 ---------------------------------------------------------- #
    def warm_up(self, url: str = HOME_URL) -> None:
        """加载本地 cookie；若没有可用 cookie，则先访问站点首页拿 bid/ll。

        预热失败不影响后续抓取（只是少了一层伪装），因此只记录日志。
        """
        if not self.warmup:
            return
        restored = self.restore_cookies()
        if restored:
            logger.info("复用本地 cookie %d 个（%s）", restored, self.cookie_file)
            return
        try:
            self._sleep_before_request()
            response = self.session.get(url, timeout=self.timeout)
            self._last_url = str(response.url)
            names = ", ".join(self.session.cookies.keys()) or "无"
            logger.info("预热会话: GET %s -> HTTP %s（cookie: %s）", url, response.status_code, names)
            self.persist_cookies()
        except Exception as exc:
            logger.warning("预热会话失败（忽略）: %s: %s", type(exc).__name__, exc)

    def persist_cookies(self) -> int:
        """把当前会话 cookie 落盘。"""
        if not self.use_cookies or not self.cookie_file:
            return 0
        return save_cookies(self.session, self.cookie_file)

    def restore_cookies(self) -> int:
        """从磁盘恢复 cookie。"""
        if not self.use_cookies or not self.cookie_file:
            return 0
        return load_cookies(self.session, self.cookie_file)

    def get(self, url: str, params: Optional[dict] = None) -> str:
        """抓取页面文本。

        :raises AntiBotError: 被风控拦截（IP 级限流）
        :raises FetchError: 其他网络或 HTTP 失败
        """
        last_error: Optional[BaseException] = None
        blocked_error: Optional[AntiBotError] = None
        blocked_rounds = 0
        self.last_error = None

        for attempt in range(self.retries):
            self._sleep_before_request()
            self.session.headers["User-Agent"] = random.choice(USER_AGENTS)
            # Referer 指向上一次访问的页面：真实用户翻页就是这么带的
            if self.referer_chain and self._last_url:
                self.session.headers["Referer"] = self._last_url
            blocked_this_round = False

            try:
                started = time.time()
                response = self.session.get(url, params=params, timeout=self.timeout)
                text = response.text or ""
                elapsed = time.time() - started
                self._last_url = str(response.url)

                if self._is_blocked(response, text):
                    blocked_this_round = True
                    blocked_rounds += 1
                    blocked_error = AntiBotError(
                        "被反爬拦截 HTTP {}（{}）".format(response.status_code, url)
                    )
                    logger.warning(
                        "第 %d/%d 次请求被风控拦截：HTTP %s，当前出口已拦截 %d 次",
                        attempt + 1, self.retries, response.status_code, blocked_rounds,
                    )
                    if blocked_rounds >= self.max_block_retries:
                        # 还有别的出口 IP（代理池/直连备用）就先换 IP，再给这个新出口一次机会
                        if self._switch_session("被风控拦截，换出口 IP 重试"):
                            blocked_rounds = 0
                        else:
                            logger.error("达到拦截重试上限（%d 次）且无可用出口，停止请求", self.max_block_retries)
                            break
                elif response.status_code >= 400:
                    last_error = FetchError("HTTP {}（{}）".format(response.status_code, url))
                    logger.warning("HTTP %s：%s", response.status_code, url)
                else:
                    response.encoding = response.apparent_encoding or "utf-8"
                    logger.debug(
                        "GET %s params=%s -> %s（%.2fs, %d 字节）",
                        url, params, response.status_code, elapsed, len(response.content),
                    )
                    self.persist_cookies()
                    return response.text
            except Exception as exc:  # requests 异常 + 代理 TLS 异常
                last_error = FetchError("{}: {}".format(type(exc).__name__, exc))
                logger.warning("请求异常：%s: %s", type(exc).__name__, exc)
                if self._switch_session("{}: {}".format(type(exc).__name__, exc)):
                    continue

            # 被限流时退避更久（风控通常需要几十秒），普通错误按指数退避
            if blocked_this_round:
                wait = min(10 * (2 ** attempt) + random.random() * 3, 60)
            else:
                wait = min(2 ** attempt + random.random(), 15)
            logger.info("第 %d/%d 次失败，%.1fs 后重试", attempt + 1, self.retries, wait)
            time.sleep(wait)

            if not blocked_this_round and attempt >= 1 and self._switch_session("连续失败"):
                continue

        error = self._build_error(last_error, blocked_error, url, params)
        self.last_error = error
        raise error


__all__ = ["Fetcher", "save_cookies", "load_cookies", "BLOCK_HINT"]
