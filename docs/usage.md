# 命令行用法参考

入口是项目根目录的 `bot.py`（也可以用 `python -m douban_top250`，两者等价）：

```bash
python bot.py --help          # 查看全部参数
python bot.py --version       # 版本号
```

参数按功能分为五组，下面列出全部选项、默认值与作用。默认值以 `douban_top250/config.py` 为准。

## 抓取

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--pages N` | `10` | 抓取页数，取值 1–10（一页 25 条） |
| `--from-json 路径` | 无 | 不从网络抓取，改为读取本地 JSON 结果（离线重跑清洗与报表） |
| `--preview N` | `10` | 控制台预览条数，`0` 表示不打印 |
| `--outdir 目录` | `output/` | 输出目录，可用环境变量 `DOUBAN_OUTPUT_DIR` 覆盖 |
| `--resume` | 关闭 | 断点续传：读已有 JSON，只补抓缺失的页，抓完与本地合并 |
| `--refresh` | 关闭 | 配合 `--resume`：即使本地已有也重抓所选页（刷新榜单头部） |
| `--only-pages 1,3,5-7` | 无 | 只抓指定页（支持 `3-7` 区间与中文逗号），被限流时小批量补刷 |
| `--shuffle-pages` | 关闭 | 打乱页序，避免 `start=0/25/50…` 这种机械翻页特征 |
| `--seed N` | 无 | 打乱页序的随机种子，便于复现同一次抓取顺序 |

## 网络与反爬

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--proxy URL` | 无 | 单个代理，例如 `http://127.0.0.1:7890` |
| `--proxy-file 文件` | 无 | 代理列表文件（每行一个，`#` 开头为注释），被拦截时自动轮换出口 IP |
| `--direct` | 关闭 | 忽略系统代理，强制直连 |
| `--delay MIN MAX` | `3 6` | 每次请求前的随机延时区间（秒） |
| `--cooldown-every N` | `4` | 每抓 N 页长休息一次，`0` 表示不休息 |
| `--cooldown MIN MAX` | `25 45` | 长休息的随机秒数区间 |
| `--no-warmup` | 预热开启 | 跳过"先访问首页拿 `bid`/`ll` cookie"的预热步骤 |
| `--timeout N` | `20` | 单次请求超时（秒） |
| `--retries N` | `4` | 单页最大尝试次数（网络错误重试） |
| `--max-block-retries N` | `2` | 同一出口被风控拦截几次后换出口或放弃；硬重试会延长封禁 |

## Cookie 持久化

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--no-cookies` | cookie 读写开启 | 不读写本地 cookie 文件（`.cache/douban_cookies.json`） |
| `--cookie-file 路径` | `.cache/douban_cookies.json` | 自定义 cookie 文件位置 |
| `--cookie-string "bid=…; dbcl2=…; ck=…"` | 无 | 注入浏览器复制出来的登录 Cookie（也支持 `Cookie:` 前缀与换行分隔） |

> `--cookie-string` 传的是你本人的账号凭据：不要外传、不要提交到版本库。

## 输出开关

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--no-csv` | CSV 开启 | 不保存 `douban_top250.csv` |
| `--no-json` | JSON 开启 | 不保存 `douban_top250.json`（同时也是每页检查点文件） |
| `--no-xlsx` | Excel 开启 | 不生成 `douban_top250.xlsx` |
| `--no-clean` | 清洗开启 | 跳过 Pandas 清洗（不产出 `douban_top250_clean.*`） |

## 日志

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--log-level LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `--log-dir 目录` | `logs/` | 日志目录 |
| `--no-log-file` | 写文件开启 | 不写日志文件（只输出到控制台） |
| `--quiet` | 关闭 | 控制台只输出警告及以上（同时抑制预览表格） |

## 常用组合

```bash
# 全量抓取：10 页 250 条 -> CSV/JSON -> 清洗 -> Excel
python bot.py

# 离线重跑清洗与 Excel（完全不联网）
python bot.py --from-json output/douban_top250.json --clean

# 被限流后小批量补刷指定的 4 页
python bot.py --resume --only-pages 1,2,5,8 --delay 5 10 --cooldown-every 2 --cooldown 60 90

# 日常只刷新榜单前 2 页（增量更新票数）
python bot.py --resume --refresh --pages 2

# 带代理池与登录 Cookie 的全量抓取（换出口 + 提高配额）
python bot.py --resume --proxy-file proxies.txt --cookie-string "bid=…; dbcl2=…; ck=…" \
    --pages 3 --delay 5 10 --cooldown-every 2 --cooldown 60 120 --shuffle-pages

# 只要原始数据，不做清洗与 Excel
python bot.py --pages 2 --no-clean --no-xlsx

# 只把已有 JSON 转成 Excel（不抓取、不清洗；列数取决于 JSON 是否含派生列）
python -m douban_top250.excel output/douban_top250.json output/douban_top250.xlsx

# 排查问题时看详细日志
python bot.py --resume --pages 1 --log-level DEBUG
```

## 退出码

| 退出码 | 含义 |
| --- | --- |
| `0` | 成功（含离线模式；被风控中断但已保存部分数据时不返回 0） |
| `1` | 失败：网络/风控错误、`--only-pages` 没有有效页码、输入文件不存在、无数据可输出 |
| `1` | **部分成功**：翻页中途被风控拦截，本次抓到的页已写入 JSON 检查点，日志会提示用 `--resume` 续跑 |
| `130` | 用户按 `Ctrl+C` 中断（当次数据不落盘） |

## 环境变量

| 变量 | 作用 |
| --- | --- |
| `DOUBAN_OUTPUT_DIR` | 覆盖默认输出目录 `output/`（也会影响 `--resume` 读取检查点的位置） |

## 输出文件

| 文件 | 内容 |
| --- | --- |
| `output/douban_top250.csv` | 原始 13 字段，`utf-8-sig` 编码 |
| `output/douban_top250.json` | `source` / `crawled_at` / `total` / `movies`，也是断点续传的检查点 |
| `output/douban_top250_clean.csv` | 清洗后数据（含派生列） |
| `output/douban_top250_clean.json` | 清洗后数据 + 清洗报告 `report` |
| `output/douban_top250.xlsx` | Excel 报表：`Top250` 数据表 + `统计概览` |
| `logs/douban_top250.log` | 轮转日志（单文件 1 MB，保留 3 份） |
| `.cache/douban_cookies.json` | 会话 cookie，复用以降低风控概率 |

## 相关文档

- [README.md](../README.md)：项目概览、快速开始、核心设计
- [anti-bot.md](anti-bot.md)：限流机理、实测时间线、内置对策与处置手册
