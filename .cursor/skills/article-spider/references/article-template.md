# 新建爬虫代码模板

以下模板基于 BaseSpider + 默认/关键词双模式，按需替换 URL、section_map、选择器或 JSON 路径。

```python
import scrapy
import datetime
from scrapy.http import Response, JsonRequest, JsonResponse
from test_work.items import CSIArticlesItem
from test_work.spiders.base import BaseSpider
from csi_crawlers.utils import generate_uuid


class YourSpider(BaseSpider):
    name = "your_spider"
    allowed_domains = ["example.com"]
    headers = {"content-type": "application/json"}
    section_map = {"要闻": "channel_id_1", "财经": "channel_id_2"}

    def default_start(self, response):
        for section in self.sections:
            if section == "__default__":
                section = "要闻"
            channel_id = self.section_map.get(section)
            if not channel_id:
                self.logger.error(f"未知采集板块: {section}")
                continue
            yield JsonRequest(
                url="https://api.example.com/list",
                headers=self.headers,
                data={"channelId": channel_id, "pageNum": 1, "pageSize": 50},
                callback=self.parse_default_list,
                meta={"current_page": 1, "section": section},
            )

    def search_start(self, response):
        for keyword in self.keywords:
            yield JsonRequest(
                url="https://api.example.com/search",
                headers=self.headers,
                data={"word": keyword, "pageNum": 1, "pageSize": 100},
                callback=self.parse_search_list,
                meta={"keyword": keyword, "current_page": 1},
            )

    def parse_default_list(self, response: JsonResponse):
        section = response.meta.get("section", "")
        channel_id = self.section_map.get(section, "")
        if not channel_id:
            return
        data = response.json()
        data_obj = data.get("data", {})
        for item in data_obj.get("list", []):
            yield scrapy.Request(
                url=item.get("detail_url") or f"https://www.example.com/detail_{item.get('id')}",
                callback=self.parse_detail,
                meta={"section": section},
            )
        current_page = response.meta.get("current_page", 1)
        has_next = data_obj.get("hasNext", False)
        should_continue = (self.page is None or self.page <= 0) and has_next or (
            self.page and self.page > 0 and current_page < self.page and has_next
        )
        if should_continue:
            next_page = current_page + 1
            yield JsonRequest(
                url="https://api.example.com/list",
                headers=self.headers,
                data={
                    "channelId": channel_id,
                    "pageNum": next_page,
                    "pageSize": 50,
                    "startTime": data_obj.get("startTime", ""),
                },
                callback=self.parse_default_list,
                meta={"current_page": next_page, "section": section},
            )

    def parse_search_list(self, response: JsonResponse):
        data = response.json()
        data_obj = data.get("data", {})
        for item in data_obj.get("list", []):
            yield scrapy.Request(
                url=item.get("detail_url") or f"https://www.example.com/detail_{item.get('id')}",
                callback=self.parse_detail,
                meta={"section": "关键词搜索"},
            )
        keyword = response.meta.get("keyword")
        current_page = response.meta.get("current_page", 1)
        has_next = data_obj.get("hasNext", False)
        should_continue = (self.page is None or self.page <= 0) and has_next or (
            self.page and self.page > 0 and current_page < self.page
        )
        if should_continue:
            next_page = current_page + 1
            yield JsonRequest(
                url="https://api.example.com/search",
                headers=self.headers,
                data={"word": keyword, "pageNum": next_page, "pageSize": 100},
                callback=self.parse_search_list,
                meta={"keyword": keyword, "current_page": next_page},
            )

    def parse_detail(self, response: Response):
        item = CSIArticlesItem()
        source_id = response.xpath("//@data-id").get() or response.url.split("/")[-1]
        title = response.xpath("//h1/text()").get() or ""
        raw_content = "".join(response.xpath("//article//text()").getall())
        publish_at = response.xpath("//time/@datetime").get()
        last_edit_at = publish_at
        uuid_str = f"article{source_id}{last_edit_at or ''}{raw_content or ''}"
        uuid = generate_uuid(uuid_str)
        item["uuid"] = uuid
        item["source_id"] = source_id
        item["data_version"] = 1
        item["entity_type"] = "article"
        item["url"] = response.url
        item["tags"] = []
        item["platform"] = "示例站"
        item["section"] = response.meta.get("section")
        item["spider_name"] = self.name
        item["crawled_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        item["publish_at"] = publish_at
        item["last_edit_at"] = last_edit_at
        item["author_name"] = response.xpath("//span[@class='author']/text()").get() or ""
        item["nsfw"] = False
        item["aigc"] = False
        item["title"] = title
        item["raw_content"] = raw_content
        item["cover_image"] = response.xpath("//meta[@property='og:image']/@content").get()
        item["likes"] = -1
        yield item
```

替换要点：

- `name`、`allowed_domains`、`section_map`、API 的 url/data。
- `parse_default_list` / `parse_search_list` 中的 `data.get("data", {}).get("list", [])` 及 `detail_url`/id 字段名按实际接口改。
- `parse_detail` 中的 XPath/JSON 路径、时间格式、`platform` 名称按目标站改。
