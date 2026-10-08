# -*- coding: utf-8 -*-
"""命令行测试：参数默认值、离线端到端（--from-json）与失败退出码。"""

from __future__ import annotations

import json
import logging

import pytest

from douban_top250 import cli
from douban_top250.config import (
    CLEAN_CSV_NAME,
    CLEAN_JSON_NAME,
    CSV_NAME,
    DEFAULT_COOLDOWN,
    DEFAULT_DELAY,
    DEFAULT_PREVIEW,
    JSON_NAME,
    MAX_PAGES,
    XLSX_NAME,
)
from douban_top250.exceptions import AntiBotError

pytest.importorskip("pandas")
openpyxl = pytest.importorskip("openpyxl")


@pytest.fixture
def json_source(tmp_path, sample_payload):
    path = tmp_path / "douban_top250.json"
    path.write_text(json.dumps(sample_payload, ensure_ascii=False), encoding="utf-8")
    return path


def offline_args(tmp_path, source, *extra):
    return [
        "--from-json", str(source),
        "--outdir", str(tmp_path / "out"),
        "--preview", "0",
        "--quiet",
        "--no-log-file",
    ] + list(extra)


def test_parser_defaults():
    args = cli.build_parser().parse_args([])

    assert args.pages == MAX_PAGES == 10
    assert args.preview == DEFAULT_PREVIEW == 10
    assert args.delay == list(DEFAULT_DELAY)
    assert args.cooldown == list(DEFAULT_COOLDOWN)
    assert args.clean is True and args.xlsx is True and args.csv is True and args.json is True
    assert args.use_cookies is True and args.warmup is True
    assert args.direct is False and args.proxy is None


def test_parser_accepts_custom_delay_and_switches():
    args = cli.build_parser().parse_args(
        ["--delay", "1", "2", "--cooldown-every", "0", "--no-clean", "--no-xlsx", "--direct", "--pages", "3"]
    )

    assert args.delay == [1.0, 2.0]
    assert args.cooldown_every == 0
    assert args.clean is False and args.xlsx is False
    assert args.direct is True
    assert args.pages == 3


def test_offline_run_writes_csv_and_json(tmp_path, json_source):
    code = cli.main(offline_args(tmp_path, json_source, "--no-clean", "--no-xlsx"))

    assert code == 0
    outdir = tmp_path / "out"
    assert (outdir / CSV_NAME).is_file()
    assert (outdir / JSON_NAME).is_file()
    assert not (outdir / XLSX_NAME).exists()

    payload = json.loads((outdir / JSON_NAME).read_text(encoding="utf-8"))
    assert payload["total"] == 3
    assert [row["rank"] for row in payload["movies"]] == [1, 2, 3]


def test_offline_run_with_clean_and_excel(tmp_path, json_source):
    code = cli.main(offline_args(tmp_path, json_source))

    assert code == 0
    outdir = tmp_path / "out"
    for name in (CSV_NAME, JSON_NAME, CLEAN_CSV_NAME, CLEAN_JSON_NAME, XLSX_NAME):
        assert (outdir / name).is_file(), name

    cleaned = json.loads((outdir / CLEAN_JSON_NAME).read_text(encoding="utf-8"))
    assert cleaned["report"]["total_out"] == 3
    assert cleaned["movies"][0]["decade"] == "1990 年代"

    workbook = openpyxl.load_workbook(str(outdir / XLSX_NAME))
    headers = [cell.value for cell in workbook["Top250"][2]]
    assert "年代" in headers and "评价人数(万)" in headers   # 清洗派生列会自动追加


def test_offline_run_without_outputs_only_validates_input(tmp_path, json_source):
    code = cli.main(offline_args(tmp_path, json_source, "--no-csv", "--no-json", "--no-clean", "--no-xlsx"))

    assert code == 0
    assert not (tmp_path / "out" / CSV_NAME).exists()


def test_main_returns_1_for_missing_json(tmp_path):
    code = cli.main(offline_args(tmp_path, tmp_path / "missing.json", "--no-clean", "--no-xlsx"))

    assert code == 1


