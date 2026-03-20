# 社区与论坛(forum)存储字段设计
Reddit, 贴吧, Discord

| **字段名** | **类型** | 来源  | **描述与设计理由** |
| --- | --- | --- | --- |
| **topic\_id** | `keyword` | 采集  | 整个帖子的id |
| **parent\_id** | `keyword` | 采集  | **父ID**。该回复直接回复的对象的 ID。用于构建 Reddit 风格的树状评论结构。 |
| **floor** | `integer` | 采集  | **楼层号**。BBS 特有（如 1楼、2楼）。用于按顺序排序展示。主贴通常为 1 或 0。 |
| **thread\_type** | `keyword` | 采集  | 帖子类型，分为thread(主贴，也就是1楼)、comment(评论)、featured(点评，一般附属于主贴或某个恢复，只有少量信息，没有单独的楼层号，也不能被回复) |
| **category\_tag** | `keyword` | 采集  | 帖子内部的分类标签。如 `[求助]`, `[原创]`, `[Discussion]`。 |
| **title** | `text` | 采集  | 主标题，回复贴此字段继承主贴主标题标题。 |
| **files\_urls** | `keyword` (Array) | 采集  | 图片、视频或附件等文件的直接链接列表，用于后续下载和分析。 |
| **status\_flags** | `keyword` (Array) | 采集  | 帖子的特殊状态。比如：锁定、置顶、精华/加精、已解决等。 |
| **likes** | `integer` | 采集  | 点赞数 |
| **dislikes** | `integer` | 采集  | 点踩数 |
| **collections** | `integer` | 采集  | 收藏数 |
| **comments** | `integer` | 采集  | 评论数 |
| **views** | `integer` | 采集  | 浏览量 |