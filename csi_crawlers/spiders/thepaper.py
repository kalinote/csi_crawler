import scrapy
import json
from scrapy.http import Response, JsonRequest, JsonResponse, headers
from csi_crawlers.items import CSIArticlesItem
from csi_crawlers.utils import generate_uuid
from csi_crawlers.spiders.base import BaseSpider
import datetime


class ThepaperSpider(BaseSpider):
    name = "thepaper"
    allowed_domains = ["thepaper.cn"]

    headers = {
        "content-type": "application/json",
    }

    def default_start(self, response):
        yield JsonRequest(
            url="https://api.thepaper.cn/contentapi/nodeCont/getByChannelId",
            headers=self.headers,
            data={
                "channelId": "",
                "excludeContIds": [],
                "listRecommendIds": [],
                "pageNum": 1,
                "pageSize": 50,
                "startTime": ""
            },
            callback=self.parse_default_list,
            meta={"current_page": 1}
        )
    
    def search_start(self, response):
        for keyword in self.keywords:
            yield JsonRequest(
                url="https://api.thepaper.cn/search/web/news",
                headers=self.headers,
                data={
                    "word": keyword,
                    "orderType": 1,
                    "pageNum": 1,
                    "pageSize": 100,
                    "searchType": 1
                },
                callback=self.parse_search_list,
                meta={"keyword": keyword, "current_page": 1}
            )
    
    def parse_search_list(self, response: JsonResponse):
        data = response.json()
        data_obj = data.get("data", {})
        
        for item in data_obj.get("list", []):
            yield scrapy.Request(
                url=f"https://www.thepaper.cn/newsDetail_forward_{item.get('contId')}",
                callback=self.parse_detail,
                meta={
                    "section": "关键词搜索"
                }
            )
        
        keyword = response.meta.get("keyword")
        current_page = response.meta.get("current_page", 1)
        has_next = data_obj.get("hasNext", False)
        
        should_continue = False
        if self.page is None or self.page <= 0:
            should_continue = has_next
        else:
            should_continue = current_page < self.page
        
        if should_continue:
            next_page = current_page + 1
            yield JsonRequest(
                url="https://api.thepaper.cn/search/web/news",
                headers=self.headers,
                data={
                    "word": keyword,
                    "orderType": 1,
                    "pageNum": next_page,
                    "pageSize": 100,
                    "searchType": 1
                },
                callback=self.parse_search_list,
                meta={
                    "keyword": keyword,
                    "current_page": next_page,
                    "section": "关键词搜索"
                }
            )
    
    def parse_default_list(self, response: JsonResponse):
        data = response.json()
        data_obj = data.get("data", {})
        
        for item in data_obj.get("list", []):
            yield scrapy.Request(
                url=f"https://www.thepaper.cn/newsDetail_forward_{item.get('contId')}",
                callback=self.parse_detail,
                meta={
                    "section": "要闻"
                }
            )
        
        current_page = response.meta.get("current_page", 1)
        has_next = data_obj.get("hasNext", False)
        start_time = data_obj.get("startTime")
        
        should_continue = False
        if self.page is None or self.page <= 0:
            should_continue = has_next
        else:
            should_continue = has_next and current_page < self.page
        
        if should_continue and start_time is not None:
            next_page = current_page + 1
            yield JsonRequest(
                url="https://api.thepaper.cn/contentapi/nodeCont/getByChannelId",
                headers=self.headers,
                data={
                    "channelId": "",
                    "excludeContIds": [],
                    "listRecommendIds": [],
                    "pageNum": next_page,
                    "pageSize": 50,
                    "startTime": str(start_time)
                },
                callback=self.parse_default_list,
                meta={"current_page": next_page}
            )

    def parse_detail(self, response: Response):
        item = CSIArticlesItem()
        data_str = response.xpath('//script[@id="__NEXT_DATA__"]/text()').get()
        if not data_str:
            return
        data_json = json.loads(data_str)
        detail_data = data_json.get("props", {}).get("pageProps", {}).get("detailData")
        content_detail = detail_data.get("contentDetail", {})

        # uuid = source_id + str(last_edit_at) + raw_content
        source_id = data_json.get("props", {}).get("pageProps", {}).get("contId")
        last_edit_at = content_detail.get("updateTime")
        if last_edit_at:
            last_edit_at = datetime.datetime.fromtimestamp(int(last_edit_at) / 1000).strftime('%Y-%m-%d %H:%M:%S')
        raw_content = content_detail.get("content")
        uuid = generate_uuid("article" + source_id + str(last_edit_at) + raw_content)

        tags = []
        for t in content_detail.get("tagList", []):
            tags.append(t.get("tag"))

        publish_at = content_detail.get("publishTime")
        if publish_at:
            publish_at = datetime.datetime.fromtimestamp(int(publish_at) / 1000).strftime('%Y-%m-%d %H:%M:%S')

        item["uuid"] = uuid
        item["source_id"] = source_id
        item["data_version"] = 1
        item["entity_type"] = "article"
        item["url"] = response.url
        item["tags"] = tags
        item["platform"] = "澎湃新闻"
        item["section"] = response.meta.get("section")
        item["spider_name"] = self.name
        item["crawled_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        item["publish_at"] = publish_at
        item["last_edit_at"] = last_edit_at
        item["author_name"] =",".join((content_detail.get("author") or "").replace("/", "、").replace(" ", "、").split("、"))
        item["nsfw"] = False
        item["aigc"] = False
        item["title"] = content_detail.get("name")
        item["raw_content"] = raw_content
        item["cover_image"] = content_detail.get("pic")
        # 点赞无法直接从返回数据中获取，先不管
        item["likes"] = -1

        yield item
        