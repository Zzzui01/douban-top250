# 反爬对抗与限流处置

本文记录豆瓣 Top250 列表页风控的实际表现、取证过程，以及本项目内置的对策与处置手册。
结论基于 2026-10 前后的**匿名访问**场景，站点策略随时可能变化。

## 1. 定性结论

- **逐请求打分，不是"封 IP 就全拒"**：被拦后 20 秒重开会话，前两个请求依然正常返回（见下表 12:43 → 12:44:57）。
- **滚动窗口配额**：同一个出口连续请求列表页，大约**第 4–6 个请求**之后开始持续拿到风控页；
  窗口尺度是**几十分钟**——静默 30–48 分钟后又能通过 4–6 个请求。
- **拦截响应多为 HTTP 200**：内容是"检测到有异常请求"页面，有时跳 `sec.douban.com` 或 `captcha`。
  只看状态码会漏判，因此 `config.ANTI_BOT_MARKS` 与 `config.BLOCK_STATUS_CODES`（403/418/429）
  一起判定，实现见 `douban_top250/parse.py::is_anti_bot_html()` 与
  `douban_top250/fetch.py::Fetcher._is_blocked()`。
- **长休息没有用**：被拦前休息 35–45 秒照样被拦（下表 12:43、12:45 两次），短时休眠不能重置窗口。
- **可恢复，不是永久封禁**：静默等待是最便宜的解药。

## 2. 实测时间线（2026-10-08，日志原样取证）

| 时刻 | 行为 | 结果 |
| --- | --- | --- |
| 12:30:44 | 单页冒烟（默认节奏） | 成功 |
| 12:43:25 | 全量 10 页，第 1–4 页成功，第 4 页后休息 43.6s | **第 5 个请求（第 5 页）被拦**，重试 2 次后止损退出 |
| 12:44:57 | 距上次被拦仅 20 秒，新会话抓第 1–2 页 | **全部成功** → 不是 IP 硬封 |
| 12:45:19 | 又一次全量 10 页，第 1–4 页成功，休息 35s | **第 5 个请求被拦** |
| 12:50:25 | 断点续传抓第 3–6 页，休息 45s | **第 5 个请求（第 7 页）被拦** |
| 13:39:45 | 打乱页序 + `--delay 5 10 --cooldown-every 3 --cooldown 60 90` | 连过 6 个请求后**第 7 个被拦** |
| 14:17:17 | 静默 34 分钟后只抓 4 页（`--only-pages 1,2,5,8`） | **4 个请求全部成功，退出码 0**（117.6s） |

读法：**每次被拦都发生在第 5–7 个请求**，中间的长休息都没帮上忙，唯一有效的是那段静默。

## 3. 为什么 2026-10-06 能一次抓完 10 页

那次的数据事实：`crawled_at = 2026-10-06 00:07:37`，10 页 250 条、**110 秒、零 403**、
两次长休息 33.1s / 26.1s，用的是默认 `--delay 3 6`。成功的四个前提：

1. 此前吃过 403 后我停手了一段时间，出口 IP 是"冷"的；
2. 孤立的一次抓取，前后没有别的请求；
3. **凌晨 00:07**，站点低峰，阈值更松；
4. 只用了一个出口、一次会话。

关键反证：今天中午用的节奏**比那天更慢**（5–10s 延时 + 60–90s 长休息）却更早被拦，
说明**问题不是"太快"，而是同一个出口在短时间内被请求太多次**。

## 4. 内置对策（含实现位置）

