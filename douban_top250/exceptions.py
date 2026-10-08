# -*- coding: utf-8 -*-
"""异常层级。

分层的原因：调用方需要**结构化**地区分失败原因，而不是对错误文本做字符串匹配。
被限流（AntiBotError）与普通网络失败（FetchError）的处置方式完全不同：
前者应立即停止并更换出口 IP，后者可以重试。
"""

from __future__ import annotations


class CrawlError(RuntimeError):
    """爬虫相关错误基类。"""


class FetchError(CrawlError):
    """网络层失败：连接错误、超时、非预期 HTTP 状态码等。"""


class AntiBotError(FetchError):
    """被豆瓣风控拦截（HTTP 403/418/429 或命中反爬页面特征）。

    被限流属于 IP 级封禁，继续重试只会延长封禁时间，应立即止损。
    """


class CleanError(CrawlError):
    """数据清洗阶段失败。"""
