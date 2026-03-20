---
name: new-spider
description: 新建爬虫时使用的通用指南。说明 BaseSpider 继承约束、入口参数、站点类型判断及对应专项 skill 选择。Use when creating a new spider, adding a crawler for a new site, or when the user asks to create a spider.
---

# 新建爬虫通用指南

## 约束

- 所有爬虫必须继承自 `csi_crawlers/spiders/base.py` 的 `BaseSpider`，文件放在同目录下。
- 实现 `default_start(response)` 做默认/按板块采集，实现 `search_start(response)` 做关键词采集。

## BaseSpider 入口与参数

`start()` 根据 `crawler_type` 调用对应入口；无 `start_url` 时 `response` 为 `None`。

构造函数已解析并挂到 `self`：

| 参数 | 说明 |
| --- | --- |
| `crawler_type` | `"default"`（默认/板块）或 `"keyword"`（关键词） |
| `sections` | 板块列表；`"__default__"` 表示默认板块，在 `default_start` 中映射为实际板块名 |
| `keywords` | 关键词列表，`search_start` 中遍历使用 |
| `page` | 页数限制；`None` 或 `<= 0` 表示不限制 |
| `start_time` / `end_time` | 时间范围（时间戳），按需使用 |

## 翻页通用逻辑

适用于所有类型的列表页：

```python
current_page = response.meta.get("current_page", 1)
has_next = ...  # 从接口/页面判断是否有下一页
should_continue = (self.page is None or self.page <= 0) and has_next \
    or (self.page and self.page > 0 and current_page < self.page and has_next)
if should_continue:
    yield ...  # 下一页请求，meta 中传入 current_page + 1
```

## 第一步：判断站点类型，选择对应 skill

拿到目标站后，先判断内容类型，再读取对应 skill：

| 类型 | 判断依据 | Item | 对应 skill |
| --- | --- | --- | --- |
| **article**（文章/资讯） | 内容为独立文章，有标题/正文/作者，新闻媒体、博客、公众号等 | `CSIArticlesItem` | [article-spider](../article-spider/SKILL.md) |
| **forum**（论坛/社区） | 有回复/评论互动，帖子分主贴与回复，Discuz!、Reddit、贴吧等 | `CSIForumItem` | [forum-spider](../forum-spider/SKILL.md) |

> 目前已有 article 和 forum 两类专项 skill，forum 类下已支持 Discuz!，未来可按需在对应 skill 中补充其他论坛框架。

## 字段通用规则

- **实际需填字段由 Item 决定**：仅赋值当前 Item 类中定义的字段。
- **非必填**：只填能从页面/接口获取的字段；数值类取不到填 `-1`，布尔类填 `False`。
- **uuid**：`generate_uuid(entity_type + source_id + str(last_edit_at) + raw_content)`，来自 `csi_crawlers.utils`。
- 字段含义与数据类型以 references 中的字段定义文档为准，仅"采集"来源的字段由爬虫填充。

## 检查清单

- [ ] 继承 `BaseSpider`，文件位于 `csi_crawlers/spiders/`
- [ ] 已根据站点类型读取对应专项 skill
- [ ] 实现 `default_start`（板块采集）和/或 `search_start`（关键词采集）
- [ ] 列表回调中 yield 详情 Request，并按 `self.page` 与 `has_next` 控制翻页
- [ ] `parse_detail` 中 yield 对应 Item，字段以 items.py 为准，能填则填
- [ ] 使用 `.venv` 运行，输出用 `-o` 写入文件

## 相关

- 字段含义与数据类型：[references/内容存储字段设计(v1).md](references/内容存储字段设计(v1).md)、[references/文章与资讯(article)存储字段设计.md](references/文章与资讯(article)存储字段设计.md)、[references/社区与论坛(forum)存储字段设计.md](references/社区与论坛(forum)存储字段设计.md)、[references/社交动态贴文(post)存储字段设计.md](references/社交动态贴文(post)存储字段设计.md)
- BaseSpider 完整定义：项目内 `csi_crawlers/spiders/base.py`
- Item 定义：项目内 `csi_crawlers/items.py`
- Scrapy 项目约定：[../scrapy-development/SKILL.md](../scrapy-development/SKILL.md)
