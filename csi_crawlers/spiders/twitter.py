import json
import re
from datetime import datetime, timedelta, timezone
from html import unescape
from http.cookies import CookieError, SimpleCookie
from urllib.parse import urlencode, urlsplit

import scrapy
from scrapy.exceptions import CloseSpider
from scrapy.http import JsonRequest

from csi_crawlers.items import CSIPostItem
from csi_crawlers.spiders.base import BaseSpider
from csi_crawlers.utils import generate_uuid, safe_int


class TwitterSpider(BaseSpider):
    """按链接采集公开推文，或使用网页登录态搜索关键词。"""

    name = "twitter"
    allowed_domains = ["x.com", "twitter.com", "cdn.syndication.twimg.com"]
    custom_settings = {
        "DOWNLOAD_TIMEOUT": 30,
        "COOKIES_ENABLED": True,
        "COOKIES_DEBUG": False,
    }
    default_headers = {
        "accept": "application/json",
        "accept-language": "en-US,en;q=0.9",
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/143.0.0.0 Safari/537.36"
        ),
    }

    # 来自 X 网页客户端的公共标识，与账号 Cookie、开发者 API 凭证无关。
    web_bearer = (
        "Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D"
        "1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
    )
    # 2026-10-09 网页搜索请求；接口变更时可通过同名爬虫参数覆盖。
    search_query_id = "ph2fARFabkwfxqmSKQ1OPw"
    search_features = {
        "rweb_video_screen_enabled": False,
        "rweb_cashtags_enabled": True,
        "profile_label_improvements_pcf_label_in_post_enabled": True,
        "responsive_web_profile_redirect_enabled": True,
        "rweb_tipjar_consumption_enabled": False,
        "verified_phone_label_enabled": False,
        "creator_subscriptions_tweet_preview_api_enabled": True,
        "responsive_web_graphql_timeline_navigation_enabled": True,
        "premium_content_api_read_enabled": False,
        "communities_web_enable_tweet_community_results_fetch": True,
        "c9s_tweet_anatomy_moderator_badge_enabled": True,
        "responsive_web_grok_analyze_button_fetch_trends_enabled": False,
        "responsive_web_grok_analyze_post_followups_enabled": True,
        "rweb_cashtags_composer_attachment_enabled": True,
        "responsive_web_jetfuel_frame": True,
        "rweb_sports_post_context_enabled": True,
        "responsive_web_grok_share_attachment_enabled": True,
        "responsive_web_grok_annotations_enabled": True,
        "articles_preview_enabled": True,
        "responsive_web_edit_tweet_api_enabled": True,
        "rweb_conversational_replies_downvote_enabled": False,
        "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
        "view_counts_everywhere_api_enabled": True,
        "longform_notetweets_consumption_enabled": True,
        "responsive_web_twitter_article_tweet_consumption_enabled": True,
        "content_disclosure_indicator_enabled": True,
        "content_disclosure_ai_generated_indicator_enabled": True,
        "responsive_web_grok_show_grok_translated_post": True,
        "responsive_web_grok_analysis_button_from_backend": True,
        "post_ctas_fetch_enabled": False,
        "freedom_of_speech_not_reach_fetch_enabled": True,
        "standardized_nudges_misinfo": True,
        "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
        "longform_notetweets_rich_text_read_enabled": True,
        "longform_notetweets_inline_media_enabled": False,
        "responsive_web_nested_quote_preview_enabled": True,
        "responsive_web_grok_image_annotation_enabled": True,
        "responsive_web_grok_imagine_annotation_enabled": True,
        "responsive_web_grok_community_note_auto_translation_is_enabled": True,
        "responsive_web_enhance_cards_enabled": False,
    }

    def __init__(
        self, tweet_urls=None, tweet_ids=None, search_query_id=None,
        search_features=None, search_product="Latest", *args, **kwargs,
    ):
        """校验采集入口，并为关键词模式准备外部登录态。

        Args:
            tweet_urls: 推文链接，多个链接使用逗号分隔，也可传入列表。
            tweet_ids: 推文 ID，多个 ID 使用逗号分隔，也可传入列表。
            search_query_id: 网页 SearchTimeline 接口标识，可在接口更新后覆盖。
            search_features: 网页功能开关的字典或 JSON 字符串，覆盖默认开关。
            search_product: Latest 按最新搜索，Top 按热门搜索。
            *args: 传给基础爬虫的位置参数。
            **kwargs: 传给基础爬虫的采集与平台配置。

        Raises:
            ValueError: 目标、登录态或接口参数无效。
        """
        if isinstance(kwargs.get("platform_headers"), dict):
            kwargs["platform_headers"] = json.dumps(kwargs["platform_headers"])
        super().__init__(*args, **kwargs)
        if self.crawler_type not in {"default", "keyword"}:
            raise ValueError("twitter 仅支持 default 和 keyword 采集方式")
        if self.start_time is not None and self.end_time is not None:
            if self.start_time > self.end_time:
                raise ValueError("采集开始时间不能晚于结束时间")
        if not isinstance(self.platform_headers, dict) or any(
            not isinstance(k, str) or not isinstance(v, str)
            for k, v in self.platform_headers.items()
        ):
            raise ValueError("twitter headers 必须为字符串键值对象")
        # 请求头名称不区分大小写，用户提供的字段优先于默认值。
        self.platform_headers = {
            **self.default_headers,
            **{k.lower(): v for k, v in self.platform_headers.items()},
        }

        if self.crawler_type == "keyword":
            if not self.keywords or any(not isinstance(k, str) or not k.strip() for k in self.keywords):
                raise ValueError("关键词不能为空")
            self.keywords = list(dict.fromkeys(k.strip() for k in self.keywords))
            if search_product not in {"Latest", "Top"}:
                raise ValueError("search_product 必须为 Latest 或 Top")
            self.search_product = search_product
            if search_query_id is not None:
                if not isinstance(search_query_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", search_query_id):
                    raise ValueError("search_query_id 格式无效")
                self.search_query_id = search_query_id
            if isinstance(search_features, str):
                try:
                    search_features = json.loads(search_features)
                except ValueError as exc:
                    raise ValueError("search_features 必须为 JSON 对象") from exc
            if search_features is not None and (
                not isinstance(search_features, dict)
                or any(not isinstance(k, str) or not isinstance(v, bool) for k, v in search_features.items())
            ):
                raise ValueError("search_features 必须为布尔值组成的对象")
            self.search_features = {**self.search_features, **(search_features or {})}
            self.search_headers = dict(self.platform_headers)
            cookie_header = self.search_headers.pop("cookie", "")
            cookies = self.platform_cookies
            if isinstance(cookies, str):
                cookie_header = "; ".join(filter(None, (cookie_header, cookies)))
                cookies = None
            self.search_cookies = {}
            # 浏览器 Cookie 中可能包含未转义的 JSON，逐项解析避免丢失后续登录字段。
            for part in cookie_header.split(";"):
                if not part.strip():
                    continue
                key, separator, value = part.strip().partition("=")
                if not separator or not re.fullmatch(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+", key):
                    raise ValueError("twitter Cookie 字符串格式无效")
                parsed = SimpleCookie()
                try:
                    parsed.load(part.strip())
                except CookieError:
                    pass
                self.search_cookies[key] = parsed[key].value if key in parsed else value
            if isinstance(cookies, dict):
                self.search_cookies.update(cookies)
            elif cookies is not None:
                raise ValueError("twitter cookies 必须为键值对象或 Cookie 字符串")
            if any(
                not isinstance(k, str) or not isinstance(v, str) or "\r" in v or "\n" in v
                for k, v in self.search_cookies.items()
            ):
                raise ValueError("twitter Cookie 必须为合法的字符串键值对象")
            if not all(self.search_cookies.get(k, "").strip() for k in ("auth_token", "ct0")):
                raise ValueError("关键词采集需要在 twitter cookies 中提供 auth_token 和 ct0")
            self.search_headers = {
                "content-type": "application/json",
                "origin": "https://x.com",
                "authorization": self.web_bearer,
                "x-twitter-active-user": "yes",
                "x-twitter-auth-type": "OAuth2Session",
                "x-twitter-client-language": "en",
                **self.search_headers,
            }
            # CSRF 必须与当前 Cookie 一致，不能使用外部请求头中的旧值。
            self.search_csrf_tokens = {keyword: self.search_cookies["ct0"] for keyword in self.keywords}
            self.seen_tweet_ids = set()
            self.search_cursors = {keyword: set() for keyword in self.keywords}
            return

        self.tweet_ids = []
        for value in (tweet_urls, tweet_ids):
            if value is None:
                continue
            targets = value.split(",") if isinstance(value, str) else value
            if not isinstance(targets, (list, tuple)):
                targets = [targets]
            for target in targets:
                target = str(target).strip()
                if not target:
                    continue
                source_id = target
                if not re.fullmatch(r"[1-9][0-9]{0,39}", source_id):
                    parsed = urlsplit(target)
                    match = re.fullmatch(
                        r"/(?:[A-Za-z0-9_]+|i/web)/status/([1-9][0-9]{0,39})"
                        r"(?:/(?:photo|video)/[0-9]+)?/?",
                        parsed.path,
                    )
                    if (
                        parsed.scheme not in {"http", "https"}
                        or parsed.hostname not in {
                            "x.com", "www.x.com", "mobile.x.com",
                            "twitter.com", "www.twitter.com", "mobile.twitter.com",
                        }
                        or not match
                    ):
                        raise ValueError("采集目标必须为有效的 X/Twitter 推文链接或数字 ID")
                    source_id = match.group(1)
                if source_id not in self.tweet_ids:
                    self.tweet_ids.append(source_id)
        if not self.tweet_ids:
            raise ValueError("请通过 tweet_urls 或 tweet_ids 指定要采集的推文")

    def default_start(self, response):
        """为每个推文 ID 请求公开嵌入数据。"""
        for source_id in self.tweet_ids:
            query = urlencode({"id": source_id, "lang": "en", "token": "1"})
            yield scrapy.Request(
                f"https://cdn.syndication.twimg.com/tweet-result?{query}",
                callback=self.parse_detail,
                errback=self.on_request_error,
                headers={
                    "referer": "https://x.com/",
                    **{
                        k: v for k, v in self.platform_headers.items()
                        if k != "cookie"
                    },
                },
                meta={
                    "source_id": source_id,
                    "handle_httpstatus_all": True,
                    "dont_merge_cookies": True,
                },
            )

    def search_start(self, response):
        """为每个关键词启动独立的搜索分页。"""
        for keyword in self.keywords:
            yield self.search_request(keyword)

    def search_request(self, keyword, current_page=1, cursor=None):
        """构造携带网页登录态的搜索请求。

        Args:
            keyword: 当前关键词，也可以包含 X 搜索操作符。
            current_page: 当前关键词的页码，从 1 开始。
            cursor: 上一页返回的底部游标。

        Returns:
            scrapy.Request: 使用独立 Cookie 容器的网页搜索请求。
        """
        query = keyword
        if self.start_time is not None:
            start_date = datetime.fromtimestamp(self.start_time, timezone.utc).date()
            query += f" since:{start_date.isoformat()}"
        if self.end_time is not None:
            end_date = datetime.fromtimestamp(self.end_time, timezone.utc).date() + timedelta(days=1)
            query += f" until:{end_date.isoformat()}"
        variables = {
            "rawQuery": query,
            "count": 20,
            "querySource": "typed_query",
            "product": self.search_product,
            "withGrokTranslatedBio": False,
            "withQuickPromoteEligibilityTweetFields": False,
        }
        if cursor:
            variables["cursor"] = cursor
        # SearchTimeline 是只读查询；当前接口对脚本 GET 返回 404，POST 可正常读取。
        return JsonRequest(
            f"https://x.com/i/api/graphql/{self.search_query_id}/SearchTimeline",
            data={"variables": variables, "features": self.search_features, "queryId": self.search_query_id},
            callback=self.parse_search_list,
            errback=self.on_request_error,
            headers={
                "referer": "https://x.com/search?" + urlencode({"q": keyword, "f": "live" if self.search_product == "Latest" else "top"}),
                **self.search_headers,
                "x-csrf-token": self.search_csrf_tokens[keyword],
            },
            cookies=self.search_cookies if cursor is None else {},
            meta={
                "keyword": keyword,
                "current_page": current_page,
                "cookiejar": ("twitter_search", keyword),
                "handle_httpstatus_all": True,
                "dont_redirect": True,
                "dont_retry": True,
            },
        )

    def parse_search_list(self, response):
        """检查登录态并解析关键词搜索结果，按游标继续翻页。

        Args:
            response: SearchTimeline 的 JSON 响应。

        Yields:
            CSIPostItem | scrapy.Request: 去重后的贴文或下一页请求。

        Raises:
            CloseSpider: 登录失效、限流、访问受限或接口结构异常。
        """
        if response.status == 429:
            raise CloseSpider("twitter 搜索已限流，请稍后重试")
        if response.status in {301, 302, 303, 307, 308, 401}:
            raise CloseSpider("twitter 登录态失效或被重定向，请更新 Cookie")
        if response.status == 403:
            raise CloseSpider("twitter 搜索访问受限，请检查账号验证状态、Cookie 和请求头")
        if response.status == 404:
            raise CloseSpider("twitter 搜索接口不可用，请检查 search_query_id 是否已更新")
        if response.status != 200:
            raise CloseSpider(f"twitter 搜索接口请求失败，HTTP 状态码：{response.status}")
        try:
            data = response.json()
        except ValueError as exc:
            raise CloseSpider("twitter 搜索未返回有效 JSON，请检查登录态或验证页面") from exc
        if not isinstance(data, dict):
            raise CloseSpider("twitter 搜索接口数据格式异常")
        if data.get("errors"):
            codes = {str(e.get("code")) for e in data["errors"] if isinstance(e, dict)}
            if codes & {"32", "89", "215"}:
                raise CloseSpider("twitter 登录态失效，请更新 Cookie")
            if "88" in codes:
                raise CloseSpider("twitter 搜索已限流，请稍后重试")
            if "326" in codes:
                raise CloseSpider("twitter 账号需要验证，请先在网页完成验证")
            raise CloseSpider("twitter 搜索接口返回错误，请检查 Cookie、请求头及搜索接口参数")
        try:
            instructions = data["data"]["search_by_raw_query"]["search_timeline"]["timeline"]["instructions"]
        except (KeyError, TypeError) as exc:
            raise CloseSpider("twitter 搜索结果结构异常，不能当作无搜索结果") from exc
        if not isinstance(instructions, list):
            raise CloseSpider("twitter 搜索时间线格式异常")

        for value in response.headers.getlist("Set-Cookie"):
            updated = SimpleCookie()
            try:
                updated.load(value.decode("latin-1"))
            except CookieError:
                continue
            if "ct0" in updated:
                self.search_csrf_tokens[response.meta["keyword"]] = updated["ct0"].value

        entries = []
        ended = False
        for instruction in instructions:
            if not isinstance(instruction, dict):
                raise CloseSpider("twitter 搜索时间线指令格式异常")
            added = instruction.get("entries") or []
            if not isinstance(added, list):
                raise CloseSpider("twitter 搜索时间线条目格式异常")
            entries.extend(added)
            if instruction.get("entry"):
                entries.append(instruction["entry"])
            if instruction.get("type") == "TimelineTerminateTimeline" and instruction.get("direction") == "Bottom":
                ended = True
        cursor = None
        tweet_count = 0
        for entry in entries:
            if not isinstance(entry, dict):
                raise CloseSpider("twitter 搜索时间线条目格式异常")
            content = entry.get("content") or {}
            if not isinstance(content, dict):
                raise CloseSpider("twitter 搜索条目内容格式异常")
            if content.get("cursorType") == "Bottom":
                cursor = content.get("value")
            if content.get("promotedMetadata"):
                continue
            contents = [content.get("itemContent") or {}]
            modules = content.get("items") or []
            if not isinstance(modules, list):
                raise CloseSpider("twitter 搜索模块格式异常")
            for module in modules:
                if not isinstance(module, dict) or not isinstance(module.get("item"), dict):
                    raise CloseSpider("twitter 搜索模块条目格式异常")
                contents.append(module["item"].get("itemContent") or {})
            for item_content in contents:
                if not isinstance(item_content, dict):
                    raise CloseSpider("twitter 搜索推文条目格式异常")
                if item_content.get("promotedMetadata"):
                    continue
                results = item_content.get("tweet_results") or {}
                if not isinstance(results, dict):
                    raise CloseSpider("twitter 搜索推文结果格式异常")
                tweet = results.get("result")
                if not tweet:
                    continue
                if not isinstance(tweet, dict):
                    raise CloseSpider("twitter 搜索推文格式异常")
                if tweet.get("__typename") == "TweetWithVisibilityResults":
                    tweet = tweet.get("tweet") or {}
                if not isinstance(tweet, dict):
                    raise CloseSpider("twitter 搜索推文格式异常")
                if tweet.get("__typename") in {"TweetTombstone", "TweetUnavailable"}:
                    continue
                if not isinstance(tweet.get("legacy"), dict):
                    raise CloseSpider("twitter 搜索结果缺少推文正文结构")
                tweet_count += 1
                legacy = tweet["legacy"]
                source_id = tweet.get("rest_id") or legacy.get("id_str")
                if not isinstance(source_id, str):
                    raise CloseSpider("twitter 搜索结果缺少推文 ID")
                if source_id in self.seen_tweet_ids:
                    continue
                note = ((tweet.get("note_tweet") or {}).get("note_tweet_results") or {}).get("result") or {}
                text = note.get("text") or legacy.get("full_text")
                if (tweet.get("note_tweet") or legacy.get("truncated")) and not note.get("text"):
                    raise CloseSpider("twitter 搜索结果未提供长推文完整正文")
                user = ((tweet.get("core") or {}).get("user_results") or {}).get("result") or {}
                user_core = user.get("core") or user.get("legacy") or {}
                repost = (legacy.get("retweeted_status_result") or {}).get("result") or {}
                parent_id = legacy.get("in_reply_to_status_id_str")
                quoted_id = legacy.get("quoted_status_id_str") or repost.get("rest_id")
                normalized = {
                    **legacy,
                    "id_str": source_id,
                    "text": text,
                    "user": {
                        "id_str": user.get("rest_id") or legacy.get("user_id_str"),
                        "name": user_core.get("name"),
                        "screen_name": user_core.get("screen_name"),
                    },
                    "entities": note.get("entity_set") or legacy.get("entities") or {},
                    "conversation_count": legacy.get("reply_count"),
                    "in_reply_to_status_id_str": parent_id,
                    "quoted_tweet": {"id_str": quoted_id} if quoted_id else None,
                }
                item = self.build_post(normalized, tweet, "关键词搜索")
                if item is not None:
                    self.seen_tweet_ids.add(source_id)
                    yield item

        keyword = response.meta["keyword"]
        current_page = response.meta["current_page"]
        if ended or not tweet_count or not isinstance(cursor, str) or not cursor:
            return
        if self.page is not None and self.page > 0 and current_page >= self.page:
            return
        if cursor in self.search_cursors[keyword]:
            self.logger.warning("关键词 %s 返回重复游标，已停止翻页", keyword)
            return
        self.search_cursors[keyword].add(cursor)
        yield self.search_request(keyword, current_page + 1, cursor)

    def parse_detail(self, response):
        """解析推文正文与基础元数据，拒绝不可用或不完整的内容。

        Args:
            response: 公开嵌入接口的 JSON 响应。

        Yields:
            CSIPostItem: 满足时间范围的推文及其原始接口数据。

        Raises:
            CloseSpider: 请求失败、数据格式异常或正文不完整。
        """
        requested_id = response.meta["source_id"]
        if response.status != 200:
            self.logger.error("推文 %s 请求失败，HTTP 状态码：%s", requested_id, response.status)
            raise CloseSpider("推文接口请求失败")
        try:
            data = response.json()
        except ValueError as exc:
            raise CloseSpider("推文接口未返回有效的 JSON 数据") from exc
        if not isinstance(data, dict) or data.get("__typename") != "Tweet":
            raise CloseSpider("推文不存在、不可公开访问或接口数据异常")

        source_id = data.get("id_str")
        text = data.get("text")
        if not isinstance(source_id, str) or source_id != requested_id:
            raise CloseSpider("接口返回的推文 ID 与采集目标不一致")
        if not isinstance(text, str) or not text.strip():
            raise CloseSpider("推文接口未返回正文")
        # 嵌入接口的长推文通常只有摘要，不能当作完整正文输出。
        if data.get("note_tweet"):
            raise CloseSpider("公开嵌入接口未提供长推文的完整正文")

        item = self.build_post(data, data, "__default__")
        if item is not None:
            yield item

    def build_post(self, data, raw_data, section):
        """将嵌入数据或搜索结果统一转换为贴文。

        Args:
            data: 已统一字段名的贴文数据。
            raw_data: 原始接口中的完整贴文对象。
            section: 默认采集或关键词搜索来源。

        Returns:
            CSIPostItem | None: 时间范围内的完整贴文，否则返回 None。

        Raises:
            CloseSpider: 贴文标识、正文或发布时间无效。
        """
        source_id = data.get("id_str")
        text = data.get("text")
        if not isinstance(source_id, str) or not re.fullmatch(r"[1-9][0-9]{0,39}", source_id):
            raise CloseSpider("推文 ID 缺失或格式异常")
        if not isinstance(text, str) or not text.strip():
            raise CloseSpider("推文接口未返回正文")
        try:
            try:
                published = datetime.fromisoformat(data["created_at"].replace("Z", "+00:00"))
            except ValueError:
                published = datetime.strptime(data["created_at"], "%a %b %d %H:%M:%S %z %Y")
            if published.tzinfo is None:
                published = published.replace(tzinfo=timezone.utc)
        except (KeyError, AttributeError, TypeError, ValueError) as exc:
            raise CloseSpider("推文发布时间缺失或格式异常") from exc
        timestamp = published.timestamp()
        if self.start_time is not None and timestamp < self.start_time:
            return
        if self.end_time is not None and timestamp > self.end_time:
            return

        user = data.get("user") or {}
        entities = data.get("entities") or {}
        parent_id = data.get("in_reply_to_status_id_str")
        post_type = "reply" if parent_id else "original"
        if not parent_id and data.get("quoted_tweet"):
            post_type = "repost"
            parent_id = data["quoted_tweet"].get("id_str")

        raw_content = json.dumps(raw_data, ensure_ascii=False, sort_keys=True)
        last_edit_at = None
        item = CSIPostItem()
        item["uuid"] = generate_uuid("post" + source_id + str(last_edit_at) + raw_content)
        item["source_id"] = source_id
        item["data_version"] = 1
        item["entity_type"] = "post"
        screen_name = user.get("screen_name") or "i/web"
        item["url"] = f"https://x.com/{screen_name}/status/{source_id}"
        item["platform"] = "twitter"
        item["section"] = section
        item["spider_name"] = self.name
        item["crawled_at"] = datetime.now(timezone.utc).isoformat()
        item["publish_at"] = published.astimezone(timezone.utc).isoformat()
        item["last_edit_at"] = last_edit_at
        item["author_id"] = user.get("id_str")
        item["author_name"] = user.get("name")
        item["raw_content"] = raw_content
        item["clean_content"] = unescape(text)
        item["post_type"] = post_type
        if parent_id:
            item["parent_id"] = str(parent_id)
        item["tags"] = [tag["text"] for tag in entities.get("hashtags", []) if tag.get("text")]
        item["mentions"] = [
            mention["id_str"]
            for mention in entities.get("user_mentions", [])
            if mention.get("id_str")
        ]
        item["nsfw"] = bool(data.get("possibly_sensitive", False))
        item["aigc"] = False
        item["metrics"] = {}
        for field, source_field in (
            ("likes", "favorite_count"),
            ("comments", "conversation_count"),
            ("shares", "retweet_count"),
        ):
            count = safe_int(data.get(source_field))
            item["metrics"][field] = count if count is not None else -1
        return item

    def on_request_error(self, failure):
        """网络请求失败时终止采集并保留错误信息。"""
        self.logger.error("推文网络请求失败：%s", failure.getErrorMessage())
        raise CloseSpider("推文网络请求失败")