def test_main_returns_1_when_crawl_is_blocked(tmp_path, monkeypatch):
    def blocked(**kwargs):
        raise AntiBotError("被反爬拦截 HTTP 403")

    monkeypatch.setattr(cli, "crawl_top250", blocked)

    code = cli.main(["--outdir", str(tmp_path / "out"), "--preview", "0", "--quiet", "--no-log-file"])

    assert code == 1


def test_main_returns_1_when_crawl_yields_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "crawl_top250", lambda **kwargs: [])

    code = cli.main(["--outdir", str(tmp_path / "out"), "--preview", "0", "--quiet", "--no-log-file"])

    assert code == 1


def test_main_handles_keyboard_interrupt(tmp_path, monkeypatch):
    def interrupted(**kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "crawl_top250", interrupted)

    code = cli.main(["--outdir", str(tmp_path / "out"), "--preview", "0", "--quiet", "--no-log-file"])

    assert code == 130


def test_run_offline_mode_reports_source(tmp_path, json_source, caplog, monkeypatch):
    # setup_logging 会把包日志的 propagate 关掉（避免与 root 重复输出），
    # 这里临时打开，才能用 caplog 断言日志内容。
    monkeypatch.setattr(logging.getLogger("douban_top250"), "propagate", True)

    with caplog.at_level("INFO", logger="douban_top250.cli"):
        code = cli.run(cli.build_parser().parse_args(offline_args(tmp_path, json_source, "--no-clean", "--no-xlsx")))

    assert code == 0
    assert any("离线模式" in record.getMessage() for record in caplog.records)


# --------------------------------------------------------------------------- #
# 断点续传 / 反限流开关
# --------------------------------------------------------------------------- #
def write_local_json(outdir, ranks, prefix="本地"):
    from douban_top250.models import Movie
    from douban_top250.storage import build_payload

    outdir.mkdir(parents=True, exist_ok=True)
    movies = [Movie(rank=rank, title="{}{}".format(prefix, rank), rating=9.0, votes=1000)
              for rank in ranks]
    path = outdir / JSON_NAME
    path.write_text(json.dumps(build_payload(movies), ensure_ascii=False), encoding="utf-8")
    return path


def quiet_online_args(outdir, *extra):
    return ["--outdir", str(outdir), "--preview", "0", "--quiet", "--no-log-file",
            "--no-clean", "--no-xlsx"] + list(extra)


def test_page_text_helper():
    assert cli._page_text([1, 2, 3]) == "1-3"
    assert cli._page_text([3]) == "3"
    assert cli._page_text([1, 3, 5]) == "1, 3, 5"
    assert cli._page_text([]) == "无"


def test_parser_defaults_for_anti_block_options():
    args = cli.build_parser().parse_args([])

    assert args.resume is False and args.refresh is False
    assert args.shuffle_pages is False and args.seed is None
    assert args.proxy_file is None and args.cookie_string is None


def test_parser_accepts_anti_block_options():
    args = cli.build_parser().parse_args([
        "--resume", "--refresh", "--shuffle-pages", "--seed", "7",
        "--proxy-file", "proxies.txt", "--cookie-string", "bid=1; ll=2",
    ])

    assert args.resume is True and args.refresh is True
    assert args.shuffle_pages is True and args.seed == 7
    assert args.proxy_file == "proxies.txt"
    assert args.cookie_string == "bid=1; ll=2"


def test_resume_only_crawls_missing_pages_and_merges(tmp_path, monkeypatch):
    from douban_top250.models import Movie

    outdir = tmp_path / "out"
    write_local_json(outdir, range(1, 26))
    recorded = {}

    def fake_crawl(**kwargs):
        recorded.update(kwargs)
        return [Movie(rank=rank, title="新{}".format(rank), rating=9.1, votes=2000)
                for rank in range(26, 51)]

    monkeypatch.setattr(cli, "crawl_top250", fake_crawl)

    code = cli.main(quiet_online_args(outdir, "--resume", "--pages", "2"))

    assert code == 0
    assert recorded["order"] == [2]              # 第 1 页本地已有，不再请求
    payload = json.loads((outdir / JSON_NAME).read_text(encoding="utf-8"))
    assert payload["total"] == 50
    assert [row["rank"] for row in payload["movies"]] == list(range(1, 51))
    assert payload["movies"][0]["title"] == "本地1"     # 本地数据保留
    assert payload["movies"][25]["title"] == "新26"     # 新数据覆盖同排名


