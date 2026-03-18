# NOTICE: 该爬虫完全由AI生成，需要持续观察。

import datetime
import re
from typing import Optional
from urllib.parse import quote, urljoin

import scrapy
from scrapy.http import Response

from csi_crawlers.items import CSIArticlesItem
from csi_crawlers.spiders.base import BaseSpider
from csi_crawlers.utils import generate_uuid


class HuanqiuNewsSpider(BaseSpider):
    name = "huanqiu_news"
    allowed_domains = [
        "huanqiu.com",
        "www.huanqiu.com",
        "world.huanqiu.com",
        "china.huanqiu.com",
        "mil.huanqiu.com",
        "taiwan.huanqiu.com",
        "opinion.huanqiu.com",
        "finance.huanqiu.com",
        "tech.huanqiu.com",
        "auto.huanqiu.com",
        "capital.huanqiu.com",
        "go.huanqiu.com",
        "health.huanqiu.com",
        "energy.huanqiu.com",
        "house.huanqiu.com",
        "city.huanqiu.com",
        "yrd.huanqiu.com",
    ]

    section_map = {
        "国际": "https://world.huanqiu.com/",
        "国内": "https://china.huanqiu.com/",
        "军事": "https://mil.huanqiu.com/",
        "台海": "https://taiwan.huanqiu.com/",
        "评论": "https://opinion.huanqiu.com/",
        "财经": "https://finance.huanqiu.com/",
        "科技": "https://tech.huanqiu.com/",
        "汽车": "https://auto.huanqiu.com/",
        "产业": "https://capital.huanqiu.com/",
        "文旅": "https://go.huanqiu.com/",
        "健康": "https://health.huanqiu.com/",
        "能源": "https://energy.huanqiu.com/",
        "房产": "https://house.huanqiu.com/",
        "城市": "https://city.huanqiu.com/",
        "长三角": "https://yrd.huanqiu.com/",
    }

    api_list_limit = 24

    custom_settings = {
        "DOWNLOAD_DELAY": 1,
        "USER_AGENT": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    }

    @staticmethod
    def _normalize_sections(sections) -> list[str]:
        if sections is None:
            return ["__default__"]
        if isinstance(sections, str):
            parts = [s.strip() for s in sections.split(",") if s.strip()]
            return parts or ["__default__"]
        if isinstance(sections, (list, tuple)):
            return list(sections) if sections else ["__default__"]
        return ["__default__"]

    def default_start(self, response):
        for section in self._normalize_sections(self.sections):
            if section == "__default__":
                for default_section in self.section_map.keys():
                    yield from self._make_section_request(default_section, 1)
                continue

            if section not in self.section_map:
                self.logger.error(f"未知采集板块: {section}")
                continue

            yield from self._make_section_request(section, 1)

    def search_start(self, response):
        raise NotImplementedError("环球网暂不支持关键词搜索采集（crawler_type=keyword）")

    def _make_section_request(self, section: str, page: int):
        section_url = self.section_map.get(section)
        if not section_url:
            return
        yield scrapy.Request(
            url=urljoin(section_url, "api/channel_pc"),
            callback=self.parse_channel_config,
            meta={
                "current_page": page,
                "section": section,
                "section_url": section_url,
            },
        )

    def parse_channel_config(self, response: Response):
        section = response.meta.get("section", "")
        section_url = response.meta.get("section_url", "")
        current_page = response.meta.get("current_page", 1)

        try:
            data = response.json()
        except Exception as e:
            self.logger.error(f"频道配置解析失败: {e}")
            return

        nodes = self._extract_nodes_from_channel_config(data)
        if not nodes:
            self.logger.warning(f"未从频道配置提取到 node: {response.url}")
            return

        offset = (current_page - 1) * self.api_list_limit
        yield scrapy.Request(
            url=self._build_api_list_url(section_url, nodes, offset=offset, limit=self.api_list_limit),
            callback=self.parse_api_list,
            meta={
                "current_page": current_page,
                "section": section,
                "section_url": section_url,
                "nodes": nodes,
                "offset": offset,
            },
        )

    def parse_api_list(self, response: Response):
        section = response.meta.get("section", "")
        section_url = response.meta.get("section_url", "")
        current_page = response.meta.get("current_page", 1)
        nodes = response.meta.get("nodes") or []
        offset = response.meta.get("offset", 0)

        try:
            data = response.json()
        except Exception as e:
            self.logger.error(f"列表接口 JSON 解析失败: {e}")
            return

        items = data.get("list") if isinstance(data, dict) else None
        if not isinstance(items, list):
            self.logger.warning(f"列表接口返回结构异常: {response.url}")
            return

        seen: set[str] = set()
        for it in items:
            if not isinstance(it, dict):
                continue
            aid = (it.get("aid") or "").strip()
            title = (it.get("title") or "").strip()
            addltype = (it.get("addltype") or "").strip()
            host = (it.get("host") or "").strip()
            cover = (it.get("cover") or "").strip()
            xtime = (it.get("xtime") or it.get("ctime") or "").strip()

            if not aid:
                continue
            if addltype and addltype.lower() not in ["normal", "news", "article"]:
                continue
            if not host:
                host = self._host_from_section_url(section_url)

            detail_url = urljoin(f"https://{host}", f"/article/{aid}")
            if not detail_url or detail_url in seen:
                continue
            seen.add(detail_url)

            yield scrapy.Request(
                url=detail_url,
                callback=self.parse_detail,
                meta={
                    "section": section,
                    "source_id": aid,
                    "list_title": title,
                    "cover_image": cover,
                    "publish_ts": xtime,
                },
            )

        has_next = len(items) >= self.api_list_limit
        should_continue = (self.page is None or self.page <= 0) and has_next or (
            self.page and self.page > 0 and current_page < self.page and has_next
        )
        if should_continue:
            next_page = current_page + 1
            next_offset = offset + self.api_list_limit
            yield scrapy.Request(
                url=self._build_api_list_url(section_url, nodes, offset=next_offset, limit=self.api_list_limit),
                callback=self.parse_api_list,
                meta={
                    "current_page": next_page,
                    "section": section,
                    "section_url": section_url,
                    "nodes": nodes,
                    "offset": next_offset,
                },
            )

    def parse_detail(self, response: Response):
        section = response.meta.get("section", "")
        url = response.url

        source_id = (
            (response.xpath("//textarea[contains(@class,'article-aid')]/text()").get() or "").strip()
            or (response.meta.get("source_id") or "").strip()
            or self._source_id_from_url(url)
        )
        if not source_id:
            return

        title = (response.xpath("//textarea[contains(@class,'article-title')]/text()").get() or "").strip()
        if not title:
            title = (response.meta.get("list_title") or "").strip()

        raw_content = self._extract_article_content_from_html(response.text)

        publish_ts = (response.xpath("//textarea[contains(@class,'article-time')]/text()").get() or "").strip()
        if not publish_ts:
            publish_ts = (response.meta.get("publish_ts") or "").strip()
        publish_at = self._format_ts_ms(publish_ts)

        edit_ts = (response.xpath("//textarea[contains(@class,'article-ext-xtime')]/text()").get() or "").strip()
        last_edit_at = self._format_ts_ms(edit_ts) or publish_at

        author_name = (response.xpath("//textarea[contains(@class,'article-author')]/text()").get() or "").strip()
        if not author_name:
            editor_name = (response.xpath("//textarea[contains(@class,'article-editor-name')]/text()").get() or "").strip()
            author_name = editor_name
        if not author_name:
            source_name_html = response.xpath("//textarea[contains(@class,'article-source-name')]/text()").get() or ""
            author_name = self._strip_html(source_name_html).strip()

        author_name = self._normalize_author_name(author_name)
        if not author_name:
            author_name = "未知"

        cover_image = (response.meta.get("cover_image") or "").strip()
        if not cover_image:
            cover_image = self._extract_first_image(raw_content)
        cover_image = response.urljoin(cover_image) if cover_image else cover_image

        uuid = generate_uuid("article" + source_id + str(last_edit_at) + raw_content)

        item = CSIArticlesItem()
        item["uuid"] = uuid
        item["source_id"] = source_id
        item["data_version"] = 1
        item["entity_type"] = "article"
        item["url"] = url
        item["tags"] = []
        item["platform"] = "环球网"
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

    @staticmethod
    def _strip_html(html: str) -> str:
        if not html:
            return ""
        return re.sub(r"<[^>]+>", "", html)

    @staticmethod
    def _normalize_author_name(author: str) -> str:
        if not author:
            return ""
        s = author.strip()
        s = re.sub(r"^\s*作者[:：]\s*", "", s)
        s = re.sub(r"^\s*责编[:：]\s*", "", s)
        parts = [p.strip() for p in re.split(r"[\s，,]+", s) if p and p.strip()]
        return ",".join(parts)

    @staticmethod
    def _extract_article_content_from_html(html: str) -> str:
        if not html:
            return ""
        m = re.search(
            r'<textarea[^>]*class=["\'][^"\']*article-content[^"\']*["\'][^>]*>([\s\S]*?)</textarea>',
            html,
            re.IGNORECASE,
        )
        return (m.group(1) if m else "").strip()

    @staticmethod
    def _source_id_from_url(url: str) -> str:
        m = re.search(r"/article/([^/?#]+)", url or "")
        return m.group(1) if m else ""

    @staticmethod
    def _extract_first_image(html: str) -> str:
        if not html:
            return ""
        m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', html, re.IGNORECASE)
        return m.group(1).strip() if m else ""

    @staticmethod
    def _format_ts_ms(ts_ms: str) -> Optional[str]:
        if not ts_ms:
            return None
        try:
            ms = int(re.sub(r"[^\d]", "", ts_ms))
        except Exception:
            return None
        if ms <= 0:
            return None
        try:
            dt = datetime.datetime.fromtimestamp(ms / 1000.0)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return None

    @staticmethod
    def _host_from_section_url(section_url: str) -> str:
        if not section_url:
            return ""
        m = re.match(r"^https?://([^/]+)/?", section_url.strip())
        return m.group(1) if m else ""

    @staticmethod
    def _extract_nodes_from_channel_config(data: dict) -> list[str]:
        if not isinstance(data, dict):
            return []
        children = data.get("children")
        if not isinstance(children, dict):
            return []

        nodes: list[str] = []

        def walk(obj):
            if not isinstance(obj, dict):
                return
            sub = obj.get("children")
            if isinstance(sub, dict) and sub:
                for v in sub.values():
                    walk(v)
                return

            node_val = obj.get("node")
            if isinstance(node_val, str) and node_val.startswith("/"):
                nodes.append(node_val)

        for v in children.values():
            walk(v)

        seen = set()
        result: list[str] = []
        for n in nodes:
            if n not in seen:
                seen.add(n)
                result.append(n)
        return result

    @staticmethod
    def _build_api_list_url(section_url: str, nodes: list[str], offset: int, limit: int) -> str:
        host = HuanqiuNewsSpider._host_from_section_url(section_url)
        if not host:
            return ""
        node_param = ",".join(
            [
                quote(f"\"{n}\"", safe="/")
                for n in nodes
                if isinstance(n, str) and n and n.startswith("/")
            ]
        )
        return f"https://{host}/api/list?node={node_param}&offset={offset}&limit={limit}"

