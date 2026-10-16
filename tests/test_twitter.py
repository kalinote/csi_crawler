import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import scrapy
from scrapy.crawler import Crawler
from scrapy.downloadermiddlewares.cookies import CookiesMiddleware
from scrapy.exceptions import CloseSpider
from scrapy.http import TextResponse
from scrapy.settings import Settings

from csi_crawlers.items import CSIPostItem
from csi_crawlers.spiders.twitter import TwitterSpider


class TwitterSpiderTests(unittest.TestCase):
    """验证推文入口、正文解析与异常响应处理。"""

    def setUp(self):
        """准备独立的推文样本和请求。"""
        self.spider = TwitterSpider(tweet_ids="1346889436626259968")
        self.request = next(self.spider.default_start(None))
        self.data = {
            "__typename": "Tweet",
            "id_str": "1346889436626259968",
            "text": "测试正文 &amp; 链接\n第二行 #测试",
            "created_at": "2021-01-06T18:40:40.000Z",
            "user": {"id_str": "2244994945", "name": "测试作者", "screen_name": "test_user"},
            "entities": {
                "hashtags": [{"text": "测试"}],
                "user_mentions": [{"id_str": "123", "screen_name": "another_user"}],
            },
            "favorite_count": 0,
            "conversation_count": 2,
            "edit_control": {"editable_until_msecs": "1609960240344"},
        }

    def response(self, data=None, status=200):
        """使用样本创建带有原始请求的 JSON 响应。"""
        return TextResponse(
            self.request.url,
            request=self.request,
            status=status,
            body=json.dumps(self.data if data is None else data, ensure_ascii=False),
            encoding="utf-8",
        )

    def test_urls_and_ids_are_normalized_and_deduplicated(self):
        """不同域名、链接附加参数和直接 ID 指向相同推文时只采集一次。"""
        spider = TwitterSpider(
            tweet_urls=(
                "https://x.com/test/status/1346889436626259968?s=20,"
                "https://twitter.com/test/status/1346889436626259968/photo/1,"
                "https://x.com/i/web/status/1346889436626259968"
            ),
            tweet_ids="1346889436626259968,12345",
        )
        requests = list(spider.default_start(None))
        self.assertEqual(len(requests), 2)
        self.assertEqual(parse_qs(urlsplit(requests[0].url).query)["id"], [self.data["id_str"]])
        self.assertEqual(requests[1].meta["source_id"], "12345")
        self.assertTrue(requests[0].meta["dont_merge_cookies"])

    def test_invalid_targets_are_rejected(self):
        """缺失目标、非平台链接和非推文页面应在发出请求前报错。"""
        for value in (None, "", "0", "abc", "https://example.com/user/status/123", "https://x.com/user"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    TwitterSpider(tweet_urls=value)
        with self.assertRaises(ValueError):
            TwitterSpider(tweet_ids="123", crawler_type="user")
        with self.assertRaises(ValueError):
            TwitterSpider(tweet_ids="123", start_time="2", end_time="1")

    def test_post_content_and_identity(self):
        """正确提取正文、来源和作者，并保留原始数据及未知字段语义。"""
        item = next(self.spider.parse_detail(self.response()))
        self.assertIsInstance(item, CSIPostItem)
        self.assertEqual(item["entity_type"], "post")
        self.assertEqual(item["platform"], "twitter")
        self.assertEqual(item["spider_name"], "twitter")
        self.assertEqual(item["source_id"], self.data["id_str"])
        self.assertEqual(item["author_id"], "2244994945")
        self.assertEqual(item["author_name"], "测试作者")
        self.assertEqual(item["clean_content"], "测试正文 & 链接\n第二行 #测试")
        self.assertEqual(json.loads(item["raw_content"]), self.data)
        self.assertEqual(item["publish_at"], "2021-01-06T18:40:40+00:00")
        self.assertIsNone(item["last_edit_at"])
        self.assertEqual(item["post_type"], "original")
        self.assertEqual(item["tags"], ["测试"])
        self.assertEqual(item["mentions"], ["123"])
        self.assertEqual(item["metrics"], {"likes": 0, "comments": 2, "shares": -1})
        self.assertNotIn("title", item)
        self.assertNotIn("parent_id", item)

    def test_reply_and_quote_relations(self):
        """回复和引用分别保留关联 ID，且回复关系优先。"""
        self.data["quoted_tweet"] = {"id_str": "100"}
        item = next(self.spider.parse_detail(self.response()))
        self.assertEqual((item["post_type"], item["parent_id"]), ("repost", "100"))
        self.data["in_reply_to_status_id_str"] = "200"
        item = next(self.spider.parse_detail(self.response()))
        self.assertEqual((item["post_type"], item["parent_id"]), ("reply", "200"))

    def test_time_filter_uses_utc_and_includes_boundaries(self):
        """时间过滤按真实时间戳比较，并包含起止边界。"""
        timestamp = int(datetime(2021, 1, 6, 18, 40, 40, tzinfo=timezone.utc).timestamp())
        self.spider.start_time = timestamp
        self.spider.end_time = timestamp
        self.assertEqual(len(list(self.spider.parse_detail(self.response()))), 1)
        self.spider.start_time = timestamp + 1
        self.assertEqual(list(self.spider.parse_detail(self.response())), [])
        self.spider.start_time = None
        self.spider.end_time = timestamp - 1
        self.assertEqual(list(self.spider.parse_detail(self.response())), [])

    def test_unavailable_and_incomplete_responses_fail(self):
        """接口异常、目标不符和长推文摘要不能被当作成功采集。"""
        for data in (
            {}, [], {"__typename": "TweetTombstone"},
            {**self.data, "id_str": "123"},
            {**self.data, "text": ""},
            {**self.data, "note_tweet": {"id": "123"}},
            {**self.data, "created_at": "无效时间"},
        ):
            with self.subTest(data=data):
                with self.assertRaises(CloseSpider):
                    list(self.spider.parse_detail(self.response(data)))
        for status in (403, 404, 429, 503):
            with self.subTest(status=status):
                with self.assertRaises(CloseSpider):
                    list(self.spider.parse_detail(self.response(status=status)))
        with self.assertRaises(CloseSpider):
            list(self.spider.parse_detail(TextResponse(
                self.request.url, request=self.request, body="非 JSON", encoding="utf-8",
            )))

    def test_uuid_is_stable_and_changes_with_content(self):
        """相同响应使用相同版本 ID，正文发生变化时生成新版本。"""
        first = next(self.spider.parse_detail(self.response()))
        reordered = dict(reversed(list(self.data.items())))
        second = next(self.spider.parse_detail(self.response(reordered)))
        self.assertEqual(first["uuid"], second["uuid"])
        self.data["text"] = "修改后的正文"
        third = next(self.spider.parse_detail(self.response()))
        self.assertNotEqual(first["uuid"], third["uuid"])


class TwitterKeywordTests(unittest.TestCase):
    """验证外部登录态、真实网页结构、分页终止和失败语义。"""

    def setUp(self):
        """按实际网页响应结构准备不包含真实账号凭证的样本。"""
        self.cookies = {"auth_token": "test-auth-token", "ct0": "test-csrf"}
        self.spider = TwitterSpider(
            crawler_type="keyword", keywords="测试,另一个关键词", page=2,
            platform_cookies=json.dumps(self.cookies),
            platform_headers=json.dumps({"User-Agent": "测试客户端", "x-csrf-token": "旧值"}),
        )
        self.request = next(self.spider.search_start(None))
        self.tweet = {
            "__typename": "Tweet",
            "rest_id": "2108394633822880212",
            "core": {"user_results": {"result": {
                "rest_id": "12345",
                "core": {"name": "测试作者", "screen_name": "test_user"},
            }}},
            "legacy": {
                "id_str": "2108394633822880212",
                "full_text": "关键词正文 &amp; 内容 #测试",
                "created_at": "Fri Oct 09 03:10:27 +0000 2026",
                "favorite_count": 0,
                "reply_count": 2,
                "retweet_count": 3,
                "entities": {
                    "hashtags": [{"text": "测试"}],
                    "user_mentions": [{"id_str": "456"}],
                },
            },
        }
        self.entries = [
            {"entryId": "tweet-2108394633822880212", "content": {
                "itemContent": {"itemType": "TimelineTweet", "tweet_results": {"result": self.tweet}},
            }},
            {"entryId": "cursor-bottom-0", "content": {"cursorType": "Bottom", "value": "下一页游标"}},
        ]
        self.data = {"data": {"search_by_raw_query": {"search_timeline": {"timeline": {
            "instructions": [{"type": "TimelineAddEntries", "entries": self.entries}],
        }}}}}

    def response(self, data=None, status=200, request=None, headers=None):
        """生成携带分页上下文的搜索响应。"""
        request = request or self.request
        return TextResponse(
            request.url, request=request, status=status, headers=headers,
            body=json.dumps(self.data if data is None else data, ensure_ascii=False), encoding="utf-8",
        )

    def test_cookies_are_required_and_accept_external_formats(self):
        """外部字典、JSON 和 Cookie 请求头均可接入，缺少登录态必须失败。"""
        for config in (
            {"platform_cookies": self.cookies},
            {"platform_cookies": json.dumps(self.cookies)},
            {"platform_cookies": "auth_token=test-auth-token; ct0=test-csrf"},
            {"platform_cookies": 'g_state={"i_l":0,"i_e":{"flag":24}}; auth_token=test-auth-token; ct0=test-csrf'},
            {"platform_headers": {"Cookie": "auth_token=test-auth-token; ct0=test-csrf"}},
        ):
            with self.subTest(config=config):
                spider = TwitterSpider(crawler_type="keyword", keywords="测试", **config)
                request = next(spider.search_start(None))
                self.assertEqual(request.cookies["auth_token"], self.cookies["auth_token"])
                self.assertEqual(request.cookies["ct0"], self.cookies["ct0"])
                self.assertNotIn("Cookie", request.headers)
                self.assertEqual(request.headers["x-csrf-token"], b"test-csrf")
                self.assertFalse(request.meta.get("dont_merge_cookies", False))
        for cookies in (None, {}, {"auth_token": "token"}, {"ct0": "csrf"}, {"auth_token": " ", "ct0": "csrf"}, ["token"]):
            with self.subTest(cookies=cookies):
                with self.assertRaises(ValueError):
                    TwitterSpider(crawler_type="keyword", keywords="测试", platform_cookies=cookies)

    def test_search_parameters_and_cookie_isolation(self):
        """关键词去重，支持接口参数覆盖，登录态不进入公开嵌入请求。"""
        spider = TwitterSpider(
            crawler_type="keyword", keywords="测试,测试,第二词", platform_cookies=self.cookies,
            search_product="Top", search_query_id="updated-query", search_features='{"articles_preview_enabled":false}',
        )
        requests = list(spider.search_start(None))
        self.assertEqual(len(requests), 2)
        self.assertTrue(requests[0].url.endswith("/updated-query/SearchTimeline"))
        self.assertEqual(requests[0].method, "POST")
        params = json.loads(requests[0].body)
        self.assertEqual(params["queryId"], "updated-query")
        self.assertEqual(params["variables"]["product"], "Top")
        self.assertFalse(params["features"]["articles_preview_enabled"])
        self.assertNotEqual(requests[0].meta["cookiejar"], requests[1].meta["cookiejar"])
        self.assertTrue(requests[0].meta["dont_retry"])
        self.assertTrue(requests[0].meta["dont_redirect"])
        public = TwitterSpider(tweet_ids="123", platform_cookies=self.cookies)
        public_request = next(public.default_start(None))
        self.assertFalse(public_request.cookies)
        self.assertNotIn("Authorization", public_request.headers)
        self.assertTrue(public_request.meta["dont_merge_cookies"])
        for config in ({"search_product": "Users"}, {"search_query_id": "bad/id"}, {"search_features": "bad-json"}, {"search_features": {"flag": "true"}}):
            with self.subTest(config=config):
                with self.assertRaises(ValueError):
                    TwitterSpider(crawler_type="keyword", keywords="测试", platform_cookies=self.cookies, **config)

    def test_search_body_author_metrics_and_pagination(self):
        """网页搜索结果直接产出完整贴文，下一页保留关键词与页码。"""
        item, request = list(self.spider.parse_search_list(self.response()))
        self.assertIsInstance(item, CSIPostItem)
        self.assertEqual(item["clean_content"], "关键词正文 & 内容 #测试")
        self.assertEqual((item["author_id"], item["author_name"]), ("12345", "测试作者"))
        self.assertEqual(item["url"], "https://x.com/test_user/status/2108394633822880212")
        self.assertEqual(item["publish_at"], "2026-10-09T03:10:27+00:00")
        self.assertEqual(item["metrics"], {"likes": 0, "comments": 2, "shares": 3})
        self.assertEqual(item["section"], "关键词搜索")
        self.assertEqual(json.loads(item["raw_content"]), self.tweet)
        self.assertIsInstance(request, scrapy.Request)
        self.assertEqual(request.meta["current_page"], 2)
        self.assertEqual(request.meta["keyword"], "测试")
        variables = json.loads(request.body)["variables"]
        self.assertEqual(variables["cursor"], "下一页游标")
        self.assertEqual(list(self.spider.parse_search_list(self.response(request=request))), [])

    def test_long_posts_visibility_wrappers_and_legacy_users(self):
        """兼容长推文、可见性包装和旧版作者字段，避免保存摘要。"""
        user = self.tweet["core"]["user_results"]["result"]
        user["legacy"] = user.pop("core")
        self.tweet["note_tweet"] = {"note_tweet_results": {"result": {
            "text": "完整长推文 " * 100,
            "entity_set": {"hashtags": [{"text": "长文"}], "user_mentions": [{"id_str": "789"}]},
        }}}
        self.entries[0]["content"]["itemContent"]["tweet_results"]["result"] = {
            "__typename": "TweetWithVisibilityResults", "tweet": self.tweet,
        }
        item = next(self.spider.parse_search_list(self.response()))
        self.assertEqual(item["clean_content"], "完整长推文 " * 100)
        self.assertEqual(item["author_name"], "测试作者")
        self.assertEqual(item["tags"], ["长文"])
        self.assertEqual(item["mentions"], ["789"])
        self.spider.seen_tweet_ids.clear()
        self.tweet["note_tweet"]["note_tweet_results"]["result"] = {}
        with self.assertRaises(CloseSpider):
            list(self.spider.parse_search_list(self.response()))

    def test_modules_and_relationships(self):
        """模块内贴文仍可解析，回复和引用保留关联推文 ID。"""
        content = self.entries[0]["content"].pop("itemContent")
        self.entries[0]["content"]["items"] = [{"item": {"itemContent": content}}]
        self.tweet["legacy"]["quoted_status_id_str"] = "100"
        item = next(self.spider.parse_search_list(self.response()))
        self.assertEqual((item["post_type"], item["parent_id"]), ("repost", "100"))
        self.spider.seen_tweet_ids.clear()
        self.tweet["legacy"]["in_reply_to_status_id_str"] = "200"
        item = next(self.spider.parse_search_list(self.response()))
        self.assertEqual((item["post_type"], item["parent_id"]), ("reply", "200"))

    def test_page_limits_and_repeated_cursor_stop(self):
        """达到页数、重复游标、终止指令或空结果时结束搜索。"""
        self.spider.page = 1
        self.assertEqual(len(list(self.spider.parse_search_list(self.response()))), 1)
        self.spider.page = 0
        first = list(self.spider.parse_search_list(self.response()))
        self.assertEqual(len(first), 1)
        self.assertIsInstance(first[0], scrapy.Request)
        self.assertEqual(list(self.spider.parse_search_list(self.response(request=first[0]))), [])
        self.spider.search_cursors["测试"].clear()
        instructions = self.data["data"]["search_by_raw_query"]["search_timeline"]["timeline"]["instructions"]
        instructions.append({"type": "TimelineTerminateTimeline", "direction": "Bottom"})
        self.assertEqual(list(self.spider.parse_search_list(self.response())), [])
        instructions.pop()
        self.entries.pop(0)
        self.assertEqual(list(self.spider.parse_search_list(self.response())), [])

    def test_posts_are_deduplicated_across_keywords(self):
        """不同关键词命中同一推文时仅输出一次，但各自可继续翻页。"""
        requests = list(self.spider.search_start(None))
        first = list(self.spider.parse_search_list(self.response(request=requests[0])))
        second = list(self.spider.parse_search_list(self.response(request=requests[1])))
        self.assertEqual(sum(isinstance(value, CSIPostItem) for value in first + second), 1)
        self.assertEqual(sum(isinstance(value, scrapy.Request) for value in first + second), 2)

    def test_time_boundaries_filter_items_without_stopping_pagination(self):
        """时间按秒精确过滤，日期查询覆盖整日，过滤当前页不影响翻页。"""
        timestamp = int(datetime(2026, 10, 9, 3, 10, 27, tzinfo=timezone.utc).timestamp())
        self.spider.start_time = timestamp
        self.spider.end_time = timestamp
        request = next(self.spider.search_start(None))
        query = json.loads(request.body)["variables"]["rawQuery"]
        self.assertEqual(query, "测试 since:2026-10-09 until:2026-10-10")
        self.assertEqual(len(list(self.spider.parse_search_list(self.response()))), 2)
        self.spider.search_cursors["测试"].clear()
        self.spider.seen_tweet_ids.clear()
        self.spider.start_time = timestamp + 1
        output = list(self.spider.parse_search_list(self.response()))
        self.assertEqual(len(output), 1)
        self.assertIsInstance(output[0], scrapy.Request)

    def test_http_and_graphql_failures_close_spider(self):
        """鉴权、限流和结构异常不会被报告为成功但无结果。"""
        for status, reason in ((401, "登录态"), (302, "登录态"), (403, "访问受限"), (404, "search_query_id"), (429, "限流"), (503, "503")):
            with self.subTest(status=status):
                with self.assertRaises(CloseSpider) as error:
                    list(self.spider.parse_search_list(self.response(status=status)))
                self.assertIn(reason, error.exception.reason)
        for code, reason in ((89, "登录态"), (88, "限流"), (326, "验证"), (999, "接口返回错误")):
            with self.subTest(code=code):
                with self.assertRaises(CloseSpider) as error:
                    list(self.spider.parse_search_list(self.response({"errors": [{"code": code}]})))
                self.assertIn(reason, error.exception.reason)
        for data in ({}, [], {"data": None}):
            with self.subTest(data=data):
                with self.assertRaises(CloseSpider):
                    list(self.spider.parse_search_list(self.response(data)))
        with self.assertRaises(CloseSpider):
            list(self.spider.parse_search_list(TextResponse(self.request.url, request=self.request, body=b"<html>login</html>")))
        self.entries[0] = None
        with self.assertRaises(CloseSpider):
            list(self.spider.parse_search_list(self.response()))

    def test_deleted_posts_and_ads_are_skipped(self):
        """跳过不可用贴文和推广内容。"""
        self.entries[0]["content"]["itemContent"]["tweet_results"]["result"] = {"__typename": "TweetTombstone"}
        self.assertEqual(list(self.spider.parse_search_list(self.response())), [])
        self.entries[0]["content"]["itemContent"]["tweet_results"]["result"] = self.tweet
        self.entries[0]["content"]["itemContent"]["promotedMetadata"] = {"advertiser": "测试"}
        self.assertEqual(list(self.spider.parse_search_list(self.response())), [])

    def test_cookie_middleware_sends_and_refreshes_session(self):
        """验证实际 Cookie 中间件携带登录态，并同步更新下一页 CSRF。"""
        crawler = Crawler(TwitterSpider, Settings({"COOKIES_ENABLED": True}))
        crawler.spider = self.spider
        middleware = CookiesMiddleware.from_crawler(crawler)
        with patch("scrapy.downloadermiddlewares.cookies._is_public_domain", return_value=False):
            middleware.process_request(self.request)
            self.assertIn(b"auth_token=test-auth-token", self.request.headers["Cookie"])
            self.assertIn(b"ct0=test-csrf", self.request.headers["Cookie"])
            response = self.response(headers={"Set-Cookie": "ct0=refreshed-csrf; Path=/; Secure"})
            middleware.process_response(self.request, response)
            next_request = list(self.spider.parse_search_list(response))[-1]
            middleware.process_request(next_request)
            self.assertEqual(next_request.headers["x-csrf-token"], b"refreshed-csrf")
            self.assertIn(b"ct0=refreshed-csrf", next_request.headers["Cookie"])
            self.assertIn(b"auth_token=test-auth-token", next_request.headers["Cookie"])
            self.assertFalse(next_request.cookies)
        other = self.spider.search_request("另一个关键词")
        self.assertEqual(other.headers["x-csrf-token"], b"test-csrf")


if __name__ == "__main__":
    unittest.main()