def test_resume_skips_network_when_local_is_complete(tmp_path, monkeypatch):
    outdir = tmp_path / "out"
    write_local_json(outdir, range(1, 51))
    calls = []

    monkeypatch.setattr(cli, "crawl_top250", lambda **kwargs: calls.append(kwargs))

    code = cli.main(quiet_online_args(outdir, "--resume", "--pages", "2"))

    assert code == 0
    assert calls == []                            # 完全没有联网抓取
    payload = json.loads((outdir / JSON_NAME).read_text(encoding="utf-8"))
    assert payload["total"] == 50


def test_resume_refresh_recrawls_selected_pages(tmp_path, monkeypatch):
    from douban_top250.models import Movie

    outdir = tmp_path / "out"
    write_local_json(outdir, range(1, 51))
    recorded = {}

    def fake_crawl(**kwargs):
        recorded.update(kwargs)
        return [Movie(rank=1, title="刷新1", rating=9.9, votes=1)]

    monkeypatch.setattr(cli, "crawl_top250", fake_crawl)

    code = cli.main(quiet_online_args(outdir, "--resume", "--refresh", "--pages", "1"))

    assert code == 0
    assert recorded["order"] == [1]
    payload = json.loads((outdir / JSON_NAME).read_text(encoding="utf-8"))
    assert payload["total"] == 50
    assert payload["movies"][0]["title"] == "刷新1"
    assert payload["movies"][1]["title"] == "本地2"


def test_resume_without_local_file_crawls_everything(tmp_path, monkeypatch):
    from douban_top250.models import Movie

    outdir = tmp_path / "out"
    recorded = {}

    def fake_crawl(**kwargs):
        recorded.update(kwargs)
        return [Movie(rank=rank, title="新{}".format(rank)) for rank in range(1, 26)]

    monkeypatch.setattr(cli, "crawl_top250", fake_crawl)

    code = cli.main(quiet_online_args(outdir, "--resume", "--pages", "1"))

    assert code == 0
    assert recorded["order"] == [1]


def test_run_wires_proxy_pool_and_cookie_string(tmp_path, monkeypatch):
    from douban_top250.models import Movie

    proxies = tmp_path / "proxies.txt"
    proxies.write_text("# 注释\nhttp://a:1\nhttp://b:2\n", encoding="utf-8")
    seen = {}

    def fake_crawl(**kwargs):
        seen["fetcher"] = kwargs["fetcher"]
        seen["shuffle"] = kwargs["shuffle"]
        seen["seed"] = kwargs["seed"]
        return [Movie(rank=1, title="x")]

    monkeypatch.setattr(cli, "crawl_top250", fake_crawl)

    code = cli.main(quiet_online_args(
        tmp_path / "out", "--proxy-file", str(proxies), "--cookie-string", "bid=abc; dbcl2=xyz",
        "--shuffle-pages", "--seed", "3",
    ))

    assert code == 0
    fetcher = seen["fetcher"]
    assert len(fetcher.sessions) == 2
    assert fetcher.sessions[0].proxies["https"] == "http://a:1"
    assert fetcher.sessions[1].proxies["https"] == "http://b:2"
    assert fetcher.sessions[0].cookies.get("dbcl2") == "xyz"
    assert seen["shuffle"] is True and seen["seed"] == 3


# --------------------------------------------------------------------------- #
# 每页检查点：被拦在半路也不白跑
# --------------------------------------------------------------------------- #
def test_blocked_midway_keeps_fetched_pages(tmp_path, monkeypatch):
    from douban_top250.models import Movie

    outdir = tmp_path / "out"
    write_local_json(outdir, range(1, 26))
    page_one = [Movie(rank=rank, title="第二页{}".format(rank)) for rank in range(26, 51)]
    page_two = [Movie(rank=rank, title="第三页{}".format(rank)) for rank in range(51, 76)]

    def fake_crawl(**kwargs):
        kwargs["on_page"](2, 3, page_one)
        kwargs["on_page"](3, 3, page_two)
        raise AntiBotError("被反爬拦截 HTTP 200（https://movie.douban.com/top250）")

    monkeypatch.setattr(cli, "crawl_top250", fake_crawl)

    code = cli.main(quiet_online_args(outdir, "--resume", "--pages", "3"))

    assert code == 1                                   # 没抓完，如实返回 1
    payload = json.loads((outdir / JSON_NAME).read_text(encoding="utf-8"))
    assert payload["total"] == 75                      # 本地 25 + 已抓到的 50 条全部保留
    assert [row["rank"] for row in payload["movies"]] == list(range(1, 76))
    assert payload["movies"][25]["title"] == "第二页26"
    assert (outdir / CSV_NAME).is_file()               # 已有数据仍然照常导出


