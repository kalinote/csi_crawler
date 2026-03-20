---
name: scrapy-development
description: Guides Scrapy project development: understand project structure and target site (with browser tools) before coding, enforce consistent spider/item/middleware patterns, and standardize output. Use when creating or modifying Scrapy spiders, middlewares, items, crawling a new site, or integrating a spider into an existing project.
---

# Scrapy 开发技能

## 1. 开发前：了解项目结构

在写或改爬虫前，先确认当前 Scrapy 项目布局：

- **项目根**：含 `scrapy.cfg` 的目录；`[settings] default = <项目名>.settings` 指向设置模块。
- **包目录**：与项目同名的子目录（如 `test_work/test_work/`），内含：
  - `spiders/`：所有爬虫，单文件一爬虫，`name`、`allowed_domains`、`start_requests`/`start_urls`、parse 回调。
  - `items.py`：Item 类与字段定义，爬虫中 `from <项目名>.items import XxxItem`。
  - `middlewares.py`：下载/爬虫中间件，如代理、UA、重试。
  - `settings.py`：全局配置；爬虫可用 `custom_settings` 覆盖。
  - `pipelines.py`：清洗、去重、入库等（可选）。
- **运行**：必须在项目根下用 **.venv** 执行，例如 ` .\.venv\Scripts\scrapy.exe crawl <spider_name>`，不要用系统 Python。

若项目不存在，先用 `scrapy startproject <name>` 和 `scrapy genspider <spider_name> <domain>` 生成再开发。

## 2. 开发前：了解目标网站（用浏览器工具）

在写选择器、API 地址或翻页逻辑前，先用浏览器工具摸清目标站：

1. **打开页面**：`browser_navigate` 到目标 URL（列表页、详情页、API 文档等）。
2. **看结构**：`browser_snapshot` 看 DOM/可访问结构，确认列表容器、链接、分页、表格或接口返回格式。
3. **确认关键元素**：需要采集的字段在哪些标签、属性（如 `data-id`、`class`）；是服务端渲染 HTML 还是前端请求 JSON API。
4. **链接与分页**：从 snapshot 或 `browser_click` 跟踪“下一页”、筛选、Tab，确认 URL 规律（如 `?page=2`、`/page/2`）。
5. **.onion 或需登录**：若为 Tor 站或需 Cookie/登录，在中间件里配代理或 Cookie，并先用 `mcp_web_fetch` 或脚本验证可访问性。

避免不看页面就写 XPath/CSS；先 snapshot 再写选择器，减少反复试错。

## 3. 代码结构一致性

- **爬虫**：
  - 一个文件一个爬虫类，`name`、`allowed_domains` 必填；`start_requests` 或 `start_urls` 二选一。
  - 解析逻辑集中在 `parse` 或具名 callback（如 `parse_api`、`parse_list`），不在回调里堆重复代码；可抽辅助方法。
  - 需要时用 `custom_settings`（如 `ROBOTSTXT_OBEY`、`COOKIES_ENABLED`、`HTTPERROR_ALLOW_ALL`、请求头）。
- **Item**：
  - 所有字段在 `items.py` 中定义；爬虫只做 `yield XxxItem(...)`，不临时造字典再转。
  - 字段名与现有 Item 风格一致（如已有 `url`、`title`、`crawl_time`，新 Item 尽量复用或保持命名风格）。
- **代理**：
  - 普通站走 HTTP 代理（在 middlewares 里设 `request.meta["proxy"]`）。
  - **.onion 必须用 socks5h**（`socks5h://host:port`），不能用 `socks5`，否则本地解析 .onion 会 getaddrinfo 失败。
- **运行环境**：所有命令通过 `.venv`（如 ` .\.venv\Scripts\scrapy.exe`、` .\.venv\Scripts\python.exe`）；注释与日志使用中文。

## 4. 输出方式限制

- **默认输出到文件**：使用 `-o` 指定路径，如 `-o result.json` 或 `-o result.csv`；不依赖仅打印到控制台。
- **限制爬取范围**：需要时用 `-s CLOSESPIDER_PAGECOUNT=N` 限制请求页数，避免全站跑满。
- **编码**：保持 `FEED_EXPORT_ENCODING = "utf-8"`（通常在 settings 已配置）。
- **格式选择**：JSON 适合结构化条目；CSV 适合表格化、Excel 后续处理；不在技能内新增其他未约定格式除非用户明确要求。

## 5. 流程检查清单

开发或修改爬虫时按顺序确认：

```
- [ ] 已确认项目根、spiders/、items.py、middlewares、settings 位置
- [ ] 已用 browser_navigate + browser_snapshot 看过目标页/API 结构
- [ ] 选择器或 API 路径与当前页面结构一致
- [ ] Item 在 items.py 定义，爬虫中 import 并 yield
- [ ] .onion 使用 socks5h，普通站使用 HTTP 代理（若需代理）
- [ ] 使用 .venv 运行，输出用 -o 写入文件，必要时加 CLOSESPIDER_PAGECOUNT
```

## 6. 参考

- 代理与 .onion：见项目内 `.cursor/rules/scrapy-project.mdc`（socks5h 说明与示例）。
- 更细的 Scrapy API 与配置见 [reference.md](references/reference.md)。
