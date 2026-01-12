from datetime import datetime
import scrapy
from scrapy.http import Response
from urllib.parse import urlparse
from csi_crawlers.items import CSIArticlesItem
from csi_crawlers.spiders.base import BaseSpider
from csi_crawlers.utils import find_datetime_from_str, generate_uuid



class BearblogSpider(BaseSpider):
    name = "bearblog"
    allowed_domains = ["bearblog.dev"]
    start_url = "https://bearblog.dev"

    def default_start(self, response: Response):
        url = "https://bearblog.dev/discover/?page=0"
        yield scrapy.Request(url, callback=self.parse_post_list)

    def parse_post_list(self, response: Response):
        urls = response.xpath('//ul[@class="discover-posts"]/li/div/a/@href').getall()
        for url in urls:
            yield response.follow(url, callback=self.parse_innerpage)

    def parse_search_list(self, response: Response):
        pass

    def parse_innerpage(self, response: Response):
        # 先跳过不是 bearblog.dev 站点的
        domain = urlparse(response.url).netloc
        if not domain.endswith('bearblog.dev'):
            self.logger.info(f'跳过非 bearblog.dev 站点: {response.url}')
            return

        item = CSIArticlesItem()

        source_id = response.url.strip("/").split("/")[-1]
        last_edit_at = find_datetime_from_str(response.xpath("//time/@datetime").get())
        raw_content = response.xpath('//main').get() or ""
        

        # 点赞 //small[@class="upvote-count"]/text()

        item["uuid"] = generate_uuid(source_id + str(last_edit_at) + raw_content)
        item["source_id"] = source_id
        item["data_version"] = 1
        item["entity_type"] = "article"
        item["url"] = response.url
        item["platform"] = self.name
        item["section"] = "discover"
        item["spider_name"] = "csi_crawlers-" + self.name
        item["crawled_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        item["publish_at"] = last_edit_at
        item["last_edit_at"] = last_edit_at
        item["author_id"] = (domain.split(".")[0] or "").strip() or None
        item["author_name"] = (response.xpath('//a[@class="title"]/h1/text()').get() or "").strip() or None
        item["nsfw"] = False
        item["aigc"] = False
        item["title"] = (response.xpath('//main/h1/text()').get() or "").strip() or None
        item["raw_content"] = response.xpath('//main').get() or ""

        yield item