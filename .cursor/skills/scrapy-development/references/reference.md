# Scrapy 开发参考

## 常用命令（项目根、.venv）

```powershell
.\.venv\Scripts\scrapy.exe crawl <spider_name> -o result.json
.\.venv\Scripts\scrapy.exe crawl <spider_name> -a pages=5 -o result.json -s CLOSESPIDER_PAGECOUNT=5
.\.venv\Scripts\scrapy.exe list
.\.venv\Scripts\scrapy.exe genspider <name> <domain>
```

## 爬虫常用 custom_settings

```python
custom_settings = {
    "ROBOTSTXT_OBEY": False,
    "COOKIES_ENABLED": False,
    "HTTPERROR_ALLOW_ALL": True,
    "DEFAULT_REQUEST_HEADERS": {"User-Agent": "...", "Accept": "..."},
}
```

## 中间件中 .onion 请求（socks5h）

```python
SOCKS5_PROXY = "socks5h://172.16.138.114:59699"
proxies = {"http": SOCKS5_PROXY, "https": SOCKS5_PROXY}
resp = requests.get(request.url, proxies=proxies, headers=..., timeout=90)
return HtmlResponse(url=resp.url, status=resp.status_code, body=resp.content, ...)
```

## Item 与 parse 示例

```python
# items.py
class MyItem(scrapy.Item):
    url = scrapy.Field()
    title = scrapy.Field()
    crawl_time = scrapy.Field()

# spider
from test_work.items import MyItem
def parse(self, response):
    if response.status != 200:
        return
    for sel in response.css("div.item"):
        yield MyItem(
            url=response.urljoin(sel.css("a::attr(href)").get()),
            title=sel.css("h2::text").get(),
            crawl_time=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        )
```

## 浏览器工具速查

- `browser_navigate`：打开 URL
- `browser_snapshot`：获取可访问的 DOM 快照，用于写选择器
- `browser_click` / `browser_fill`：交互后再次 snapshot 查看动态内容
