from datetime import datetime
import scrapy
from scrapy.http import Response
from urllib.parse import urlparse
from csi_crawlers.items import CSIArticlesItem
from csi_crawlers.spiders.base import BaseSpider
from csi_crawlers.utils import find_datetime_from_str, generate_uuid, safe_int

class BearblogSpider(BaseSpider):
    name = "bearblog"
    allowed_domains = ["bearblog.dev"]
    start_url = "https://bearblog.dev"

    def default_start(self, response: Response):
        url = "https://bearblog.dev/discover/?page=0"
        yield scrapy.Request(url, callback=self.parse_post_list, meta={"current_page": 0})

    def parse_post_list(self, response: Response):
        current_page = response.meta.get("current_page", 0)
        is_search = response.meta.get("is_search", False)
        
        if is_search:
            self.logger.info("正在解析搜索结果")
        else:
            self.logger.info(f"正在爬取列表页第 {current_page} 页")
        
        urls = response.xpath('//ul[@class="discover-posts"]/li/div/a/@href').getall()
        for url in urls:
            yield response.follow(url, callback=self.parse_innerpage)

        if is_search:
            return

        # 翻页逻辑
        # 判断是否存在文本包含 Next 的 a 标签
        has_next = response.xpath('//a[contains(text(), "Next")]').get()
        
        if has_next:
            should_continue = False
            if (self.page is None or self.page <= 0) or (current_page + 1 < self.page):
                should_continue = True
            
            if should_continue:
                next_page = current_page + 1
                url = f"https://bearblog.dev/discover/?page={next_page}"
                self.logger.info(f"5秒后将爬取列表页第 {next_page} 页")
                yield scrapy.Request(
                    url, 
                    callback=self.parse_post_list, 
                    meta={'current_page': next_page, 'download_delay': 5},
                    dont_filter=True
                )
        else:
            self.logger.info(f"已到达最后一页，当前第 {current_page} 页")

    def search_start(self, response: Response):
        self.logger.info(f"开始关键词搜索，关键词数量: {len(self.keywords)}")
        # 获取搜索页以提取 CSRF token
        yield scrapy.Request(
            url="https://bearblog.dev/discover/search/",
            callback=self.parse_search_token,
            dont_filter=True
        )

    def parse_search_token(self, response: Response):
        token = response.xpath('//input[@name="csrfmiddlewaretoken"]/@value').get()
        if not token:
            self.logger.error("无法获取 csrfmiddlewaretoken")
            return

        url = "https://bearblog.dev/discover/search/"
        for keyword in self.keywords:
            self.logger.info(f"正在搜索关键词: {keyword}")
            yield scrapy.FormRequest(
                url=url,
                formdata={
                    'csrfmiddlewaretoken': token,
                    'query': keyword
                },
                callback=self.parse_post_list,
                meta={'is_search': True},
                dont_filter=True
            )

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
        item["likes"] = safe_int(response.xpath('//small[@class="upvote-count"]/text()').get()) or -1

        yield item
