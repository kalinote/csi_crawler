from datetime import datetime
import scrapy
from scrapy.http import HtmlResponse
from urllib.parse import urlparse, parse_qs
from csi_crawlers.items import CSIForumItem
from csi_crawlers.utils import find_datetime_from_str, find_int_from_str, generate_uuid, get_flag_name_from_url, safe_int, extract_param_from_url
from csi_crawlers.spiders.base import BaseSpider

# TODO: 按照发帖时间搜索
# TODO: 采集站点主页信息
# TODO: 采集站点用户信息

class JavbusSpider(BaseSpider):
    name = "javbus"
    allowed_domains = ["www.javbus.com"]
    
    crawled_users = []
    start_url = "https://www.javbus.com/"

    def search_start(self, response: HtmlResponse):
        yield scrapy.Request(
            url="https://www.javbus.com/forum/search.php?mod=forum",
            callback=self.post_search
        )
    
    def post_search(self, response: HtmlResponse):
        formhash_value = response.xpath("//input[@name='formhash']/@value").get()
        
        if not formhash_value:
            self.logger.error("无法获取formhash值")
            return
        
        for index, keyword in enumerate(self.keywords):
            delay = index * 90
            self.logger.info(f"关键词 '{keyword}' 将在 {delay} 秒后执行搜索")
            yield scrapy.FormRequest(
                url="https://www.javbus.com/forum/search.php?mod=forum",
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
        
        threads = response.xpath("//li[@class='pbw']")
        for thread in threads:
            thread_url = thread.xpath(".//h3/a/@href").get()
            if not thread_url:
                continue
            
            yield response.follow(
                url=thread_url,
                callback=self.parse_thread,
                meta={
                    "status_flags": [],
                    "section": "关键词搜索"
                }
            )
        
        next_page_link = response.xpath("//a[@class='nxt']/@href").get()
        
        if next_page_link:
            should_continue = False
            
            if (self.page is None or self.page <= 0) or (current_page < self.page):
                should_continue = True
            
            if should_continue:
                next_page_url = response.urljoin(next_page_link)
                self.logger.info(f"5秒后将爬取关键词 '{keyword}' 的第 {current_page + 1} 页")
                yield scrapy.Request(
                    url=next_page_url,
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

    def default_start(self, response: HtmlResponse):
        yield scrapy.Request(
            url="https://www.javbus.com/forum/forum.php?mod=forumdisplay&fid=2",
            callback=self.parse_forum,
            meta={"current_page": 1}
        )

    def parse_forum(self, response: HtmlResponse):
        current_page = response.meta.get("current_page", 1)
        self.logger.info(f"正在爬取论坛列表第 {current_page} 页")
        
        threads = response.xpath("//tbody[starts-with(@id, 'normalthread_')]")
        for thread in threads:
            thread_url = thread.xpath(".//a[@class='s']/@href").get()
            if not thread_url:
                continue
            
            status_flags = []
            status_flags_imgs = thread.xpath(".//img[@align='absmiddle']")
            
            for status_flags_img in status_flags_imgs:
                flag = get_flag_name_from_url(status_flags_img.xpath("./@src").get())
                if flag and flag not in status_flags:
                    status_flags.append(flag)

            yield response.follow(
                url=thread_url,
                callback=self.parse_thread,
                meta={
                    "status_flags": status_flags,
                    "section": "老司机福利讨论区"
                }
            )
        
        next_page_link = response.xpath("//a[@class='nxt']/@href").get()
        
        if next_page_link:
            should_continue = False
            
            if (self.page is None or self.page <= 0) or (current_page < self.page):
                should_continue = True
            
            if should_continue:
                next_page_url = response.urljoin(next_page_link)
                self.logger.info(f"5秒后将爬取第 {current_page + 1} 页")
                yield scrapy.Request(
                    url=next_page_url,
                    callback=self.parse_forum,
                    meta={
                        "current_page": current_page + 1,
                        "download_delay": 5
                    },
                    dont_filter=True
                )
        else:
            self.logger.info(f"已到达最后一页，当前第 {current_page} 页")
    
    def _init_base_item(self, response, tid, section):
        """辅助方法：初始化基础 Item 并填充通用字段"""
        item = CSIForumItem()
        item["entity_type"] = "forum"
        item["data_version"] = 1
        item["topic_id"] = tid
        item["url"] = response.url
        item["platform"] = "Javbus"
        item["spider_name"] = "csi_crawlers-" + self.name
        item["section"] = section
        item["crawled_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        item["nsfw"] = True
        item["aigc"] = False
        
        # 设置默认值为 -1 的字段
        for field in ["likes", "dislikes", "collections", "comments", "views"]:
            item[field] = -1
            
        return item

    def _parse_featured_comments(self, comment_containers, parent_source_id, parent_last_edit_at, common_data):
        """辅助方法：解析楼中楼/点评 (消除重复逻辑)"""
        # 解包通用数据
        response = common_data['response']
        tid = common_data['tid']
        section = common_data['section']
        category_tag = common_data['category_tag']
        title = common_data['title']

        for comment_container in comment_containers:
            comment_id_attr = comment_container.xpath("./@id").get()
            if not comment_id_attr:
                continue
            
            source_id = comment_id_attr.split("comment_")[-1].strip()
            featured_posts = comment_container.xpath("./div")
            
            # 使用 enumerate 自动计算楼层
            for inner_floor, featured_post in enumerate(featured_posts, 1):
                raw_content = featured_post.xpath("./div[@class='psti']/text()").get() or ""
                author_href = featured_post.xpath(".//div/a/@href").get()
                author_id = extract_param_from_url(author_href, "uid")
                
                author_name_elem = featured_post.xpath("(.//div/a/text())[last()]").get()
                author_name = author_name_elem.strip() if author_name_elem else None
                
                if not raw_content or not author_id or not author_name:
                    continue
                
                # 使用辅助函数初始化
                item = self._init_base_item(response, tid, section)
                
                # 填充特定字段
                item["uuid"] = generate_uuid("forum" + source_id + str(parent_last_edit_at) + raw_content)
                item["source_id"] = source_id
                item["publish_at"] = find_datetime_from_str(featured_post.xpath('.//div[@class="psti"]/span/text()').get())
                item["last_edit_at"] = item["publish_at"] # 点评通常没有编辑时间，视作同发布时间
                item["author_id"] = author_id
                item["author_name"] = author_name
                item["parent_id"] = parent_source_id
                item["floor"] = inner_floor
                item["thread_type"] = "featured"
                item["category_tag"] = category_tag
                item["title"] = title
                item["raw_content"] = raw_content
                item["status_flags"] = []
                
                yield item

    def parse_thread(self, response: HtmlResponse):
        parsed_url = urlparse(response.url)
        query_params = parse_qs(parsed_url.query)
        tid = query_params.get('tid', [None])[0]
        section = response.meta.get("section", "")
        
        # 准备传递给子函数的通用数据包
        common_data = {
            'response': response,
            'tid': tid,
            'section': section,
            'category_tag': "", # 后续填充
            'title': ""         # 后续填充
        }

        # 1. 处理主帖 (First Post)
        first_post_box = response.xpath("//div[@class='nthread_postbox nthread_firstpostbox']")
        
        # 如果不是翻页，存在 first_post_box
        if first_post_box:
            # 提取主贴特有信息
            raw_content = first_post_box.xpath(".//div[@class='t_fsz']").get() or ""
            last_edit_at = find_datetime_from_str(first_post_box.xpath(".//i[@class='pstatus']/text()").get()) or None
            source_id = (first_post_box.xpath("./@id").get() or tid).split("post_")[-1].strip()
            
            # 更新 common_data
            common_data['category_tag'] = response.xpath("//div[@class='nthread_info cl']/h1/a/font/text()").get()
            common_data['title'] = (response.xpath("//div[@class='nthread_info cl']/h1/span/text()").get() or "").strip()
            
            # 初始化并填充主贴 Item
            forum_item = self._init_base_item(response, tid, section)
            
            author_info_box = first_post_box.xpath("//div[@class='viewthread_authorinfo']")
            if author_info_box:
                forum_item["author_id"] = extract_param_from_url(author_info_box.xpath(".//div[@class='authi']/a/@href").get(), "uid")
                forum_item["author_name"] = author_info_box.xpath(".//div[@class='authi']/a/text()").get()
            
            forum_item.update({
                "uuid": generate_uuid("forum" + source_id + str(last_edit_at) + raw_content),
                "source_id": source_id,
                "publish_at": response.xpath("//span[@class='mr10']/text()").get(),
                "last_edit_at": last_edit_at,
                "parent_id": tid,
                "floor": 1,
                "thread_type": "thread",
                "category_tag": common_data['category_tag'],
                "title": common_data['title'],
                "raw_content": raw_content,
                "status_flags": response.meta.get("status_flags", []),
                "likes": safe_int(response.xpath("//span[@id='recommendv_add']/text()").get()) or -1,
                "collections": safe_int(response.xpath("//span[@id='favoritenumber']/text()").get()) or -1,
                "comments": find_int_from_str(response.xpath("//div[@class='authi mb5']/span[@class='y']/text()").get()) or -1,
                "views": find_int_from_str(response.xpath("//div[@class='authi mb5']/span[@class='mr10 y']/text()").get()) or -1,
            })
            
            yield forum_item
            
            # 处理主贴下的点评/楼中楼 (复用逻辑)
            yield from self._parse_featured_comments(
                first_post_box.xpath(".//div[starts-with(@id, 'comment_')]"),
                source_id,
                last_edit_at,
                common_data
            )
            
        else:
            # 翻页情况：从 meta 恢复主贴信息供后续使用
            common_data['category_tag'] = response.meta.get("category_tag", "")
            common_data['title'] = response.meta.get("title", "")
            # 注意：source_id 在这里如果是翻页，通常还是指向主贴ID或者上一页传过来的ID，用于关联
            source_id = response.meta.get("source_id", tid)

        # 2. 处理普通回复 (Comments)
        post_boxes = response.xpath("//div[@class='nthread_postbox']")
        for post_box in post_boxes:
            comment_source_id = (post_box.xpath("./@id").get() or tid).split("post_")[-1].strip()
            comment_last_edit_at = find_datetime_from_str(post_box.xpath("./em[starts-with(@id, 'authorposton')]/text()").get()) or None
            comment_raw_content = post_box.xpath('.//td[@class="t_f"]').get() or ""
            
            comment_item = self._init_base_item(response, tid, section)
            
            comment_item.update({
                "uuid": generate_uuid("forum" + comment_source_id + str(comment_last_edit_at) + comment_raw_content),
                "source_id": comment_source_id,
                "publish_at": comment_last_edit_at,
                "last_edit_at": comment_last_edit_at,
                "author_id": extract_param_from_url(post_box.xpath('.//div[@class="authi"]/a/@href').get(), "uid"),
                "author_name": post_box.xpath('.//div[@class="authi"]/a/text()').get() or "",
                "parent_id": source_id or tid,
                "floor": safe_int(post_box.xpath(".//strong/a/em/text()").get()) or -1,
                "thread_type": "comment",
                "category_tag": common_data['category_tag'],
                "title": common_data['title'],
                "raw_content": comment_raw_content,
                "status_flags": [],
            })
            
            yield comment_item
            
            # 处理回复下的点评/楼中楼 (复用逻辑)
            yield from self._parse_featured_comments(
                post_box.xpath(".//div[starts-with(@id, 'comment_')]"),
                comment_source_id,
                comment_last_edit_at,
                common_data
            )
        
        # 处理评论翻页
        next_page_link = response.xpath("//a[@class='nxt']/@href").get()
        if next_page_link:
            next_page_url = response.urljoin(next_page_link)
            self.logger.info(f"帖子 {tid} 5秒后将爬取下一页评论")
            
            yield scrapy.Request(
                url=next_page_url,
                callback=self.parse_thread,
                meta={
                    "section": section,
                    "status_flags": response.meta.get("status_flags"),
                    "source_id": source_id,
                    "category_tag": common_data['category_tag'],
                    "title": common_data['title'],
                    "download_delay": 5
                }
            )
        
        