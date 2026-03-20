---
name: forum-spider
description: 构建论坛/社区类爬虫时使用。适用于有帖子回复互动结构的站点（如 Discuz!、Reddit、贴吧等），使用 CSIForumItem 存储数据，涵盖 thread/comment/featured 三层数据结构、字段填充规则及各论坛类型的专项实现模式。Use when building a spider for any forum, community, or BBS site with post-reply interaction.
---

# Forum 类爬虫

> 本 skill 专注于 forum 类站点的通用模式与各框架的专项实现，需配合 [new-spider](../new-spider/SKILL.md) 使用。BaseSpider 继承、`self.page`/`self.sections`/`self.keywords` 参数、通用翻页逻辑见该 skill。

> **重要**：本 skill 中的代码模式和模板均基于特定站点实现，不同论坛框架及站点的二次开发程度差异很大。**必须先用浏览器实际审查目标站的 DOM 结构与接口**，再参考对应模板编写，不要盲目套用。

## Forum 站点特征

与 article 类最大的区别：内容有**互动层级结构**，一个帖子由多条数据组成，每条数据独立存储为一个 `CSIForumItem`。

## 数据层级（thread_type）

| thread_type | 含义 | floor | parent_id |
| --- | --- | --- | --- |
| `thread` | 主贴（1楼） | `1` | `topic_id`（帖子 tid） |
| `comment` | 普通回复 | 实际楼层号，取不到则 `-1` | 主贴的 `source_id` |
| `featured` | 楼中楼/点评 | 楼中楼内序号（从 `1` 起） | 所属回复的 `source_id` |

- `topic_id`：整个帖子的唯一 ID，同一帖子下所有条目共享。
- `title`：主贴标题；回复与楼中楼通过 `response.meta` 继承，不重新解析。
- `status_flags`：置顶（`stickied`）、精华（`essence`）等，在列表页解析后通过 meta 传入，**仅主贴赋值**，回复/楼中楼填 `[]`。

## 推荐代码模式

### _init_base_item(response, tid, section)

集中初始化所有帖子通用的固定字段，调用后再按 `thread_type` `.update()` 特有字段：

```python
def _init_base_item(self, response, tid, section):
    item = CSIForumItem()
    item["entity_type"] = "forum"
    item["data_version"] = 1
    item["topic_id"] = tid
    item["url"] = response.url
    item["platform"] = "目标站名称"
    item["spider_name"] = self.name
    item["section"] = section
    item["crawled_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    item["nsfw"] = False
    item["aigc"] = False
    for field in ["likes", "dislikes", "collections", "comments", "views"]:
        item[field] = -1
    return item
```

### parse_thread：首页 vs 评论翻页

帖子首页与评论翻页通常共用同一个 callback，需区分处理：

```python
# 首页：主贴容器存在 → 解析主贴，填充 common_data
if first_post_box:
    common_data["title"] = ...
    common_data["category_tag"] = ...
    source_id = ...
else:
    # 翻页：从 meta 恢复上下文
    common_data["title"] = response.meta.get("title", "")
    common_data["category_tag"] = response.meta.get("category_tag", "")
    source_id = response.meta.get("source_id", tid)
```

评论翻页请求的 meta **必须携带**：`source_id`、`title`、`category_tag`、`section`、`status_flags`。

### _parse_featured_comments

将楼中楼/点评封装为独立方法，通过 `common_data` dict 传递共享上下文，避免 `parse_thread` 中重复代码。若目标站无楼中楼功能，删除此调用即可。

---

## Discuz! 专项

Discuz! 是最常见的论坛框架之一，以下为其特有模式。

### 站点特征

- 帖子列表 URL：`forum.php?mod=forumdisplay&fid=<fid>`，`fid` 为板块 ID（整型）。
- 帖子详情 URL：`forum.php?mod=viewthread&tid=<tid>`，`tid` 为帖子唯一 ID。
- 翻页：`<a class="nxt">` 链接，列表页与评论翻页格式相同。
- 搜索：需先 GET 搜索页获取 `formhash`，再 POST 提交（见下方）。
- 反爬：多关键词搜索建议间隔 90 秒；列表/帖子翻页建议 5 秒延迟。

### 搜索流程（formhash 两步）

```
search_start(response)
  └─ GET /forum/search.php?mod=forum  →  post_search(response)
       └─ FormRequest（formhash + srchtxt）×N  →  parse_keyword(response)
```

- `formhash` 取自 `//input[@name='formhash']/@value`。
- 多关键词用 `index * 90` 秒延迟 + `priority=-index` 顺序执行。
- 若目标站搜索为普通 GET 参数，可跳过 `post_search` 直接 yield 搜索请求。

### 常用 XPath 速查

| 位置 | XPath | 说明 |
| --- | --- | --- |
| 帖子列表行 | `//tbody[starts-with(@id, 'normalthread_')]` | 普通帖行，排除置顶等特殊行 |
| 帖子链接 | `.//a[@class='s']/@href` | 列表行内链接 |
| 状态图标 | `.//img[@align='absmiddle']/@src` | 用 `get_flag_name_from_url` 解析 flag 名 |
| 下一页 | `//a[@class='nxt']/@href` | 列表页与帖子页通用 |
| 主贴容器 | `//div[@class='nthread_postbox nthread_firstpostbox']` | 仅帖子首页存在 |
| 普通回复容器 | `//div[@class='nthread_postbox']` | 每页均存在 |
| 楼中楼容器 | `.//div[starts-with(@id, 'comment_')]` | 在各 post_box 内 |
| post source_id | `post_box/@id` → `.split("post_")[-1]` | |
| comment source_id | `container/@id` → `.split("comment_")[-1]` | |
| 作者 uid | `.//div[@class='authi']/a/@href` | 用 `extract_param_from_url(href, "uid")` |
| 作者名 | `.//div[@class='authi']/a/text()` | |
| 楼层号 | `.//strong/a/em/text()` | 取不到时试 `.//strong/a/text()`；若为"樓主"则视为 2 |
| 发帖/回复时间 | `em[starts-with(@id, 'authorposton')]/text()` | 用 `find_datetime_from_str` 解析 |
| 最后编辑时间 | `.//i[@class='pstatus']/text()` | 取不到则与 `publish_at` 相同 |
| 主贴发布时间 | `//span[@class='mr10']/text()` | |
| 分类标签 | `//div[@class='nthread_info cl']/h1/a/font/text()` | |
| 主贴标题 | `//div[@class='nthread_info cl']/h1/span/text()` | |
| 点赞数 | `//span[@id='recommendv_add']/text()` | 用 `safe_int` |
| 收藏数 | `//span[@id='favoritenumber']/text()` | 用 `safe_int` |
| 回复数 | `//div[@class='authi mb5']/span[@class='y']/text()` | 用 `find_int_from_str` |
| 浏览数 | `//div[@class='authi mb5']/span[@class='mr10 y']/text()` | 用 `find_int_from_str` |
| formhash | `//input[@name='formhash']/@value` | 搜索前 GET 页取得 |

### 完整代码模板

见 [references/discuz-template.md](references/discuz-template.md)。

---

## 相关

- CSIForumItem 字段含义与类型见 `new-spider/references/社区与论坛(forum)存储字段设计.md` 及 `new-spider/references/内容存储字段设计(v1).md`。
- 通用工具函数：`find_datetime_from_str`、`find_int_from_str`、`generate_uuid`、`safe_int`、`extract_param_from_url`、`get_flag_name_from_url` 均来自 `csi_crawlers.utils`。
