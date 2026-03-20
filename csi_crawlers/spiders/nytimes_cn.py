import datetime
import re
from typing import Optional

import scrapy
from scrapy.http import Response

from csi_crawlers.items import CSIArticlesItem
from csi_crawlers.spiders.base import BaseSpider
from csi_crawlers.utils import generate_uuid

ARTICLE_PATH_RE = re.compile(r"^/([a-z0-9-]+)/(\d{8})/([^/?#]+)/?$", re.I)


class NytimesCnSpider(BaseSpider):
    name = "nytimes_cn_news"
    allowed_domains = ["cn.nytimes.com"]

    section_map = {
        "首页": "https://cn.nytimes.com/",
        "国际": "https://cn.nytimes.com/world/",
        "亚太": "https://cn.nytimes.com/asia-pacific/",
        "南亚": "https://cn.nytimes.com/south-asia/",
        "美国": "https://cn.nytimes.com/usa/",
        "美洲": "https://cn.nytimes.com/americas/",
        "欧洲": "https://cn.nytimes.com/europe/",
        "中东": "https://cn.nytimes.com/mideast/",
        "非洲": "https://cn.nytimes.com/africa/",
        "中国": "https://cn.nytimes.com/china/",
        "时政": "https://cn.nytimes.com/policy/",
        "经济": "https://cn.nytimes.com/china-ec/",
        "社会": "https://cn.nytimes.com/society/",
        "中外关系": "https://cn.nytimes.com/foreign-relations/",
        "港澳台": "https://cn.nytimes.com/hk-taiwan/",
        "商业与经济": "https://cn.nytimes.com/business/",
        "全球经济": "https://cn.nytimes.com/global-ec/",
        "中国经济": "https://cn.nytimes.com/china-ec/",
        "交易录": "https://cn.nytimes.com/dealbook/",
        "镜头": "https://cn.nytimes.com/lens/",
        "科技": "https://cn.nytimes.com/technology/",
        "科技公司": "https://cn.nytimes.com/bits/",
        "科技与你": "https://cn.nytimes.com/personal-tech/",
        "科学": "https://cn.nytimes.com/science/",
        "健康": "https://cn.nytimes.com/health/",
        "教育": "https://cn.nytimes.com/education/",
        "文化": "https://cn.nytimes.com/culture/",
        "阅读": "https://cn.nytimes.com/books/",
        "艺术": "https://cn.nytimes.com/art/",
        "电影与电视": "https://cn.nytimes.com/film-tv/",
        "体育": "https://cn.nytimes.com/sports/",
        "风尚": "https://cn.nytimes.com/style/",
        "时尚": "https://cn.nytimes.com/fashion/",
        "美食与美酒": "https://cn.nytimes.com/food-wine/",
        "生活方式": "https://cn.nytimes.com/lifestyle/",
        "旅游": "https://cn.nytimes.com/travel/",
        "房地产": "https://cn.nytimes.com/real-estate/",
        "观点与评论": "https://cn.nytimes.com/opinion/",
        "专栏作者": "https://cn.nytimes.com/op-column/",
        "观点": "https://cn.nytimes.com/op-ed/",
        "漫画": "https://cn.nytimes.com/cartoon/",
    }

    custom_settings = {
        "DOWNLOAD_DELAY": 1,
        "USER_AGENT": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    }

    def default_start(self, response):
        """根据板块配置发起各板块列表页请求。"""
        if "__default__" in self.sections:
            self.sections.remove("__default__")
            if "中国" not in self.sections:
                self.sections.append("中国")
        seen_base: set[str] = set()
        for section in self.sections:
            if section == "__default__":
                continue
            base_url = self.section_map.get(section)
            if not base_url:
                self.logger.error(f"未知采集板块: {section}")
                continue
            if base_url in seen_base:
                continue
            seen_base.add(base_url)
            yield scrapy.Request(
                url=base_url,
                callback=self.parse_list,
                meta={"section": section, "current_page": 1},
            )

    def search_start(self, response):
        raise NotImplementedError(
            "纽约时报中文网暂不支持关键词搜索采集（crawler_type=keyword）"
        )

    def parse_list(self, response: Response):
        section = response.meta.get("section", "")
        current_page = response.meta.get("current_page", 1)

        seen: set[str] = set()
        for href in response.xpath(
            "//h3[contains(@class,'sectionLeadHeader') or contains(@class,'regularSummaryHeadline')]/a/@href"
        ).getall():
            path = (href or "").split("?", 1)[0].split("#", 1)[0]
            if not path or not ARTICLE_PATH_RE.match(path):
                continue
            detail_url = response.urljoin(href)
            if detail_url in seen:
                continue
            seen.add(detail_url)
            yield scrapy.Request(
                url=detail_url,
                callback=self.parse_detail,
                meta={"section": section},
            )

        next_href = response.xpath(
            "//div[contains(@class,'pagination')]//li[contains(@class,'next')]/a/@href"
        ).get()
        has_next = bool(next_href and next_href.strip())
        should_continue = (self.page is None or self.page <= 0) and has_next or (
            self.page and self.page > 0 and current_page < self.page and has_next
        )
        if should_continue and next_href:
            yield scrapy.Request(
                url=response.urljoin(next_href),
                callback=self.parse_list,
                meta={"section": section, "current_page": current_page + 1},
            )

    def parse_detail(self, response: Response):
        section = response.meta.get("section", "")
        url = response.url

        if "/dual/" in url or "javascript:" in url.lower():
            return

        source_id = (
            response.xpath("//meta[@name='uuid']/@content").get()
            or response.xpath("//meta[@id='uuid']/@content").get()
            or ""
        ).strip()
        if not source_id:
            source_id = self._source_id_from_url(url)
        if not source_id:
            self.logger.warning(f"无法解析 source_id，跳过: {url}")
            return

        title = (
            response.xpath(
                "//article[contains(@class,'article-content')]//div[contains(@class,'article-header')]//h1/text()"
            ).get()
            or ""
        ).strip()
        if not title:
            title = self._clean_headline(
                (
                    response.xpath("//meta[@name='headline']/@content").get()
                    or response.xpath("//meta[@id='headline']/@content").get()
                    or ""
                ).strip()
            )
        if not title:
            title = (response.xpath("//meta[@property='og:title']/@content").get() or "").strip()

        publish_raw = (
            response.xpath("//meta[@property='article:published_time']/@content").get() or ""
        ).strip()
        if not publish_raw:
            publish_raw = (
                response.xpath("//meta[@name='date']/@content").get()
                or response.xpath("//meta[@id='date']/@content").get()
                or ""
            ).strip()
        publish_at = self._normalize_iso_datetime(publish_raw)

        edit_raw = (
            response.xpath("//meta[@property='article:modified_time']/@content").get() or ""
        ).strip()
        last_edit_at = self._normalize_iso_datetime(edit_raw) or publish_at

        author_name = (
            response.xpath("//meta[@name='byline']/@content").get()
            or response.xpath("//meta[@id='byline']/@content").get()
            or ""
        ).strip()
        if not author_name:
            author_name = (
                response.xpath(
                    "//article[contains(@class,'article-content')]//div[contains(@class,'byline')]//address/text()"
                ).get()
                or ""
            ).strip()

        cover_image = (
            response.xpath("//meta[@property='og:image']/@content").get() or ""
        ).strip()
        if not cover_image:
            cover_image = (
                response.xpath(
                    "//article[contains(@class,'article-content')]//figure[contains(@class,'article-span-photo')]//img/@src"
                ).get()
                or ""
            ).strip()

        paragraphs = response.xpath(
            "//article[contains(@class,'article-content')]//section[contains(@class,'article-body')]//div[contains(@class,'article-paragraph')]"
        ).getall()
        raw_content = "".join(paragraphs).strip()
        if not raw_content:
            raw_content = (
                response.xpath(
                    "//article[contains(@class,'article-content')]//section[contains(@class,'article-body')]"
                ).get()
                or ""
            ).strip()

        if not title or not raw_content:
            self.logger.warning(f"详情页缺少标题或正文，跳过: {url}")
            return

        uuid = generate_uuid("article" + source_id + str(last_edit_at) + raw_content)

        item = CSIArticlesItem()
        item["uuid"] = uuid
        item["source_id"] = source_id
        item["data_version"] = 1
        item["entity_type"] = "article"
        item["url"] = url
        item["tags"] = []
        item["platform"] = "纽约时报中文网"
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
        item["likes"] = -1
        if cover_image:
            item["cover_image"] = cover_image

        yield item

    @staticmethod
    def _source_id_from_url(url: str) -> str:
        if not url:
            return ""
        m = re.search(r"/(\d{8})/([^/?#]+)/?", url)
        if not m:
            return ""
        return f"{m.group(1)}_{m.group(2)}"

    @staticmethod
    def _clean_headline(s: str) -> str:
        if not s:
            return ""
        s = s.strip()
        s = re.sub(r"\s*[-–—]\s*纽约时报中文网\s*$", "", s)
        return s.strip()

    @staticmethod
    def _normalize_iso_datetime(s: str) -> Optional[str]:
        if not s:
            return None
        s = s.strip()
        m = re.match(r"(\d{4}-\d{2}-\d{2})[T\s](\d{2}:\d{2}:\d{2})", s)
        if m:
            return f"{m.group(1)} {m.group(2)}"
        m = re.match(r"(\d{4}-\d{2}-\d{2})[T\s](\d{2}:\d{2})", s)
        if m:
            return f"{m.group(1)} {m.group(2)}:00"
        m = re.match(r"(\d{4}-\d{2}-\d{2})", s)
        if m:
            return f"{m.group(1)} 00:00:00"
        return None
