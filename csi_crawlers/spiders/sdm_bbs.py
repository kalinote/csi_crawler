# NOTICE: 该爬虫完全由AI生成，需要持续观察。

import datetime
import re

import scrapy
from scrapy.http import Response

from csi_crawlers.items import CSIForumItem
from csi_crawlers.spiders.base import BaseSpider
from csi_crawlers.utils import generate_uuid, safe_int, find_datetime_from_str


class ThreeDMForumSpider(BaseSpider):
    name = "sdm_bbs"
    allowed_domains = ["bbs.3dmgame.com"]

    section_config = {
        "PC新游发布与体验区": {
            "start_url": "https://bbs.3dmgame.com/game0day",
            "fid": None,
        },
        "PC独立游戏资源区": {
            "start_url": "https://bbs.3dmgame.com/forum-771-1.html",
            "fid": 771,
        },
        "PC游戏综合资源区": {
            "start_url": "https://bbs.3dmgame.com/forum-192-1.html",
            "fid": 192,
        },
        "游戏杂谈区": {
            "start_url": "https://bbs.3dmgame.com/forum-406-1.html",
            "fid": 406,
        },
        "游戏软硬件交流区": {
            "start_url": "https://bbs.3dmgame.com/forum-220-1.html",
            "fid": 220,
        },
    }

    def default_start(self, response):
        """根据板块配置发起各板块列表页请求。"""
        if "__default__" in self.sections:
            self.sections.remove("__default__")
            if "游戏杂谈区" not in self.sections:
                self.sections.append("游戏杂谈区")
            if "PC新游发布与体验区" not in self.sections:
                self.sections.append("PC新游发布与体验区")
        for section in self.sections:
            if section == "__default__":
                continue
            conf = self.section_config.get(section)
            if not conf:
                self.logger.error(f"未知采集板块: {section}")
                continue
            url = conf["start_url"]
            fid = conf.get("fid")
            yield scrapy.Request(
                url=url,
                callback=self.parse_list,
                meta={
                    "section": section,
                    "fid": fid,
                    "current_page": 1,
                },
            )

    def search_start(self, response):
        raise ValueError("3DM 论坛未对游客开放关键词搜索，不支持 keyword 模式采集")

    def parse_list(self, response: Response):
        """解析列表页：提取帖子链接并发详情请求，若有下一页则继续翻页。"""
        section = response.meta.get("section", "")
        fid = response.meta.get("fid")
        current_page = response.meta.get("current_page", 1)

        rows = response.xpath(
            "//div[@id='threadlist']//tbody[starts-with(@id,'normalthread_') or starts-with(@id,'stickthread_')]"
        )
        for row in rows:
            thread_link = row.xpath(
                ".//th[contains(@class,'common') or contains(@class,'new')]//a[contains(@href,'thread-')][1]/@href"
            ).get()
            if not thread_link:
                continue
            url = response.urljoin(thread_link)
            tid = self._extract_tid(thread_link)
            status_flags = self._extract_status_flags_from_row(row)

            reply_text = row.xpath(
                "normalize-space(.//td[contains(@class,'num')]/a[1]/text())"
            ).get()
            view_text = row.xpath(
                "normalize-space(.//td[contains(@class,'num')]/em[1]/text())"
            ).get()
            reply_count = safe_int(reply_text) if reply_text else -1
            view_count = safe_int(view_text) if view_text else -1
            yield scrapy.Request(
                url=url,
                callback=self.parse_thread,
                meta={
                    "section": section,
                    "fid": fid,
                    "topic_id": tid,
                    "status_flags": status_flags,
                    "list_reply_count": reply_count,
                    "list_view_count": view_count,
                    "current_page": 1,
                },
            )

        next_href = response.xpath("//div[@class='pg']//a[@class='nxt']/@href").get()
        if self._should_paginate(next_href, current_page):
            yield scrapy.Request(
                url=response.urljoin(next_href),
                callback=self.parse_list,
                meta={
                    "section": section,
                    "fid": fid,
                    "current_page": current_page + 1,
                },
            )

    def parse_thread(self, response: Response):
        """解析帖子页：首页产出主贴与回复及楼中楼，翻页仅产出回复与楼中楼，并继续翻页。"""
        section = response.meta.get("section", "")
        fid = response.meta.get("fid")
        topic_id = response.meta.get("topic_id")
        status_flags = response.meta.get("status_flags") or []
        list_reply_count = response.meta.get("list_reply_count", -1)
        list_view_count = response.meta.get("list_view_count", -1)
        current_page = response.meta.get("current_page", 1)

        category_tag = response.xpath(
            "normalize-space(//em[@id='thread_types']//a[contains(@class,'xw1')]/text())"
        ).get()
        if not category_tag:
            category_tag = response.xpath(
                "normalize-space(//div[@id='pt']//a[contains(@href,'typeid=')][last()]/text())"
            ).get()

        post_nodes = response.xpath("//div[@id='postlist']/div[starts-with(@id,'post_')]")
        if current_page == 1 and post_nodes:
            main_post = post_nodes[0]
            pid_attr = main_post.xpath("@id").get()
            main_post_source_id = pid_attr.split("post_")[-1] if pid_attr else None
            thread_item = self._build_post_item(
                response=response,
                post_node=main_post,
                topic_id=topic_id,
                section=section,
                category_tag=category_tag,
                status_flags=status_flags,
                thread_type="thread",
                list_reply_count=list_reply_count,
                list_view_count=list_view_count,
                main_post_source_id=main_post_source_id,
            )
            if thread_item:
                yield thread_item
            reply_nodes = post_nodes[1:]
        else:
            main_post_source_id = response.meta.get("main_post_source_id")
            reply_nodes = post_nodes

        for reply in reply_nodes:
            comment_item = self._build_post_item(
                response=response,
                post_node=reply,
                topic_id=topic_id,
                section=section,
                category_tag=category_tag,
                status_flags=status_flags,
                thread_type="comment",
                main_post_source_id=main_post_source_id,
            )
            if comment_item:
                yield comment_item
            for featured_item in self._parse_featured_comments(
                response=response,
                reply_node=reply,
                topic_id=topic_id,
                section=section,
                category_tag=category_tag,
                status_flags=status_flags,
            ):
                yield featured_item

        next_href = response.xpath("//div[@class='pg']//a[@class='nxt']/@href").get()
        if self._should_paginate(next_href, current_page):
            yield scrapy.Request(
                url=response.urljoin(next_href),
                callback=self.parse_thread,
                meta={
                    "section": section,
                    "fid": fid,
                    "topic_id": topic_id,
                    "status_flags": status_flags,
                    "list_reply_count": list_reply_count,
                    "list_view_count": list_view_count,
                    "current_page": current_page + 1,
                    "main_post_source_id": main_post_source_id,
                },
            )

    def _build_post_item(
        self,
        response: Response,
        post_node,
        topic_id,
        section,
        category_tag,
        status_flags,
        thread_type,
        list_reply_count=None,
        list_view_count=None,
        main_post_source_id=None,
    ):
        """根据 post 节点构建主贴或回复的 CSIForumItem。"""
        pid_attr = post_node.xpath("@id").get()
        if not pid_attr:
            return None

        if self._is_locked_visible_to_author_only(post_node):
            return None
        source_id = pid_attr.split("post_")[-1]

        author_name = post_node.xpath(
            ".//div[contains(@class,'authi')]//a[1]/text()"
        ).get() or ""
        author_href = post_node.xpath(
            ".//div[contains(@class,'authi')]//a[contains(@href,'space-uid-')]/@href"
        ).get()
        author_id = ""
        if author_href:
            m = re.search(r"space-uid-(\d+)", author_href)
            if m:
                author_id = m.group(1)

        publish_text = post_node.xpath(
            "normalize-space(.//div[contains(@class,'authi')]//em[starts-with(@id,'authorposton')]/text())"
        ).get()
        publish_at = None
        if publish_text:
            publish_at = find_datetime_from_str(publish_text)

        last_edit_text = post_node.xpath(
            "normalize-space(.//div[contains(@class,'pi')]//em[@class='xg1' and contains(text(),'最后编辑')]/text())"
        ).get()
        last_edit_at = None
        if last_edit_text:
            last_edit_at = find_datetime_from_str(last_edit_text)
        if not last_edit_at:
            last_edit_at = publish_at

        raw_content_html = post_node.xpath(".//td[contains(@class,'t_f')]").get() or ""

        floor_text = post_node.xpath(
            "normalize-space(.//td[@class='plc']/div[@class='pi']/strong)"
        ).get()
        floor = -1
        if floor_text:
            if floor_text == "舒服的沙发":
                floor = 2
            elif floor_text == "硬硬的板凳":
                floor = 3
            elif floor_text == "冰凉的地板":
                floor = 4
            else:
                floor_text = floor_text.replace("#", "").strip()
                floor = safe_int(floor_text)
        if thread_type == "thread":
            floor = 1

        uuid = generate_uuid(
            "forum" + str(topic_id) + source_id + str(last_edit_at) + raw_content_html
        )

        item = CSIForumItem()
        item["uuid"] = uuid
        item["source_id"] = source_id
        item["data_version"] = 1
        item["entity_type"] = "forum"
        item["url"] = response.url
        item["tags"] = []
        item["platform"] = "3DMGAME论坛"
        item["section"] = section
        item["spider_name"] = self.name
        item["crawled_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        item["publish_at"] = publish_at
        item["last_edit_at"] = last_edit_at
        item["author_id"] = author_id
        item["author_name"] = author_name
        item["nsfw"] = False
        item["aigc"] = False

        item["topic_id"] = topic_id
        if thread_type == "thread":
            item["parent_id"] = source_id
        else:
            item["parent_id"] = main_post_source_id
        item["floor"] = floor
        item["thread_type"] = thread_type
        item["category_tag"] = category_tag
        item["title"] = (
            response.xpath("normalize-space(//span[@id='thread_subject']/text())").get()
            or ""
        )
        item["raw_content"] = raw_content_html
        item["status_flags"] = status_flags or []

        if list_reply_count is not None and list_reply_count != -1:
            item["comments"] = list_reply_count
        else:
            item["comments"] = -1
        if list_view_count is not None and list_view_count != -1:
            item["views"] = list_view_count
        else:
            item["views"] = -1

        item["likes"] = -1
        item["dislikes"] = -1
        item["collections"] = -1

        return item

    def _is_locked_visible_to_author_only(self, node) -> bool:
        """是否为“仅作者可见”的隐藏内容楼层。"""
        locked_text = node.xpath(
            "normalize-space(.//div[contains(@class,'locked')][1])"
        ).get()
        if locked_text and "此帖仅作者可见" in locked_text:
            return True

        locked_html = node.xpath(
            ".//div[contains(@class,'locked') and contains(., '此帖仅作者可见')][1]"
        ).get()
        return bool(locked_html)

    def _parse_featured_comments(
        self,
        response: Response,
        reply_node,
        topic_id,
        section,
        category_tag,
        status_flags,
    ):
        """解析单条回复下的楼中楼，产出 thread_type=featured 的条目。"""
        parent_pid_attr = reply_node.xpath("@id").get()
        if not parent_pid_attr:
            return
        parent_id = parent_pid_attr.split("post_")[-1]

        featured_nodes = reply_node.xpath(
            ".//div[contains(@class,'psth') or contains(@class,'cm')]//li"
        )
        index = 0
        for node in featured_nodes:
            if self._is_locked_visible_to_author_only(node):
                continue
            index += 1
            cid_attr = node.xpath("@id").get()
            if cid_attr and "comment_" in cid_attr:
                source_id = cid_attr.split("comment_")[-1]
            else:
                source_id = f"{parent_id}_{index}"

            author_name = node.xpath(
                ".//a[contains(@href,'space-uid-')][1]/text()"
            ).get() or ""
            author_href = node.xpath(
                ".//a[contains(@href,'space-uid-')][1]/@href"
            ).get()
            author_id = ""
            if author_href:
                m = re.search(r"space-uid-(\d+)", author_href)
                if m:
                    author_id = m.group(1)

            time_text = node.xpath(
                "normalize-space(.//span[contains(@class,'xg1')]/text())"
            ).get()
            publish_at = None
            if time_text:
                publish_at = find_datetime_from_str(time_text)
            last_edit_at = publish_at

            raw_content_html = node.xpath("string(.)").get() or ""

            uuid = generate_uuid(
                "forum"
                + str(topic_id)
                + source_id
                + str(last_edit_at)
                + raw_content_html
            )

            item = CSIForumItem()
            item["uuid"] = uuid
            item["source_id"] = source_id
            item["data_version"] = 1
            item["entity_type"] = "forum"
            item["url"] = response.url
            item["tags"] = []
            item["platform"] = "3DMGAME论坛"
            item["section"] = section
            item["spider_name"] = self.name
            item["crawled_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            item["publish_at"] = publish_at
            item["last_edit_at"] = last_edit_at
            item["author_id"] = author_id
            item["author_name"] = author_name
            item["nsfw"] = False
            item["aigc"] = False

            item["topic_id"] = topic_id
            item["parent_id"] = parent_id
            item["floor"] = index
            item["thread_type"] = "featured"
            item["category_tag"] = category_tag
            item["title"] = (
                response.xpath(
                    "normalize-space(//span[@id='thread_subject']/text())"
                ).get()
                or ""
            )
            item["raw_content"] = raw_content_html
            item["status_flags"] = status_flags or []

            item["likes"] = -1
            item["dislikes"] = -1
            item["collections"] = -1
            item["comments"] = -1
            item["views"] = -1

            yield item

    def _should_paginate(self, next_href, current_page):
        """根据是否有下一页链接及 page 参数判断是否继续翻页。"""
        if not next_href:
            return False
        if self.page is None or self.page <= 0:
            return True
        try:
            current_page_int = int(current_page)
        except (TypeError, ValueError):
            current_page_int = 1
        return current_page_int < self.page

    def _extract_tid(self, href: str):
        """从帖子链接中提取 tid。"""
        m = re.search(r"thread-(\d+)-", href)
        if m:
            return m.group(1)
        m = re.search(r"[?&]tid=(\d+)", href)
        if m:
            return m.group(1)
        return ""

    def _extract_status_flags_from_row(self, row):
        """从列表行提取置顶、精华等状态标识。"""
        flags = []
        row_id = row.xpath("@id").get() or ""
        if row_id.startswith("stickthread_"):
            flags.append("top")
        img_srcs = row.xpath(".//th//img/@src").getall()
        for src in img_srcs:
            if "digest" in src and "digest" not in flags:
                flags.append("digest")
        return flags

