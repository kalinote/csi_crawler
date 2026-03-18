# NOTICE: 该爬虫完全由AI生成，需要持续观察。

import datetime
import json
import re
from urllib.parse import quote, urlparse

import scrapy
from scrapy.http import Response

from csi_crawlers.items import CSIArticlesItem
from csi_crawlers.spiders.base import BaseSpider
from csi_crawlers.utils import generate_uuid


class IfengNewsSpider(BaseSpider):
    name = "ifeng_news"
    allowed_domains = [
        "www.ifeng.com",
        "news.ifeng.com",
        "finance.ifeng.com",
        "tech.ifeng.com",
        "mil.ifeng.com",
        "sports.ifeng.com",
        "ent.ifeng.com",
        "auto.ifeng.com",
        "house.ifeng.com",
        "fashion.ifeng.com",
        "phtv.ifeng.com",
        "home.ifeng.com",
        "ishare.ifeng.com",
        "d.shankapi.ifeng.com",
    ]

    section_map = {
        "资讯": "https://news.ifeng.com/",
        "财经": "https://finance.ifeng.com/",
        "科技": "https://tech.ifeng.com/",
        "军事": "https://mil.ifeng.com/",
        "体育": "https://sports.ifeng.com/",
        "娱乐": "https://ent.ifeng.com/",
        "汽车": "https://auto.ifeng.com/",
        "房产": "https://house.ifeng.com/",
        "时尚": "https://fashion.ifeng.com/",
        "凤凰卫视": "https://phtv.ifeng.com/",
    }

    custom_settings = {
        "DOWNLOAD_DELAY": 1,
        "USER_AGENT": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    }

    def default_start(self, response):
        for section in self.sections:
            if section == "__default__":
                section = "资讯"
            url = self.section_map.get(section)
            if not url:
                self.logger.error(f"未知采集板块: {section}")
                continue
            yield scrapy.Request(
                url=url,
                callback=self.parse_default_list,
                meta={
                    "current_page": 1,
                    "section": section,
                },
            )

    def search_start(self, response):
        for keyword in self.keywords:
            yield from self._make_search_request(keyword, 1)

    def _make_search_request(self, keyword: str, page: int):
        url = (
            f"https://d.shankapi.ifeng.com/api/getSoFengData/all/{quote(keyword)}/{page}"
            f"/getSoFengDataCallback?callback=getSoFengDataCallback"
        )
        yield scrapy.Request(
            url=url,
            callback=self.parse_search_list,
            meta={"keyword": keyword, "current_page": page},
        )

    def parse_search_list(self, response: Response):
        keyword = response.meta.get("keyword", "")
        current_page = response.meta.get("current_page", 1)

        m = re.match(r"getSoFengDataCallback\((.+)\)\s*;?\s*$", response.text.strip(), re.DOTALL)
        if not m:
            self.logger.warning(f"关键词 [{keyword}] 第{current_page}页 JSONP 解析失败")
            return
        try:
            data = json.loads(m.group(1))
        except Exception as e:
            self.logger.warning(f"关键词 [{keyword}] 第{current_page}页 JSON 解析失败: {e}")
            return

        d = data.get("data") or {}
        items = d.get("items") or []
        total_page = d.get("totalPage") or 0

        for item_data in items:
            raw_url = item_data.get("url") or ""
            if not raw_url:
                continue
            if raw_url.startswith("//"):
                raw_url = "https:" + raw_url
            if "/c/special/" in raw_url:
                continue
            source_id = item_data.get("id") or ""
            title_html = item_data.get("title") or ""
            yield scrapy.Request(
                url=raw_url,
                callback=self.parse_detail,
                meta={
                    "keyword": keyword,
                    "section": keyword,
                    "source_id": source_id,
                    "search_title": re.sub(r"<[^>]+>", "", title_html).strip(),
                },
            )

        has_next = current_page < total_page
        should_continue = (self.page is None or self.page <= 0) and has_next or (
            self.page and self.page > 0 and current_page < self.page and has_next
        )
        if should_continue:
            yield from self._make_search_request(keyword, current_page + 1)

    def parse_default_list(self, response: Response):
        section = response.meta.get("section", "")
        seen_urls = set()
        list_xpath = (
            "//p[contains(@class,'index_news_list_p_')]//a[contains(@href,'/c/')] "
            "| //div[contains(@class,'index_list_title_box_')]//h3/a[contains(@href,'ifeng.com')] "
            "| //a[contains(@href,'/c/') and contains(@href,'ifeng.com')]"
        )
        for node in response.xpath(list_xpath):
            href = node.xpath("@href").get()
            if not href:
                continue
            if "v.ifeng.com" in href or ".shtml" in href or "/c/special/" in href:
                continue
            detail_url = response.urljoin(href)
            if detail_url.startswith("//"):
                detail_url = "https:" + detail_url
            try:
                if "ifeng.com" not in urlparse(detail_url).netloc:
                    continue
            except Exception:
                continue
            if detail_url in seen_urls:
                continue
            seen_urls.add(detail_url)
            yield scrapy.Request(
                url=detail_url,
                callback=self.parse_detail,
                meta={"section": section},
            )

    def parse_detail(self, response: Response):
        section = response.meta.get("section", "")
        url = response.url
        m = re.search(r"/c/(?:s/)?([^/?#]+)", url)
        source_id = (m.group(1) if m else "") or response.meta.get("source_id", "")
        if not source_id or source_id == "special":
            return

        doc_data = self._extract_all_data(response)
        title = (
            response.xpath("//h1[contains(@class,'index_topic_')]/text()").get()
            or (doc_data.get("title") if isinstance(doc_data, dict) else None)
            or response.xpath("//title/text()").get()
            or response.meta.get("search_title", "")
            or ""
        )
        title = (title or "").strip()

        raw_content = response.xpath("//div[contains(@class,'index_text_')]").get()
        content_data = (doc_data.get("contentData") or {}) if isinstance(doc_data, dict) else {}
        content_list = content_data.get("contentList") or []
        if not raw_content and content_list:
            parts = [entry["data"] for entry in content_list if entry.get("type") == "text" and entry.get("data")]
            if parts:
                raw_content = "".join(parts)
        raw_content = raw_content or ""

        date_node = response.xpath("//span[contains(@class,'index_date_')]/text()").get()
        publish_at = date_node.strip() if date_node else None
        if not publish_at and isinstance(doc_data, dict) and doc_data.get("newsTime"):
            publish_at = doc_data["newsTime"]
        if publish_at and len(publish_at) == 10 and re.match(r"\d{4}-\d{2}-\d{2}", publish_at):
            publish_at = publish_at + " 00:00:00"
        if not re.match(r"\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}", publish_at or ""):
            publish_at = None
        last_edit_at = publish_at

        author_name = (
            response.xpath("//span[contains(@class,'index_source_')]//a/text()").get()
            or (doc_data.get("source") if isinstance(doc_data, dict) else None)
            or ""
        )
        author_name = (author_name or "").strip()

        cover_image = response.xpath("//meta[@name='og:img_video']/@content").get()
        if not cover_image:
            cover_image = response.xpath("//meta[@property='og:image']/@content").get()
        if not cover_image and content_list:
            for entry in content_list:
                if entry.get("type") == "video" and entry.get("bigPosterUrl"):
                    cover_image = entry["bigPosterUrl"]
                    break

        uuid = generate_uuid("article" + source_id + str(last_edit_at) + raw_content)

        item = CSIArticlesItem()
        item["uuid"] = uuid
        item["source_id"] = source_id
        item["data_version"] = 1
        item["entity_type"] = "article"
        item["url"] = url
        item["tags"] = []
        item["platform"] = "凤凰网"
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
        item["raw_content"] = raw_content
        item["cover_image"] = cover_image
        item["likes"] = -1

        yield item

    def _extract_all_data(self, response: Response):
        text = response.text
        if not text:
            return None
        m = re.search(r"var\s+allData\s*=\s*(\{[\s\S]*?\});?\s*(?:var\s|$|<)", text)
        if not m:
            return None
        try:
            data = json.loads(m.group(1))
            doc = data.get("docData") if isinstance(data, dict) else None
            return doc if isinstance(doc, dict) else None
        except Exception:
            return None
