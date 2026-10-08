# -*- coding: utf-8 -*-
"""命令行入口：抓取 -> 去重 -> 预览 -> 存 CSV/JSON -> 可选清洗 -> 可选 Excel。

用法示例：
    python bot.py                                  # 抓取全部 10 页，存 output/ 并生成 Excel
    python bot.py --resume                         # 断点续传：只补抓本地缺的页，抓完自动合并
    python bot.py --resume --pages 3 --refresh     # 只重抓前 3 页（刷新榜单头部）再与本地合并
    python bot.py --pages 2 --clean                # 只抓 2 页，并输出 Pandas 清洗结果
    python bot.py --from-json output/douban_top250.json --clean   # 离线重跑清洗与 Excel（不联网）

被限流时的组合拳（详见 README「被限流了怎么办」）：
    python bot.py --resume --proxy-file proxies.txt --cookie-string "bid=...; dbcl2=...; ck=..." \
        --pages 3 --delay 5 10 --cooldown-every 2 --cooldown 60 120 --shuffle-pages
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import List, Optional, Sequence

from .config import (
    CSV_NAME,
    DEFAULT_COOLDOWN,
    DEFAULT_COOLDOWN_EVERY,
    DEFAULT_DELAY,
    DEFAULT_MAX_BLOCK_RETRIES,
    DEFAULT_PREVIEW,
    DEFAULT_RETRIES,
    DEFAULT_TIMEOUT,
    JSON_NAME,
    LOG_DIR,
    MAX_PAGES,
    OUTPUT_DIR,
    SOURCE,
    XLSX_NAME,
)
from .crawler import crawl_top250, dedupe_movies, missing_pages
from .exceptions import CrawlError
from .logging_setup import get_logger, setup_logging
from .models import Movie
from .storage import build_payload, load_json, merge_movies, save_csv, save_json

__version__ = "1.0.0"
logger = get_logger(__name__)


class _HelpFormatter(argparse.ArgumentDefaultsHelpFormatter):
    """布尔开关不显示 "(default: True)" —— 那对 --no-xxx 这类参数是误导。"""

    def _get_help_string(self, action: argparse.Action) -> str:
        if action.nargs == 0:                     # store_true / store_false
            return action.help or ""
        return super()._get_help_string(action)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bot.py",
        description="豆瓣电影 Top250 爬虫（抓取 / 清洗 / Excel 导出）",
        formatter_class=_HelpFormatter,
    )
    parser.add_argument("--version", action="version", version="douban-top250 {}".format(__version__))

    crawl_group = parser.add_argument_group("抓取")
    crawl_group.add_argument("--pages", type=int, default=MAX_PAGES,
                             help="抓取页数，1-{}".format(MAX_PAGES))
    crawl_group.add_argument("--from-json", dest="from_json", default=None,
                             help="不从网络抓取，改为读取本地 JSON 结果")
    crawl_group.add_argument("--preview", type=int, default=DEFAULT_PREVIEW,
                             help="控制台预览条数，0 表示不打印")
    crawl_group.add_argument("--outdir", default=str(OUTPUT_DIR), help="输出目录")
    crawl_group.add_argument("--resume", action="store_true",
                             help="断点续传：读取输出目录里已有的 JSON，只补抓缺失的页并合并")
    crawl_group.add_argument("--refresh", action="store_true",
                             help="配合 --resume：即使本地已有也重抓所选页（刷新榜单头部）")
    crawl_group.add_argument("--only-pages", dest="only_pages", default=None,
                             help="只抓指定页，如 1,3,5-7（被限流时用来小批量补刷）")
    crawl_group.add_argument("--shuffle-pages", dest="shuffle_pages", action="store_true",
                             help="打乱页序，避免 0/25/50… 这种机械翻页特征")
    crawl_group.add_argument("--seed", type=int, default=None,
                             help="打乱页序的随机种子（便于复现同一次抓取顺序）")

    net_group = parser.add_argument_group("网络与反爬")
    net_group.add_argument("--proxy", default=None, help="代理地址，例如 http://127.0.0.1:7890")
    net_group.add_argument("--proxy-file", dest="proxy_file", default=None,
                           help="代理列表文件（每行一个），被风控拦截时自动轮换出口 IP")
    net_group.add_argument("--direct", action="store_true", help="忽略系统代理，强制直连")
    net_group.add_argument("--delay", type=float, nargs=2, metavar=("MIN", "MAX"), default=list(DEFAULT_DELAY),
                           help="每次请求前的随机延时区间（秒）")
    net_group.add_argument("--cooldown-every", dest="cooldown_every", type=int, default=DEFAULT_COOLDOWN_EVERY,
                           help="每抓 N 页长休息一次，0 表示不休息")
    net_group.add_argument("--cooldown", type=float, nargs=2, metavar=("MIN", "MAX"), default=list(DEFAULT_COOLDOWN),
                           help="长休息的随机秒数区间")
    net_group.add_argument("--no-warmup", dest="warmup", action="store_false", default=True,
                           help="跳过访问首页预热会话")
    net_group.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="单次请求超时（秒）")
    net_group.add_argument("--retries", type=int, default=DEFAULT_RETRIES, help="单页最大尝试次数")
    net_group.add_argument("--max-block-retries", dest="max_block_retries", type=int,
                           default=DEFAULT_MAX_BLOCK_RETRIES, help="被风控拦截几次后放弃")

    cookie_group = parser.add_argument_group("Cookie 持久化")
    cookie_group.add_argument("--no-cookies", dest="use_cookies", action="store_false", default=True,
                              help="不读写本地 cookie 文件")
    cookie_group.add_argument("--cookie-file", dest="cookie_file", default=None, help="cookie 文件路径")
    cookie_group.add_argument("--cookie-string", dest="cookie_string", default=None,
                              help='浏览器复制出来的登录 Cookie，例如 "bid=xxx; dbcl2=xxx; ck=xxx"')

    out_group = parser.add_argument_group("输出开关")
    out_group.add_argument("--no-csv", dest="csv", action="store_false", default=True, help="不保存 CSV")
    out_group.add_argument("--no-json", dest="json", action="store_false", default=True, help="不保存 JSON")
    out_group.add_argument("--no-xlsx", dest="xlsx", action="store_false", default=True, help="不生成 Excel")
    out_group.add_argument("--no-clean", dest="clean", action="store_false", default=True,
                           help="跳过 Pandas 清洗（清洗结果写入 clean_*.csv/json）")

    log_group = parser.add_argument_group("日志")
    log_group.add_argument("--log-level", dest="log_level", default="INFO",
                           choices=("DEBUG", "INFO", "WARNING", "ERROR"), help="日志级别")
    log_group.add_argument("--log-dir", dest="log_dir", default=str(LOG_DIR), help="日志目录")
    log_group.add_argument("--no-log-file", dest="log_file", action="store_false", default=True,
                           help="不写日志文件")
    log_group.add_argument("--quiet", action="store_true", help="控制台只输出警告及以上")
    return parser


def _import_pandas_features():
    """延迟导入 pandas 相关模块，未安装时只影响 --clean / Excel 步骤。"""
    from . import clean, excel
    return clean, excel


def _page_text(pages: Sequence[int]) -> str:
    """把页码列表压成 '1-3' 或 '1, 3, 5' 这种可读文本。"""
    items = list(pages)
    if not items:
        return "无"
    if items == list(range(items[0], items[-1] + 1)):
        return str(items[0]) if len(items) == 1 else "{}-{}".format(items[0], items[-1])
    return ", ".join(str(item) for item in items)


def parse_page_list(text: str) -> List[int]:
    """把 '1,3,5-7'（也容忍中文逗号）解析成页码列表：去重、排序、只保留 1-MAX_PAGES。"""
    pages: List[int] = []
    for chunk in str(text).replace("，", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            start_text, _, end_text = chunk.partition("-")
            if not (start_text.strip().isdigit() and end_text.strip().isdigit()):
                continue
            span = range(int(start_text), int(end_text) + 1)
        elif chunk.isdigit():
            span = [int(chunk)]
        else:
            continue
        for page in span:
            if 1 <= page <= MAX_PAGES and page not in pages:
                pages.append(page)
    return sorted(pages)


def write_checkpoint(movies: List[Movie], path: Path) -> Path:
    """把当前进度写进结果 JSON（每抓完一页调用一次）。

    这样即使翻到第 7 页被风控打断，前 6 页也已经落盘，
    下次 `--resume` 只需要补剩下的页，不会白跑。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = build_payload(movies, source=SOURCE)
    with open(str(path), "w", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False, indent=2)
    return path


