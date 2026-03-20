# NOTICE: 该爬虫完全由AI生成，需要持续观察。

import base64
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
        "img.huanqiucdn.cn",
        "rfp.huanqiucdn.cn",
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
                section = "国内"

            if section not in self.section_map:
                self.logger.error(f"未知采集板块: {section}")
                continue

            section_url = self.section_map.get(section)
            if not section_url:
                return
            yield scrapy.Request(
                url=urljoin(section_url, "api/channel_pc"),
                callback=self.parse_channel_config,
                meta={
                    "current_page": 1,
                    "section": section,
                    "section_url": section_url,
                },
            )

    def search_start(self, response):
        raise NotImplementedError("环球网暂不支持关键词搜索采集（crawler_type=keyword）")

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
        item["likes"] = -1

        img_urls = self._extract_all_image_urls(raw_content)
        poster_urls = self._extract_all_video_poster_urls(raw_content)
        media_urls = img_urls + poster_urls
        seen_media: set[str] = set()
        media_urls = [u for u in media_urls if not (u in seen_media or seen_media.add(u))]

        if not media_urls:
            yield item
            return

        pending = {
            "count": len(media_urls),
            "done": 0,
            "base64_map": {},
            "raw_content": raw_content,
            "item": item,
        }
        for media_url in media_urls:
            if isinstance(media_url, str) and media_url.strip().lower().startswith("data:"):
                pending["done"] += 1
                continue

            abs_url = urljoin(response.url, media_url)
            yield scrapy.Request(
                url=abs_url,
                callback=self.parse_image,
                errback=self.handle_image_error,
                meta={
                    "pending": pending,
                    "img_url": media_url,
                    "expect_image_only": media_url in poster_urls,
                },
                headers={"Referer": response.url},
                dont_filter=True,
            )

    def parse_image(self, response):
        pending = response.meta["pending"]
        img_url = response.meta["img_url"]
        expect_image_only = bool(response.meta.get("expect_image_only"))

        content_type = response.headers.get("Content-Type", b"image/jpeg").decode().split(";")[0].strip()
        if not content_type.startswith("image/"):
            if expect_image_only:
                pending["done"] += 1
                if pending["done"] >= pending["count"]:
                    pending["item"]["raw_content"] = self._replace_images_with_base64(
                        pending["raw_content"], pending["base64_map"]
                    )
                    yield pending["item"]
                return
            content_type = "image/jpeg"

        img_b64 = base64.b64encode(response.body).decode()
        pending["base64_map"][img_url] = f"data:{content_type};base64,{img_b64}"

        pending["done"] += 1
        if pending["done"] >= pending["count"]:
            pending["item"]["raw_content"] = self._replace_images_with_base64(
                pending["raw_content"], pending["base64_map"]
            )
            yield pending["item"]

    def handle_image_error(self, failure):
        request = failure.request
        pending = request.meta["pending"]
        self.logger.warning(f"图片下载失败，保留原始链接: {request.url}")

        pending["done"] += 1
        if pending["done"] >= pending["count"]:
            pending["item"]["raw_content"] = self._replace_images_with_base64(
                pending["raw_content"], pending["base64_map"]
            )
            yield pending["item"]

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

    @staticmethod
    def _extract_all_image_urls(html: str) -> list[str]:
        if not html:
            return []
        urls: list[str] = []

        # 1) src
        urls.extend(re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', html, re.IGNORECASE))

        # 2) data-src / data-original / data-lazy 等常见懒加载属性
        urls.extend(
            re.findall(r'<img[^>]+data-src=["\']([^"\']+)["\']', html, re.IGNORECASE)
        )
        urls.extend(
            re.findall(r'<img[^>]+data-original=["\']([^"\']+)["\']', html, re.IGNORECASE)
        )
        urls.extend(
            re.findall(r'<img[^>]+data-lazy=["\']([^"\']+)["\']', html, re.IGNORECASE)
        )

        # 3) srcset：取第一条 URL（逗号分隔，每条可能带宽度/倍率描述）
        for srcset in re.findall(r'<img[^>]+srcset=["\']([^"\']+)["\']', html, re.IGNORECASE):
            first = (srcset or "").split(",")[0].strip()
            if not first:
                continue
            first_url = first.split()[0].strip()
            if first_url:
                urls.append(first_url)

        seen: set[str] = set()
        result: list[str] = []
        for url in urls:
            if url not in seen:
                seen.add(url)
                result.append(url)
        return result

    @staticmethod
    def _extract_all_video_poster_urls(html: str) -> list[str]:
        if not html:
            return []
        posters = re.findall(r"<video[^>]+poster=[\"']([^\"']+)[\"']", html, re.IGNORECASE)
        seen: set[str] = set()
        result: list[str] = []
        for u in posters:
            if not u or u in seen:
                continue
            seen.add(u)
            result.append(u)
        return result

    @staticmethod
    def _replace_images_with_base64(html: str, base64_map: dict) -> str:
        for url, data_uri in base64_map.items():
            # src / data-src / data-original / data-lazy
            html = html.replace(f'src="{url}"', f'src="{data_uri}"')
            html = html.replace(f"src='{url}'", f"src='{data_uri}'")
            html = html.replace(f'data-src="{url}"', f'data-src="{data_uri}"')
            html = html.replace(f"data-src='{url}'", f"data-src='{data_uri}'")
            html = html.replace(f'data-original="{url}"', f'data-original="{data_uri}"')
            html = html.replace(f"data-original='{url}'", f"data-original='{data_uri}'")
            html = html.replace(f'data-lazy="{url}"', f'data-lazy="{data_uri}"')
            html = html.replace(f"data-lazy='{url}'", f"data-lazy='{data_uri}'")
            html = html.replace(f'poster="{url}"', f'poster="{data_uri}"')
            html = html.replace(f"poster='{url}'", f"poster='{data_uri}'")

            # srcset：只替换 srcset 属性值里的 URL token（保持原有描述符不动，避免误替换其它文本）
            def _srcset_repl(m: re.Match) -> str:
                attr = m.group(1)
                quote = m.group(2)
                val = m.group(3)
                escaped_url = re.escape(url)
                # 替换形如：<url><空格/逗号/结束> 的 URL token
                val = re.sub(rf"(?<!\S){escaped_url}(?=(\s|,|$))", data_uri, val)
                return f"{attr}={quote}{val}{quote}"

            html = re.sub(r"(srcset)\s*=\s*([\"'])(.*?)\2", _srcset_repl, html, flags=re.IGNORECASE | re.DOTALL)
        return html

