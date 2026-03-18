# NOTICE: 该爬虫完全由AI生成，需要持续观察。

import datetime
import re
from urllib.parse import urlencode

import scrapy
from scrapy.http import Response

from csi_crawlers.items import CSIArticlesItem
from csi_crawlers.spiders.base import BaseSpider
from csi_crawlers.utils import generate_uuid


class WForumNewsSpider(BaseSpider):
    name = "wforum"
    allowed_domains = ["wforum.com", "www.wforum.com"]

    section_map = {
        "即时新闻": {"path": "breaking"},
        "热点新闻": {"path": "headline"},
        "中国军情": {"path": "china"},
    }

    def default_start(self, response):
        for section in self.sections:
            if section == "__default__":
                section = "即时新闻"
            conf = self.section_map.get(section)
            if not conf:
                self.logger.error(f"未知采集板块: {section}")
                continue
            path = conf["path"]
            url = f"https://www.wforum.com/news/{path}/"
            yield scrapy.Request(
                url=url,
                callback=self.parse_default_list,
                meta={
                    "current_page": 1,
                    "section": section,
                    "path": path,
                    "pid": 0,
                },
            )

    def search_start(self, response):
        for keyword in self.keywords:
            params = {"sname": keyword, "stype": "1"}
            url = "https://www.wforum.com/news/headline/search.php?" + urlencode(
                params,
                encoding="gbk",
                errors="ignore",
            )
            yield scrapy.Request(
                url=url,
                callback=self.parse_search_list,
                meta={
                    "keyword": keyword,
                    "current_page": 1,
                },
            )

    def parse_default_list(self, response: Response):
        section = response.meta.get("section", "")
        for row in response.xpath("//table[@width='630']//tr[td/a[@class='style10']]"):
            title = row.xpath("normalize-space(.//td[1]/a[@class='style10']/text())").get()
            href = row.xpath(".//td[1]/a[@class='style10']/@href").get()
            list_time = row.xpath("normalize-space(.//td[2])").get()
            if not href:
                continue
            detail_url = response.urljoin(href)
            yield scrapy.Request(
                url=detail_url,
                callback=self.parse_detail,
                meta={
                    "section": section,
                    "list_time": list_time,
                },
            )

        current_page = response.meta.get("current_page", 1)
        next_href = response.xpath(
            "//table[@width='630']//a[contains(@href,'dynamic_page=') and contains(.,'下页')]/@href"
        ).get()
        has_next = bool(next_href)
        should_continue = False
        if has_next:
            if self.page is None or self.page <= 0:
                should_continue = True
            else:
                try:
                    current_page_int = int(current_page)
                except (TypeError, ValueError):
                    current_page_int = 1
                if current_page_int < self.page:
                    should_continue = True

        if should_continue and next_href:
            next_url = response.urljoin(next_href)
            yield scrapy.Request(
                url=next_url,
                callback=self.parse_default_list,
                meta={
                    "current_page": current_page + 1,
                    "section": section,
                },
            )

    def parse_search_list(self, response: Response):
        keyword = response.meta.get("keyword", "")
        for row in response.xpath("//table[@width='630']//tr[td/a[@class='style10']]"):
            href = row.xpath(".//td[1]/a[@class='style10']/@href").get()
            list_time = row.xpath("normalize-space(.//td[2])").get()
            if not href:
                continue
            detail_url = response.urljoin(href)
            yield scrapy.Request(
                url=detail_url,
                callback=self.parse_detail,
                meta={
                    "section": "关键词搜索",
                    "list_time": list_time,
                    "keyword": keyword,
                },
            )

        current_page = response.meta.get("current_page", 1)
        next_href = response.xpath(
            "//table[@width='630']//a[contains(@href,'dynamic_page=') and contains(.,'下页')]/@href"
        ).get()
        has_next = bool(next_href)
        should_continue = False
        if has_next:
            if self.page is None or self.page <= 0:
                should_continue = True
            else:
                try:
                    current_page_int = int(current_page)
                except (TypeError, ValueError):
                    current_page_int = 1
                if current_page_int < self.page:
                    should_continue = True

        if should_continue and next_href:
            next_url = response.urljoin(next_href)
            yield scrapy.Request(
                url=next_url,
                callback=self.parse_search_list,
                meta={
                    "keyword": keyword,
                    "current_page": current_page + 1,
                },
            )

    def parse_detail(self, response: Response):
        section = response.meta.get("section")
        list_time = response.meta.get("list_time")

        title = response.xpath(
            "//div[@class='main']//div[@class='zuo']//span[@class='STYLE55']/text()"
        ).get()
        meta_text = response.xpath(
            "normalize-space(//div[@class='main']//div[@class='zuo']//table[1]//tr[2]/td[1]/span[@class='STYLE4'])"
        ).get()

        publish_at = None
        author_name = ""
        if meta_text:
            m = re.search(r"\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}", meta_text)
            if m:
                publish_at = m.group(0)
                rest = meta_text[m.end():]
                rest_parts = rest.split("|")
                if rest_parts:
                    candidate = rest_parts[0].strip()
                    if candidate:
                        author_name = candidate

        if not publish_at and list_time:
            publish_at = list_time.replace("　", " ")

        raw_content_html = response.xpath("//div[@id='cont']").get() or ""
        cover_image = response.xpath(
            "(//div[@id='cont']//img[1]/@src)[1]"
        ).get()

        url = response.url
        source_id = url.rstrip("/").split("/")[-1].split(".")[0]
        last_edit_at = publish_at

        uuid = generate_uuid("article" + source_id + str(last_edit_at) + raw_content_html)

        item = CSIArticlesItem()
        item["uuid"] = uuid
        item["source_id"] = source_id
        item["data_version"] = 1
        item["entity_type"] = "article"
        item["url"] = url
        item["tags"] = []
        item["platform"] = "世界论坛网"
        item["section"] = section
        item["spider_name"] = self.name
        item["crawled_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        item["publish_at"] = publish_at
        item["last_edit_at"] = last_edit_at
        item["author_id"] = author_name
        item["author_name"] = author_name
        item["nsfw"] = False
        item["aigc"] = False
        item["title"] = title
        item["raw_content"] = raw_content_html
        item["cover_image"] = cover_image
        item["likes"] = -1

        yield item