def run(args: argparse.Namespace) -> int:
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    interrupted = False

    # 1) 取数：网络抓取或读取本地 JSON
    if args.from_json:
        source_path = Path(args.from_json)
        if not source_path.is_file():
            logger.error("JSON 文件不存在：%s", source_path)
            return 1
        payload = load_json(source_path)
        movies = dedupe_movies([Movie.from_row(row) for row in payload.get("movies") or []])
        logger.info("离线模式：从 %s 读取 %d 条记录", source_path, len(movies))
    else:
        from .fetch import Fetcher, load_proxy_file

        proxy_pool = load_proxy_file(args.proxy_file) if args.proxy_file else None
        if proxy_pool and args.proxy:
            logger.warning("同时给了 --proxy 与 --proxy-file，本次以代理池为准")

        # 断点续传：先看看本地已经有什么，避免把 10 页重复翻一遍
        existing: List[Movie] = []
        if args.resume:
            json_path = outdir / JSON_NAME
            if json_path.is_file():
                existing = dedupe_movies(
                    [Movie.from_row(row) for row in load_json(json_path).get("movies") or []]
                )
                logger.info("断点续传：本地已有 %d 条（%s）", len(existing), json_path)
            else:
                logger.info("断点续传：没有找到 %s，本次按全量抓取", json_path)
        else:
            logger.info("提示：加 --resume 可只补抓缺失的页，显著减少请求量")

        order: Optional[List[int]] = None
        if args.only_pages:
            order = parse_page_list(args.only_pages)
            if not order:
                logger.error("--only-pages 没解析出有效页码（允许 1-%d）：%s", MAX_PAGES, args.only_pages)
                return 1
            logger.info("指定页模式：本次只抓第 %s 页", _page_text(order))
            if not args.resume:
                logger.warning("没有加 --resume，结果 JSON 将只包含这几页（建议加上以与本地数据合并）")
        elif args.resume:
            if args.refresh:
                order = list(range(1, max(1, min(args.pages, MAX_PAGES)) + 1))
                logger.info("刷新模式：重抓第 %s 页，抓完与本地数据合并", _page_text(order))
            else:
                order = missing_pages(existing, pages=args.pages)
                logger.info("断点续传：本次要抓的页 = %s（共 %d 页）", _page_text(order), len(order))

        if not order and args.resume and not args.only_pages:
            logger.info("本地数据已覆盖第 1-%d 页，无需联网抓取", args.pages)
            movies = existing
            interrupted = False
        else:
            fetcher = Fetcher(
                proxy=args.proxy,
                proxy_pool=proxy_pool,
                direct=args.direct,
                timeout=args.timeout,
                retries=args.retries,
                max_block_retries=args.max_block_retries,
                delay=tuple(args.delay),
                warmup=args.warmup,
                use_cookies=args.use_cookies,
                cookie_file=args.cookie_file or None,
                cookie_string=args.cookie_string,
                quiet=args.quiet,
            )
            checkpoint_path = outdir / JSON_NAME
            fetched: List[Movie] = []
            interrupted = False

            def checkpoint(page: int, _total: int, page_movies: List[Movie]) -> None:
                """每页抓完立刻落盘：被拦在半路也不会白跑。"""
                fetched.extend(page_movies)
                if not args.json:
                    return
                merged = dedupe_movies(merge_movies(existing, fetched))
                write_checkpoint(merged, checkpoint_path)
                logger.info("检查点已保存：%d 条（第 %d 页抓取完成）", len(merged), page)

            try:
                movies = crawl_top250(
                    fetcher=fetcher,
                    pages=args.pages,
                    on_page=checkpoint if args.json else None,
                    cooldown_every=args.cooldown_every,
                    cooldown=tuple(args.cooldown),
                    order=order,
                    shuffle=args.shuffle_pages,
                    seed=args.seed,
                )
            except CrawlError as exc:
                if not fetched:
                    raise                      # 一条都没抓到，按原样报错退出
                interrupted = True
                logger.error("%s", exc)
                logger.warning(
                    "抓取中断：本次抓到的 %d 条已存入 %s，下次执行 `--resume` 只补缺页即可",
                    len(dedupe_movies(merge_movies(existing, fetched))), checkpoint_path,
                )
                movies = fetched

            if existing:
                fresh_ranks = {movie.rank for movie in movies}
                existing_ranks = {movie.rank for movie in existing}
                logger.info(
                    "已与本地数据合并：本次刷新 %d 条，新增 %d 条，本地共 %d 条",
                    len(fresh_ranks & existing_ranks), len(fresh_ranks - existing_ranks),
                    len(existing_ranks | fresh_ranks),
                )
            movies = dedupe_movies(merge_movies(existing, movies))
        payload = None

    if not movies:
        logger.error("没有获取到任何数据，请检查网络/代理或降低抓取频率后重试")
        return 1

    # 2) 预览
    if args.preview and not args.quiet:
        from .report import print_table

        print_table(movies, limit=args.preview)

    # 3) 原始结果落盘
    crawled_at = payload.get("crawled_at") if payload else None

    if payload is None:
        payload = build_payload(movies, source=SOURCE, crawled_at=crawled_at)

    if args.csv:
        save_csv(movies, outdir / CSV_NAME)
    if args.json:
        save_json(movies, outdir / JSON_NAME, source=SOURCE, crawled_at=payload.get("crawled_at"))

    # 4) Pandas 清洗
    excel_payload = payload
    if args.clean:
        clean, _ = _import_pandas_features()

        frame, report = clean.clean_movies(movies)
        clean.save_clean(frame, outdir, report)
        excel_payload = {
            "source": payload.get("source") or SOURCE,
            "crawled_at": payload.get("crawled_at"),
            "cleaned_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "total": int(len(frame)),
            "movies": frame.to_dict(orient="records"),
            "report": report.as_dict(),
        }

    # 5) Excel 导出
    if args.xlsx:
        _, excel = _import_pandas_features()

        excel.write_workbook(excel_payload, outdir / XLSX_NAME)

    if interrupted:
        logger.warning("本次只抓到部分页（共 %d 条）已保存，补抓请重复执行 `--resume`", len(movies))
        return 1
    logger.info("全部完成：共 %d 条，输出目录 %s", len(movies), outdir)
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    setup_logging(level=args.log_level, quiet=args.quiet, log_dir=args.log_dir, to_file=args.log_file)
    if args.use_cookies and not args.cookie_file:
        args.cookie_file = None  # 使用 config.COOKIE_FILE 默认值

    started = time.time()
    try:
        code = run(args)
    except KeyboardInterrupt:
        logger.warning("用户中断（已抓取的数据不会保存）")
        return 130
    except CrawlError as exc:
        logger.error("%s", exc)
        return 1
    except Exception as exc:  # 兜底：把意外异常写进日志而不是抛裸栈
        logger.exception("未预期的错误：%s: %s", type(exc).__name__, exc)
        return 1

    logger.info("耗时 %.1fs，退出码 %d", time.time() - started, code)
    return code


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())


__all__ = ["main", "run", "build_parser"]