| 对策 | 实现 | 默认 |
| --- | --- | --- |
| 会话预热：先 GET 首页拿 `bid`/`ll` 再翻页 | `fetch.py::Fetcher.warm_up()` | 开启（`--no-warmup` 关闭） |
| cookie 持久化复用 | `fetch.py::load_cookies/save_cookies`、`Fetcher.restore_cookies()/persist_cookies()` | `.cache/douban_cookies.json` |
| 注入登录态 Cookie | `fetch.py::parse_cookie_string()/apply_cookie_string()` | `--cookie-string` |
| Referer 链式伪装（指向真实上一次访问的 URL） | `Fetcher.get()` 中 `self.session.headers["Referer"] = self._last_url` | 开启 |
| UA 轮换（4 个浏览器 UA，逐请求随机） | `config.USER_AGENTS` | 开启 |
| 随机延时 | `Fetcher._sleep_before_request()` | `--delay 3 6` |
| 长休息 | `crawler.py::crawl_top250(cooldown_every, cooldown)` | `--cooldown-every 4 --cooldown 25 45` |
| 出口轮换（代理池） | `fetch.py::load_proxy_file()` + `Fetcher._switch_session()` | `--proxy-file` |
| 拦截止损（无可用出口就终止） | `Fetcher.get()` 中 `blocked_rounds >= max_block_retries` | `--max-block-retries 2` |
| 页序打散（消除 `0,25,50…` 指纹） | `crawler.py::resolve_page_order(shuffle=True)` | `--shuffle-pages --seed` |
| 每页检查点（被拦也保住已抓数据） | `cli.py::write_checkpoint()` + `on_page` 回调 | 开启（`--no-json` 关闭） |
| 断点续传 / 精确补页 | `crawler.py::missing_pages()` + `storage.py::merge_movies()` | `--resume / --refresh / --only-pages` |
| 系统代理异常时自动直连 | `Fetcher` 的"系统代理会话 + 直连备用会话" | 自动 |

## 5. 被限流了怎么办（按有效性排序）

1. **先停手 30 分钟以上**——成本最低且必做，期间继续跑只会加重标记。
2. **换出口 IP（最有效）**：代理写进 `proxies.txt` 后
   `python bot.py --resume --proxy-file proxies.txt`，被拦会自动换下一个出口；
   没有代理池就用**手机热点**或重启光猫换公网 IP，立竿见影。
3. **带上登录 Cookie**：浏览器登录豆瓣 → F12 → Network → 任意请求 → 复制 `Cookie` 请求头 →
   `python bot.py --resume --cookie-string "bid=…; dbcl2=…; ck=…"`。
4. **分批 + 断点续传**：单批 ≤4 页、两批间隔 ≥30 分钟，
   `python bot.py --resume --only-pages 1,2,5,8`。每抓完一页都落盘，被拦也不丢数据。
5. **日常只刷新头部**：`python bot.py --resume --refresh --pages 2`，只要 2 个请求。
6. **打乱页序**：`--shuffle-pages`（可配 `--seed` 复现）。
7. **进一步放慢**：`--delay 5 10 --cooldown-every 2 --cooldown 60 90`——有效但有限，别指望它解决问题。
8. **不要硬刚**：早期的指数退避重试（10/20/40/60 秒 × 4 次）实测**延长了封禁时间**。
   本项目 `--max-block-retries 2` 的默认值就是这个教训的产物。

## 6. 可持续的运行节奏（推荐）

- 单批 ≤4 页，两批之间 ≥30 分钟，每天总量控制在 20–30 个列表页请求以内；
- 日常维护：`python bot.py --resume --refresh --pages 2`；
- 首次全量或换 IP 后一次抓完是可以的，但**别在 90 分钟内反复全量**；
- 榜单每天变化很小：把刷新降到每天一次，比研究怎么绕过风控省事得多，也不会给站点添麻烦。

## 7. 兜底方案（本项目未内置）

用 Playwright 驱动本机 Chrome、挂已登录的持久化 Profile：TLS/JS 指纹与真人一致，几乎不会被 WAF 拦。
代价是多一个很重的依赖、运行更慢，需要时再单独加。

## 8. 怎么自己验证"滚动窗口配额"这个结论

- **换 IP 对照**：同一台机器、同一条命令，用手机热点跑 `python bot.py --refresh`（10 页）。
  能一次通过 → 是本出口 IP 的信誉问题；新 IP 也只给 4–6 个请求 → 是站点收紧了匿名配额。
- **时段对照**：在凌晨低峰复刻 2026-10-06 的条件再跑一次。
- **日志取证**：`logs/douban_top250.log`（1 MB × 3 轮转）逐条记录请求时刻与结果，
  `--log-level DEBUG` 可以得到更细的请求过程。

## 9. 系统代理的 TLS 坑

系统代理开启时（如 `127.0.0.1:7890`），`requests` 可能抛
`ValueError: check_hostname requires server_hostname`（TLS-in-TLS）。
`Fetcher` 默认构造"系统代理会话 + 直连备用会话"，出错自动切换；也可以 `--direct` 强制直连，
或用 `--proxy` 指定可用代理。

---

> 本文与项目代码仅用于学习与统计研究。请遵守目标站点协议与相关法律法规，
> 不要把频率压到影响站点的程度，也不要用于商业用途或大规模抓取。
