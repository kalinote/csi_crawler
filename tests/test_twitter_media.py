"""验证贴文采集的正式平台名称、媒体直链和原始数据保留。"""

import json
import unittest
from copy import deepcopy

from scrapy import Request
from scrapy.http import TextResponse

from csi_crawlers.spiders.twitter import TwitterSpider


class TwitterMediaTests(unittest.TestCase):
    """使用本地响应验证两种采集入口，不发送平台请求。"""

    def setUp(self):
        """准备同一贴文的图片、视频和备用清晰度。"""
        self.source = {
            "__typename": "Tweet", "id_str": "1234567890123456789", "text": "完整正文",
            "created_at": "2026-10-16T08:00:00Z", "user": {"screen_name": "sample"},
            "extended_entities": {"media": [
                {"id_str": "image-1", "type": "photo", "media_url_https": "https://pbs.twimg.com/photo.jpg", "original_info": {"width": 1200, "height": 800}},
                {"id_str": "video-1", "type": "video", "media_url_https": "https://pbs.twimg.com/poster.jpg", "video_info": {"variants": [
                    {"content_type": "application/x-mpegURL", "url": "https://video.twimg.com/stream.m3u8"},
                    {"content_type": "video/mp4", "bitrate": 256000, "url": "https://video.twimg.com/low.mp4"},
                    {"content_type": "video/mp4", "bitrate": 832000, "url": "https://video.twimg.com/high.mp4?signature=keep"},
                ]}},
            ]},
        }

    def test_link_and_keyword_parsing_emit_the_same_media_contract(self):
        """两种真实解析入口都输出正式平台名称和归档所需媒体清单。"""
        source = deepcopy(self.source)
        legacy = {**source, "full_text": source["text"]}
        raw_tweet = {"rest_id": source["id_str"], "legacy": legacy}
        search = {"data": {"search_by_raw_query": {"search_timeline": {"timeline": {"instructions": [
            {"entries": [{"content": {"itemContent": {"tweet_results": {"result": raw_tweet}}}}]},
        ]}}}}}
        for mode in ("default", "keyword"):
            with self.subTest(mode=mode):
                if mode == "default":
                    spider = TwitterSpider(tweet_ids=source["id_str"])
                    payload, meta, callback = source, {"source_id": source["id_str"]}, spider.parse_detail
                else:
                    spider = TwitterSpider(crawler_type="keyword", keywords="正文", platform_cookies=json.dumps({"auth_token": "local-placeholder", "ct0": "local-placeholder"}))
                    payload, meta, callback = search, {"keyword": "正文", "current_page": 1}, spider.parse_search_list
                response = TextResponse("https://x.com/local", request=Request("https://x.com/local", meta=meta), body=json.dumps(payload).encode(), encoding="utf-8")
                items = list(callback(response))
                self.assertEqual(len(items), 1)
                item = items[0]
                self.assertEqual(item["platform"], "Twitter")
                self.assertEqual(item["spider_name"], "twitter")
                self.assertEqual(item["clean_content"], "完整正文")
                self.assertEqual([media["type"] for media in item["media_resources"]], ["image", "video", "image"])
                self.assertEqual(item["media_resources"][1]["source_url"], "https://video.twimg.com/high.mp4?signature=keep")
                self.assertEqual(item["media_resources"][2]["role"], "poster")
                self.assertEqual(item["media_resources"][2]["media_id"], item["media_resources"][1]["media_id"])
                self.assertEqual(item["files_urls"], [media["source_url"] for media in item["media_resources"]])
                self.assertEqual(json.loads(item["raw_content"]), source if mode == "default" else raw_tweet)
                self.assertNotIn("status", item["media_resources"][0])
        self.assertEqual(self.source, source)

    def test_public_media_details_and_empty_media(self):
        """公开嵌入媒体和无媒体贴文都遵守相同清单契约。"""
        spider = TwitterSpider(tweet_ids=self.source["id_str"])
        source = {**self.source, "extended_entities": None, "mediaDetails": [{"type": "photo", "media_url_https": "https://pbs.twimg.com/image.jpg"}]}
        item = spider.build_post(source, source, "__default__")
        self.assertEqual(len(item["media_resources"]), 1)
        source["mediaDetails"] = []
        item = spider.build_post(source, source, "__default__")
        self.assertEqual(item["media_resources"], [])
        self.assertEqual(item["files_urls"], [])


if __name__ == "__main__":
    unittest.main()
