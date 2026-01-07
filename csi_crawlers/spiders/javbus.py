from datetime import datetime
import scrapy
from scrapy.http import HtmlResponse
from urllib.parse import urlparse, parse_qs
from csi_crawlers.items import CSIForumItem
from csi_crawlers.utils import find_datetime_from_str, find_int_from_str, generate_uuid, get_flag_name_from_url, safe_int
from csi_crawlers.spiders.base import BaseSpider

# TODO: 按照发帖时间搜索
# TODO: 采集站点主页信息
# TODO: 采集站点评论信息
# TODO: 采集站点用户信息

class JavbusSpider(BaseSpider):
    name = "javbus"
    allowed_domains = ["www.javbus.com"]
    
    crawled_users = []
    
    async def start(self):
        # 先去主页获取一个默认的 phpsessid
        if self.crawler_type == 'default':
            next_call = self.goto_forum
        elif self.crawler_type == 'keyword':
            if not self.keywords:
                raise ValueError('关键词不能为空')
            next_call = self.goto_search
        else:
            raise ValueError(f'不支持的爬虫类型: {self.crawler_type}')
        
        yield scrapy.Request(
            url="https://www.javbus.com/",
            callback=next_call
        )

    def goto_search(self, response: HtmlResponse):
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

    def goto_forum(self, response: HtmlResponse):
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
    
    def parse_thread(self, response: HtmlResponse):
        forum_item = CSIForumItem()
        
        parsed_url = urlparse(response.url)
        query_params = parse_qs(parsed_url.query)
        tid = query_params.get('tid', [None])[0]
        
        # 首先处理主帖
        first_post_box = response.xpath("//div[@class='nthread_postbox nthread_firstpostbox']")
        
        author_info_box = first_post_box.xpath("//div[@class='viewthread_authorinfo']")
        if author_info_box:
            author_url = author_info_box.xpath(".//div[@class='authi']/a/@href").get()
            parsed_author_url = urlparse("https://www.javbus.com/forum/" + author_url)
            author_query_params = parse_qs(parsed_author_url.query)
            author_id = author_query_params.get('uid', [None])[0]
            author_name = author_info_box.xpath(".//div[@class='authi']/a/text()").get()
        else:
            author_id = None
            author_name = None
        
        # 如果翻页则没有 first_post_box
        if first_post_box:
            raw_content = first_post_box.xpath(".//div[@class='t_fsz']").get() or ""
            last_edit_at = find_datetime_from_str(first_post_box.xpath(".//i[@class='pstatus']/text()").get()) or None
            source_id = (first_post_box.xpath('./td[@class="t_f"]/@id').get() or tid).split("postmessage_")[-1].strip()
            category_tag = response.xpath("//div[@class='nthread_info cl']/h1/a/font/text()").get()
            title = (response.xpath("//div[@class='nthread_info cl']/h1/span/text()").get() or "").strip()
            
            forum_item["uuid"] = generate_uuid(source_id + str(last_edit_at) + raw_content)
            forum_item["topic_id"] = tid
            forum_item["source_id"] = source_id
            forum_item["url"] = response.url
            forum_item["platform"] = self.name
            forum_item["section"] = response.meta["section"]
            forum_item["spider_name"] = "csi_crawlers-javbus"
            forum_item["crawled_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            forum_item["publish_at"] = response.xpath("//span[@class='mr10']/text()").get()
            forum_item["last_edit_at"] = last_edit_at
            forum_item["author_id"] = author_id
            forum_item["author_name"] = author_name
            forum_item["nsfw"] = True
            forum_item["aigc"] = False
            forum_item["parent_id"] = tid
            forum_item["floor"] = 1
            forum_item["thread_type"] = "main"
            forum_item["category_tag"] = category_tag
            forum_item["title"] = title
            forum_item["raw_content"] = raw_content
            forum_item["status_flags"] = response.meta["status_flags"]
            forum_item["likes"] = safe_int(response.xpath("//span[@id='recommendv_add']/text()").get()) or -1
            forum_item["dislikes"] = -1
            forum_item["collections"] = safe_int(response.xpath("//span[@id='favoritenumber']/text()").get()) or -1
            forum_item["comments"] = find_int_from_str(response.xpath("//div[@class='authi mb5']/span[@class='y']/text()").get()) or -1
            forum_item["views"] = find_int_from_str(response.xpath("//div[@class='authi mb5']/span[@class='mr10 y']/text()").get()) or -1
                    
            yield forum_item
            
            # 继续处理主贴点评
            comment_containers = first_post_box.xpath(".//div[starts-with(@id, 'comment_')]")
            for comment_container in comment_containers:
                comment_id_attr = comment_container.xpath("./@id").get()
                if not comment_id_attr:
                    continue
                comment_source_id = comment_id_attr.split("comment_")[-1].strip()
                
                featured_posts = comment_container.xpath("./div")
                inner_floor = 0
                for featured_post in featured_posts:
                    inner_floor += 1
                    featured_post_item = CSIForumItem()
                    
                    raw_content = featured_post.xpath("./div[@class='psti']/text()").get() or ""
                    author_href = featured_post.xpath(".//div/a/@href").get()
                    author_id = None
                    if author_href and "&uid=" in author_href:
                        author_id = author_href.split("&uid=")[-1].strip()
                    
                    author_name_elem = featured_post.xpath("(.//div/a/text())[last()]").get()
                    author_name = author_name_elem.strip() if author_name_elem else None
                    
                    if not raw_content or not author_id or not author_name:
                        continue
                    
                    featured_post_item["uuid"] = generate_uuid(comment_source_id + str(last_edit_at) + raw_content)
                    featured_post_item["topic_id"] = tid
                    featured_post_item["source_id"] = comment_source_id
                    featured_post_item["url"] = response.url
                    featured_post_item["platform"] = self.name
                    featured_post_item["section"] = response.meta["section"]
                    featured_post_item["spider_name"] = "csi_crawlers-javbus"
                    featured_post_item["crawled_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    featured_post_item["publish_at"] = response.xpath("//span[@class='mr10']/text()").get()
                    featured_post_item["last_edit_at"] = last_edit_at
                    featured_post_item["author_id"] = author_id
                    featured_post_item["author_name"] = author_name
                    featured_post_item["nsfw"] = True
                    featured_post_item["aigc"] = False
                    featured_post_item["parent_id"] = source_id
                    featured_post_item["floor"] = inner_floor
                    featured_post_item["thread_type"] = "featured"
                    featured_post_item["category_tag"] = category_tag
                    featured_post_item["title"] = title
                    featured_post_item["raw_content"] = raw_content
                    featured_post_item["status_flags"] = []
                    featured_post_item["likes"] = -1
                    featured_post_item["dislikes"] = -1
                    featured_post_item["collections"] = -1
                    featured_post_item["comments"] = -1
                    featured_post_item["views"] = -1
                    
                    yield featured_post_item

        # 处理评论
        post_boxes = response.xpath("//div[@class='nthread_postbox']")
        for post_box in post_boxes:
            pass
        
        # TODO: 翻页
        