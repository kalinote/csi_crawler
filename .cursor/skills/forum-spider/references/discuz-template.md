# Forum 类爬虫代码模板（基于 Discuz!）

Forum 类站点（如 Reddit、贴吧、Discuz! 社区）的核心特征：帖子分为主贴（thread）、普通回复（comment）、楼中楼/点评（featured），每一条数据都以 `CSIForumItem` 存储，通过 `topic_id`/`parent_id`/`floor`/`thread_type` 描述层级关系。

以下代码以某基于 Discuz! 构建的社区站为参考实现。

```python
from datetime import datetime
import scrapy
from scrapy.http import HtmlResponse
from urllib.parse import urlparse, parse_qs
from csi_crawlers.items import CSIForumItem
from csi_crawlers.utils import (
    find_datetime_from_str, find_int_from_str, generate_uuid,
    get_flag_name_from_url, safe_int, extract_param_from_url
)
from csi_crawlers.spiders.base import BaseSpider


class DiscuzSpider(BaseSpider):
    name = "discuz_example"
    allowed_domains = ["www.example.com"]

    # 板块名 -> Discuz! fid 映射
    section_map = {
        "板块名": 2,
    }

    # ────────────────────────────────────────────────────────
    # 关键词采集：先 GET 搜索页获取 formhash，再 POST 提交
    # ────────────────────────────────────────────────────────
    def search_start(self, response: HtmlResponse):
        yield scrapy.Request(
            url="https://www.example.com/forum/search.php?mod=forum",
            callback=self.post_search
        )

    def post_search(self, response: HtmlResponse):
        formhash_value = response.xpath("//input[@name='formhash']/@value").get()
        if not formhash_value:
            self.logger.error("无法获取formhash值")
            return

        for index, keyword in enumerate(self.keywords):
            delay = index * 90
            yield scrapy.FormRequest(
                url="https://www.example.com/forum/search.php?mod=forum",
                formdata={
                    "srchtxt": keyword,
                    "searchsubmit": "yes",
                    "formhash": formhash_value,
                },
                callback=self.parse_keyword,
                meta={
                    "download_delay": delay,
                    "current_page": 1,
                    "keyword": keyword
                },
                dont_filter=True,
                priority=-index
            )

    def parse_keyword(self, response: HtmlResponse):
        current_page = response.meta.get("current_page")
        keyword = response.meta.get("keyword")
        self.logger.info(f"正在爬取关键词 '{keyword}' 的搜索结果第 {current_page} 页")

        for thread in response.xpath("//li[@class='pbw']"):
            thread_url = thread.xpath(".//h3/a/@href").get()
            if not thread_url:
                continue
            yield response.follow(
                url=thread_url,
                callback=self.parse_thread,
                meta={"status_flags": [], "section": "关键词搜索"}
            )

        next_page_link = response.xpath("//a[@class='nxt']/@href").get()
        if next_page_link:
            should_continue = (self.page is None or self.page <= 0) or (current_page < self.page)
            if should_continue:
                yield scrapy.Request(
                    url=response.urljoin(next_page_link),
                    callback=self.parse_keyword,
                    meta={
                        "current_page": current_page + 1,
                        "keyword": keyword,
                        "download_delay": 5
                    },
                    dont_filter=True
                )
        else:
            self.logger.info(f"关键词 '{keyword}' 已到达最后一页，当前第 {current_page} 页")

    # ────────────────────────────────────────────────────────
    # 默认采集：按板块 fid 抓帖子列表
    # ────────────────────────────────────────────────────────
    def default_start(self, response: HtmlResponse):
        for section in self.sections:
            if section == "__default__":
                section = "板块名"
            fid = self.section_map.get(section)
            if not fid:
                self.logger.error(f"未知采集板块: {section}")
                continue
            yield scrapy.Request(
                url=f"https://www.example.com/forum/forum.php?mod=forumdisplay&fid={fid}",
                callback=self.parse_forum,
                meta={"current_page": 1, "section": section}
            )

    def parse_forum(self, response: HtmlResponse):
        current_page = response.meta.get("current_page", 1)
        section = response.meta.get("section", "")
        self.logger.info(f"正在爬取{section}论坛列表第 {current_page} 页")

        for thread in response.xpath("//tbody[starts-with(@id, 'normalthread_')]"):
            thread_url = thread.xpath(".//a[@class='s']/@href").get()
            if not thread_url:
                continue

            # 从列表页图标提取置顶/精华等 status_flags
            status_flags = []
            for img in thread.xpath(".//img[@align='absmiddle']"):
                flag = get_flag_name_from_url(img.xpath("./@src").get())
                if flag and flag not in status_flags:
                    status_flags.append(flag)

            yield response.follow(
                url=thread_url,
                callback=self.parse_thread,
                meta={"status_flags": status_flags, "section": section}
            )

        next_page_link = response.xpath("//a[@class='nxt']/@href").get()
        if next_page_link:
            should_continue = (self.page is None or self.page <= 0) or (current_page < self.page)
            if should_continue:
                yield scrapy.Request(
                    url=response.urljoin(next_page_link),
                    callback=self.parse_forum,
                    meta={
                        "current_page": current_page + 1,
                        "section": section,
                        "download_delay": 5
                    },
                    dont_filter=True
                )
        else:
            self.logger.info(f"已到达最后一页，当前第 {current_page} 页")

    # ────────────────────────────────────────────────────────
    # 辅助方法
    # ────────────────────────────────────────────────────────
    def _init_base_item(self, response, tid, section):
        """初始化 CSIForumItem 并填充所有帖子通用的固定字段"""
        item = CSIForumItem()
        item["entity_type"] = "forum"
        item["data_version"] = 1
        item["topic_id"] = tid
        item["url"] = response.url
        item["platform"] = "示例社区"        # 替换为目标站名称
        item["spider_name"] = self.name
        item["section"] = section
        item["crawled_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        item["nsfw"] = False
        item["aigc"] = False
        for field in ["likes", "dislikes", "collections", "comments", "views"]:
            item[field] = -1
        return item

    def _parse_featured_comments(self, comment_containers, parent_source_id, parent_last_edit_at, common_data):
        """解析楼中楼/点评（featured），并以 parent_source_id 作为 parent_id"""
        response = common_data["response"]
        tid = common_data["tid"]
        section = common_data["section"]
        category_tag = common_data["category_tag"]
        title = common_data["title"]

        for comment_container in comment_containers:
            comment_id_attr = comment_container.xpath("./@id").get()
            if not comment_id_attr:
                continue
            source_id = comment_id_attr.split("comment_")[-1].strip()

            for inner_floor, featured_post in enumerate(comment_container.xpath("./div"), 1):
                raw_content = featured_post.xpath("./div[@class='psti']/text()").get() or ""
                author_href = featured_post.xpath(".//div/a/@href").get()
                author_id = extract_param_from_url(author_href, "uid")
                author_name_elem = featured_post.xpath("(.//div/a/text())[last()]").get()
                author_name = author_name_elem.strip() if author_name_elem else None

                if not raw_content or not author_id or not author_name:
                    continue

                item = self._init_base_item(response, tid, section)
                publish_at = find_datetime_from_str(
                    featured_post.xpath('.//div[@class="psti"]/span/text()').get()
                )
                item.update({
                    "uuid": generate_uuid("forum" + source_id + str(parent_last_edit_at) + raw_content),
                    "source_id": source_id,
                    "publish_at": publish_at,
                    "last_edit_at": publish_at,    # 点评通常无编辑时间，视同发布时间
                    "author_id": author_id,
                    "author_name": author_name,
                    "parent_id": parent_source_id,
                    "floor": inner_floor,
                    "thread_type": "featured",
                    "category_tag": category_tag,
                    "title": title,
                    "raw_content": raw_content,
                    "status_flags": [],
                })
                yield item

    # ────────────────────────────────────────────────────────
    # 帖子详情：主贴 + 回复 + 楼中楼，支持评论翻页
    # ────────────────────────────────────────────────────────
    def parse_thread(self, response: HtmlResponse):
        parsed_url = urlparse(response.url)
        tid = parse_qs(parsed_url.query).get("tid", [None])[0]
        section = response.meta.get("section", "")

        common_data = {
            "response": response,
            "tid": tid,
            "section": section,
            "category_tag": "",
            "title": "",
        }

        # ── 主贴（仅第一页存在 nthread_firstpostbox）──
        first_post_box = response.xpath("//div[@class='nthread_postbox nthread_firstpostbox']")
        if first_post_box:
            source_id = (first_post_box.xpath("./@id").get() or tid).split("post_")[-1].strip()
            raw_content = first_post_box.xpath(".//div[@class='t_fsz']").get() or ""
            last_edit_at = find_datetime_from_str(
                first_post_box.xpath(".//i[@class='pstatus']/text()").get()
            )

            common_data["category_tag"] = response.xpath(
                "//div[@class='nthread_info cl']/h1/a/font/text()"
            ).get()
            common_data["title"] = (
                response.xpath("//div[@class='nthread_info cl']/h1/span/text()").get() or ""
            ).strip()

            forum_item = self._init_base_item(response, tid, section)
            author_info = response.xpath("//div[@class='viewthread_authorinfo']")
            if author_info:
                forum_item["author_id"] = extract_param_from_url(
                    author_info.xpath(".//div[@class='authi']/a/@href").get(), "uid"
                )
                forum_item["author_name"] = author_info.xpath(".//div[@class='authi']/a/text()").get()

            forum_item.update({
                "uuid": generate_uuid("forum" + source_id + str(last_edit_at) + raw_content),
                "source_id": source_id,
                "publish_at": response.xpath("//span[@class='mr10']/text()").get(),
                "last_edit_at": last_edit_at,
                "parent_id": tid,
                "floor": 1,
                "thread_type": "thread",
                "category_tag": common_data["category_tag"],
                "title": common_data["title"],
                "raw_content": raw_content,
                "status_flags": response.meta.get("status_flags", []),
                "likes": safe_int(response.xpath("//span[@id='recommendv_add']/text()").get()) or -1,
                "collections": safe_int(response.xpath("//span[@id='favoritenumber']/text()").get()) or -1,
                "comments": find_int_from_str(
                    response.xpath("//div[@class='authi mb5']/span[@class='y']/text()").get()
                ) or -1,
                "views": find_int_from_str(
                    response.xpath("//div[@class='authi mb5']/span[@class='mr10 y']/text()").get()
                ) or -1,
            })
            yield forum_item

            yield from self._parse_featured_comments(
                first_post_box.xpath(".//div[starts-with(@id, 'comment_')]"),
                source_id, last_edit_at, common_data
            )
        else:
            # 评论翻页后恢复上下文
            common_data["category_tag"] = response.meta.get("category_tag", "")
            common_data["title"] = response.meta.get("title", "")
            source_id = response.meta.get("source_id", tid)

        # ── 普通回复（comment）──
        for post_box in response.xpath("//div[@class='nthread_postbox']"):
            comment_source_id = (post_box.xpath("./@id").get() or tid).split("post_")[-1].strip()
            comment_last_edit_at = find_datetime_from_str(
                post_box.xpath("./em[starts-with(@id, 'authorposton')]/text()").get()
            )
            comment_raw_content = post_box.xpath('.//td[@class="t_f"]').get() or ""

            raw_floor = post_box.xpath(".//strong/a/em/text()").get()
            if not raw_floor:
                raw_floor = post_box.xpath(".//strong/a/text()").get()
                if raw_floor and raw_floor.strip() == "樓主":
                    raw_floor = 2

            comment_item = self._init_base_item(response, tid, section)
            comment_item.update({
                "uuid": generate_uuid(
                    "forum" + comment_source_id + str(comment_last_edit_at) + comment_raw_content
                ),
                "source_id": comment_source_id,
                "publish_at": comment_last_edit_at,
                "last_edit_at": comment_last_edit_at,
                "author_id": extract_param_from_url(
                    post_box.xpath('.//div[@class="authi"]/a/@href').get(), "uid"
                ),
                "author_name": post_box.xpath('.//div[@class="authi"]/a/text()').get() or "",
                "parent_id": source_id or tid,
                "floor": safe_int(raw_floor) or -1,
                "thread_type": "comment",
                "category_tag": common_data["category_tag"],
                "title": common_data["title"],
                "raw_content": comment_raw_content,
                "status_flags": [],
            })
            yield comment_item

            yield from self._parse_featured_comments(
                post_box.xpath(".//div[starts-with(@id, 'comment_')]"),
                comment_source_id, comment_last_edit_at, common_data
            )

        # ── 评论翻页 ──
        next_page_link = response.xpath("//a[@class='nxt']/@href").get()
        if next_page_link:
            self.logger.info(f"帖子 {tid} 5秒后将爬取下一页评论")
            yield scrapy.Request(
                url=response.urljoin(next_page_link),
                callback=self.parse_thread,
                meta={
                    "section": section,
                    "status_flags": response.meta.get("status_flags"),
                    "source_id": source_id,
                    "category_tag": common_data["category_tag"],
                    "title": common_data["title"],
                    "download_delay": 5,
                }
            )
```

替换要点：

- `name`、`allowed_domains`、`section_map`（板块名 → Discuz! fid）、所有 URL 换成目标站域名。
- `_init_base_item` 中的 `platform` 换成目标站名称；`nsfw` 按实际设置。
- `parse_forum` 中的列表 XPath（`normalthread_*`、`a[@class='s']`）按目标站 HTML 结构调整。
- `parse_thread` 中主贴/回复/楼中楼的 XPath 按目标站调整；若目标站无楼中楼，删除 `_parse_featured_comments` 调用即可。
- 若目标站搜索不需要 formhash（如直接 GET 参数），`search_start` 可简化为直接 yield 搜索请求，去掉 `post_search` 中间步骤。