def test_blocked_before_any_page_saves_nothing(tmp_path, monkeypatch):
    outdir = tmp_path / "out"

    def fake_crawl(**kwargs):
        raise AntiBotError("被反爬拦截 HTTP 200（https://movie.douban.com/top250）")

    monkeypatch.setattr(cli, "crawl_top250", fake_crawl)

    code = cli.main(quiet_online_args(outdir))

    assert code == 1
    assert not (outdir / JSON_NAME).exists()           # 一条都没抓到，不写检查点
    assert not (outdir / CSV_NAME).exists()


def test_no_json_disables_checkpoint(tmp_path, monkeypatch):
    from douban_top250.models import Movie

    outdir = tmp_path / "out"
    recorded = {}

    def fake_crawl(**kwargs):
        recorded.update(kwargs)
        return [Movie(rank=1, title="唯一")]

    monkeypatch.setattr(cli, "crawl_top250", fake_crawl)

    code = cli.main(quiet_online_args(outdir, "--no-json"))

    assert code == 0
    assert recorded["on_page"] is None                 # --no-json 时不落检查点
    assert not (outdir / JSON_NAME).exists()


# --------------------------------------------------------------------------- #
# --only-pages：被限流时小批量补刷指定页
# --------------------------------------------------------------------------- #
def test_parse_page_list_helper():
    assert cli.parse_page_list("1,3,5") == [1, 3, 5]
    assert cli.parse_page_list("5-7") == [5, 6, 7]
    assert cli.parse_page_list("3,1,3, 2") == [1, 2, 3]      # 去重并排序
    assert cli.parse_page_list("1，4") == [1, 4]             # 容忍中文逗号
    assert cli.parse_page_list("1, 3-4") == [1, 3, 4]
    assert cli.parse_page_list("0,11,abc,-") == []           # 越界与非数字全部丢弃
    assert cli.parse_page_list("") == []
    assert cli.build_parser().parse_args([]).only_pages is None


def test_only_pages_crawls_exactly_those_pages(tmp_path, monkeypatch):
    from douban_top250.models import Movie

    outdir = tmp_path / "out"
    write_local_json(outdir, range(1, 26))
    recorded = {}

    def fake_crawl(**kwargs):
        recorded.update(kwargs)
        return [Movie(rank=rank, title="刷新{}".format(rank)) for rank in range(26, 51)]

    monkeypatch.setattr(cli, "crawl_top250", fake_crawl)

    code = cli.main(quiet_online_args(outdir, "--resume", "--only-pages", "2,4"))

    assert code == 0
    assert recorded["order"] == [2, 4]                       # 一次只抓这两页
    payload = json.loads((outdir / JSON_NAME).read_text(encoding="utf-8"))
    assert payload["total"] == 50                            # 与本地数据合并
    assert payload["movies"][0]["title"] == "本地1"


def test_only_pages_rejects_input_without_valid_page(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "crawl_top250", lambda **kwargs: calls.append(kwargs))

    code = cli.main(quiet_online_args(tmp_path / "out", "--only-pages", "0,99"))

    assert code == 1
    assert calls == []                                       # 不发起任何请求


def test_only_pages_without_resume_replaces_dataset(tmp_path, monkeypatch):
    from douban_top250.models import Movie

    outdir = tmp_path / "out"
    write_local_json(outdir, range(1, 26))

    monkeypatch.setattr(cli, "crawl_top250",
                        lambda **kwargs: [Movie(rank=1, title="新1")])

    code = cli.main(quiet_online_args(outdir, "--only-pages", "1"))

    assert code == 0
    payload = json.loads((outdir / JSON_NAME).read_text(encoding="utf-8"))
    assert payload["total"] == 1                             # 没加 --resume 就只留这几页
