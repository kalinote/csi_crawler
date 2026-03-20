---
name: article-spider
description: 构建文章/资讯类爬虫时使用。适用于新闻媒体、博客、公众号等以独立文章为内容单元的站点，使用 CSIArticlesItem 存储数据。涵盖 API 与 HTML 两种列表/详情解析模式、字段填充规则及完整代码模板。Use when building a spider for news sites, blogs, media sites, or any site where content is individual articles.
---

# 文章/资讯类（article）爬虫

> 本 skill 专注于 article 类站点的特有模式，需配合 [new-spider](../new-spider/SKILL.md) 使用。BaseSpider 继承、`self.page`/`self.sections`/`self.keywords` 参数、通用翻页逻辑见该 skill。

> **重要**：references 中的代码模板仅作参考，实际编写时必须先审查目标站的真实接口与 HTML 结构，按实际情况实现，不要盲目套用。

## 适用站点特征

- 内容以**独立文章**为单元，每篇有自己的标题、正文、作者、发布时间。
- 典型代表：澎湃新闻、BBC、CNN、公众号、个人博客等。
- 列表页给出文章摘要/链接，详情页包含完整正文。
- 每篇文章对应**一条** `CSIArticlesItem`，结构简单。

## CSIArticlesItem 字段

公共字段（来自 `CSICommonFields`）+ article 扩展字段，仅填充能从页面/接口获取的字段，不能获取的可不赋值或用默认值：

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `uuid` | str | 必填 | `generate_uuid("article" + source_id + str(last_edit_at) + raw_content)` |
| `source_id` | str | 必填 | 平台原始文章 ID |
| `data_version` | int | `1` | 固定为 `1` |
| `entity_type` | str | `"article"` | 固定为 `"article"` |
| `url` | str | 必填 | 文章原始链接 |
| `platform` | str | 必填 | 来源平台名称（如 `"澎湃新闻"`） |
| `section` | str | 必填 | 所属板块，从 `response.meta` 取 |
| `spider_name` | str | 必填 | `self.name` |
| `crawled_at` | str | 必填 | `datetime.now().strftime("%Y-%m-%d %H:%M:%S")` |
| `publish_at` | str | 若能取则填 | 文章发布时间，同格式 |
| `last_edit_at` | str | 若能取则填 | 最后编辑时间；无法区分时与 `publish_at` 相同 |
| `author_id` | str | 若能取则填 | 作者在平台的原始 ID |
| `author_name` | str | 若能取则填 | 作者昵称/署名 |
| `tags` | list | `[]` | 文章标签，平台无标签则填 `[]` |
| `nsfw` | bool | `False` | 是否为不适宜内容 |
| `aigc` | bool | `False` | 是否为 AI 生成内容 |
| `title` | str | 必填 | 文章标题 |
| `raw_content` | str | 必填 | 原始 HTML 或 JSON 正文 |
| `cover_image` | str | 可不填 | 封面图 URL，无法获取可省略 |
| `likes` | int | `-1` | 点赞数，无法获取填 `-1` |

## 解析模式

### API 模式（JSON 接口）

大多数现代新闻 App/站点提供 JSON API：

```
default_start / search_start
  └─ JsonRequest → parse_default_list / parse_search_list
       ├─ 从 data.list 提取 detail_url / id → Request → parse_detail
       └─ 翻页：pageNum / cursor / startTime 参数递增
```

- 列表接口通常返回 `{ data: { list: [...], hasNext: bool } }`，字段名因站而异。
- 详情可能直接在列表数据中内嵌（无需二次请求），也可能需要单独请求详情接口或 HTML 页。

### HTML 模式

传统新闻网站或博客：

```
default_start / search_start
  └─ Request → parse_default_list / parse_search_list
       ├─ XPath/CSS 提取列表中的 href → Request → parse_detail
       └─ 翻页：下一页链接 或 ?page=N 参数
```

### parse_detail 核心逻辑

```python
def parse_detail(self, response):
    source_id = ...               # 从 URL 参数或页面脚本提取
    raw_content = ...             # HTML .get() 或 JSON 字段
    publish_at = ...              # 解析为 "%Y-%m-%d %H:%M:%S"
    last_edit_at = publish_at     # 无编辑时间时与 publish_at 相同

    item = CSIArticlesItem()
    item["uuid"] = generate_uuid("article" + source_id + str(last_edit_at) + raw_content)
    item["source_id"] = source_id
    item["data_version"] = 1
    item["entity_type"] = "article"
    item["url"] = response.url
    item["platform"] = "平台名"
    item["section"] = response.meta.get("section")
    item["spider_name"] = self.name
    item["crawled_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    item["publish_at"] = publish_at
    item["last_edit_at"] = last_edit_at
    item["nsfw"] = False
    item["aigc"] = False
    item["title"] = ...
    item["raw_content"] = raw_content
    # 以下按能否获取决定是否赋值
    # item["author_name"] = ...
    # item["cover_image"] = ...
    # item["likes"] = ...
    yield item
```

## 相关

- 完整代码模板（含 API 列表 + HTML 详情示例）见 [references/article-template.md](references/article-template.md)。
- CSIArticlesItem 公共字段含义见 `new-spider/references/内容存储字段设计(v1).md`，article 扩展字段见 `new-spider/references/文章与资讯(article)存储字段设计.md`。
- `generate_uuid`、时间解析工具等来自 `csi_crawlers.utils`。
