from datetime import datetime
import scrapy
from scrapy.http import Response
from urllib.parse import urlparse
from csi_crawlers.items import CSIArticlesItem
from csi_crawlers.spiders.base import BaseSpider
from csi_crawlers.utils import find_datetime_from_str, generate_uuid, safe_int

class AnwangxiaSpider(BaseSpider):
    name = "anwangxia"
    allowed_domains = ["anwangxia.com"]

    def default_start(self, response):
        url = "https://www.anwangxia.com/category/exclusive/page/1"
        yield scrapy.Request(
            url,
            callback=self.parse_post_list,
            meta={
                "current_page": 1,
                "section": "独家报道"
            }
        )
    
    def search_start(self, response):
        for keyword in self.keywords:
            self.logger.info(f"开始搜索关键词: {keyword}")
            url = f"https://www.anwangxia.com/?s={keyword}"
            yield scrapy.Request(
                url,
                callback=self.parse_post_list,
                meta={
                    "current_page": 1,
                    "section": "关键词搜索",
                    "keyword": keyword
                }
            )

    def parse_post_list(self, response: Response):
        urls = response.xpath("//h2/a/@href").getall()

        for url in urls:
            # TODO: 检查此处逻辑
            yield scrapy.Request(url, callback=self.parse_innerpage, meta={"section": response.meta.get("section")})

        current_page = response.meta.get("current_page", 1)
        has_next = response.xpath('//a[@class="next"]').get()
        
        if has_next:
            should_continue = False
            if (self.page is None or self.page <= 0) or (current_page < self.page):
                should_continue = True
            
            if should_continue:
                next_page = current_page + 1
                keyword = response.meta.get("keyword")
                
                if keyword:
                    url = f"https://www.anwangxia.com/page/{next_page}?s={keyword}"
                    yield scrapy.Request(url, callback=self.parse_post_list, meta={"current_page": next_page, "section": response.meta.get("section"), "keyword": keyword})
                else:
                    url = f"https://www.anwangxia.com/category/exclusive/page/{next_page}"
                    yield scrapy.Request(url, callback=self.parse_post_list, meta={"current_page": next_page, "section": response.meta.get("section")})
        else:
            self.logger.info(f"已到达最后一页，当前第 {current_page} 页")

    def parse_innerpage(self, response: Response):
        item = CSIArticlesItem()

        source_id = response.xpath("//article/@id").get().replace("post-", "").strip()
        last_edit_at = find_datetime_from_str(response.xpath('//time[contains(@class, "published")]/@datetime').get())
        raw_content = response.xpath('//div[contains(@class, "entry-content")]').get() or ""

        item["uuid"] = generate_uuid("article" + source_id + str(last_edit_at) + raw_content)
        item["source_id"] = source_id
        item["data_version"] = 1
        item["entity_type"] = "article"
        item["url"] = response.url
        item["tags"] = response.xpath('//div[@class="entry-tag"]/a/text()').getall()
        item["platform"] = "暗网下"
        item["section"] = response.meta.get("section")
        item["spider_name"] = self.name
        item["crawled_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        item["publish_at"] = last_edit_at
        item["last_edit_at"] = last_edit_at
        item["author_id"] = response.xpath('//a[contains(@class, "nickname")]/@href').get().strip("/").split("/")[-1].strip()
        item["author_name"] = response.xpath('//a[contains(@class, "nickname")]/text()').get()
        item["nsfw"] = False
        item["aigc"] = False
        item["title"] = response.xpath('//h1[@class="entry-title"]/text()').get()
        item["raw_content"] = raw_content
        item["cover_image"] = response.xpath('//figure/a/img/@src').get()
        item["likes"] = safe_int(response.xpath('//span[@class="entry-action-num"]/text()').get().replace("(", "").replace(")", ""))

        yield item
