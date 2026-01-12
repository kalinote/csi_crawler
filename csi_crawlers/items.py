import scrapy

class CSICommonFields(scrapy.Item):
    """
    通用字段
    """
    uuid = scrapy.Field()
    source_id = scrapy.Field()
    data_version = scrapy.Field()
    entity_type = scrapy.Field()
    url = scrapy.Field()
    platform = scrapy.Field()
    section = scrapy.Field()
    spider_name = scrapy.Field()
    crawled_at = scrapy.Field()
    publish_at = scrapy.Field()
    last_edit_at = scrapy.Field()
    author_id = scrapy.Field()
    author_name = scrapy.Field()
    nsfw = scrapy.Field()
    aigc = scrapy.Field()

class CSIUserItem(scrapy.Item):
    """
    用户item
    """
    uuid = scrapy.Field()
    user_id = scrapy.Field()
    screen_name = scrapy.Field()
    url = scrapy.Field()
    avatar_url = scrapy.Field()
    platform = scrapy.Field()
    crawled_at = scrapy.Field()
    last_active_at = scrapy.Field()
    following = scrapy.Field()
    follower = scrapy.Field()
    friends = scrapy.Field()
    personal_url = scrapy.Field()
    contacts = scrapy.Field()
    sex = scrapy.Field()
    birthday = scrapy.Field()
    
class CSIForumItem(CSICommonFields):
    """
    论坛item
    """
    topic_id = scrapy.Field()
    parent_id = scrapy.Field()
    floor = scrapy.Field()
    thread_type = scrapy.Field()
    category_tag = scrapy.Field()
    title = scrapy.Field()
    raw_content = scrapy.Field()
    status_flags = scrapy.Field()
    likes = scrapy.Field()
    dislikes = scrapy.Field()
    collections = scrapy.Field()
    comments = scrapy.Field()
    views = scrapy.Field()

class CSIArticlesItem(CSICommonFields):
    """
    文章与资讯item
    """
    title = scrapy.Field()
    clean_content = scrapy.Field()
    raw_content = scrapy.Field()
    translation_content = scrapy.Field()
    safe_raw_content = scrapy.Field()
    cover_image = scrapy.Field()
    likes = scrapy.Field()
