from datetime import datetime
import scrapy
from scrapy.http import Response
from csi_crawlers.items import CSIArticlesItem
from csi_crawlers.spiders.base import BaseSpider
from csi_crawlers.utils import find_datetime_from_str, generate_uuid, safe_int

class AnwangxiaSpider(BaseSpider):
    name = "anwangxia"
    allowed_domains = ["anwangxia.com"]

    section_map = {
        "独家报道": "exclusive",
    }

    def default_start(self, response):
        for section in self.sections:
            if section == "__default__":
                section = "独家报道"

            section_url = self.section_map.get(section)
            if not section_url:
                self.logger.error(f"未知采集板块: {section}")
                continue
            url = f"https://www.anwangxia.com/category/{section_url}/page/1"
            yield scrapy.Request(url, callback=self.parse_post_list, meta={"current_page": 1, "section": section})
    
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
        section = response.meta.get("section", "")
        current_page = response.meta.get("current_page", 1)
        keyword = response.meta.get("keyword")
        if keyword:
            self.logger.info(f"正在解析关键词「{keyword}」搜索结果第 {current_page} 页")
        else:
            self.logger.info(f"正在爬取板块「{section}」列表第 {current_page} 页")

        urls = response.xpath("//h2/a/@href").getall()
        for url in urls:
            if not url or not url.strip():
                continue
            yield response.follow(url, callback=self.parse_innerpage, meta={"section": section})

        has_next = response.xpath('//a[@class="next"]').get()
        if not has_next:
            self.logger.info(f"已到达最后一页，当前第 {current_page} 页")
            return

        if (self.page is not None and self.page > 0) and current_page >= self.page:
            return
        next_page = current_page + 1
        if keyword:
            next_url = f"https://www.anwangxia.com/page/{next_page}?s={keyword}"
        else:
            section_url = self.section_map.get(section, "exclusive")
            next_url = f"https://www.anwangxia.com/category/{section_url}/page/{next_page}"
        meta = {"current_page": next_page, "section": section}
        if keyword:
            meta["keyword"] = keyword
        yield scrapy.Request(next_url, callback=self.parse_post_list, meta=meta)

    def parse_innerpage(self, response: Response):
        id_attr = response.xpath("//article/@id").get()
        if not id_attr:
            return
        source_id = id_attr.replace("post-", "").strip()
        last_edit_at = find_datetime_from_str(response.xpath('//time[contains(@class, "published")]/@datetime').get())
        raw_content = response.xpath('//div[contains(@class, "entry-content")]').get() or ""

        item = CSIArticlesItem()
        item["uuid"] = generate_uuid("article" + source_id + str(last_edit_at) + raw_content)
        item["source_id"] = source_id
        item["data_version"] = 1
        item["entity_type"] = "article"
        item["url"] = response.url
        item["tags"] = response.xpath('//div[@class="entry-tag"]/a/text()').getall() or []
        item["platform"] = "暗网下"
        item["section"] = response.meta.get("section")
        item["spider_name"] = self.name
        item["crawled_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        item["publish_at"] = last_edit_at
        item["last_edit_at"] = last_edit_at
        author_href = response.xpath('//a[contains(@class, "nickname")]/@href').get()
        item["author_id"] = author_href.strip("/").split("/")[-1].strip() if author_href else None
        item["author_name"] = response.xpath('//a[contains(@class, "nickname")]/text()').get()
        item["nsfw"] = False
        item["aigc"] = False
        item["title"] = response.xpath('//h1[@class="entry-title"]/text()').get()
        item["raw_content"] = raw_content
        item["cover_image"] = response.xpath('//figure/a/img/@src').get()
        likes_text = response.xpath('//span[@class="entry-action-num"]/text()').get()
        item["likes"] = safe_int((likes_text or "").replace("(", "").replace(")", "")) or -1

        yield item
