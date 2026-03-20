# 社交动态贴文(post)存储字段设计
Twitter, 微博, 朋友圈

| **字段名** | **类型** | 来源  | **描述与用途** |
| --- | --- | --- | --- |
| **title** | `text` | 采集  | **核心字段**。标题的权重通常高于正文，搜索时需要 boost。【如果平台有title】 |
| **mentions** | `keyword` (Array) | 采集  | 提到的用户ID列表（如 @elonmusk），用于分析社交关系链。【如果该平台存在@操作】 |
| **files\_urls** | `keyword` (Array) | 采集  | 图片、视频或附件等文件的直接链接列表，用于后续下载和分析。 |
| **\[待定\]metrics** | `object` | 采集  | 包含动态变化的数值，点赞、转发量等<br><br>`{ "likes": 100, "comments": 20, "shares": 5 }`。 |
| **post\_type** | `keyword` | 采集  | 枚举值：`original` (原创), `repost` (转发), `reply` (评论)。 |
| **parent\_id** | `keyword` | 采集  | 如果是转发或评论，记录父节点的 `source_id`，用于还原对话树。 |
| **geo\_location** | `geo_point` | 采集  | 如果包含经纬度，ES可支持“搜索附近5公里的推文”。 |
| **ip\_location** | `text` | 采集  | IP地理位置 |