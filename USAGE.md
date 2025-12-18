# 爬虫通用参数使用说明

所有继承 `BaseSpider` 的爬虫都自动支持以下命令行参数：

## 参数列表

### 1. rabbitmq_queue
RabbitMQ 队列名称
- 类型：字符串
- 示例：`-a rabbitmq_queue=test_queue`

### 2. page
页数
- 类型：整数
- 示例：`-a page=10`

### 3. start_time
开始时间（10位时间戳）
- 类型：整数
- 示例：`-a start_time=1702540800`

### 4. end_time
结束时间（10位时间戳）
- 类型：整数
- 示例：`-a end_time=1702627200`

### 5. keywords
关键词列表（用半角逗号分隔）
- 类型：字符串列表
- 示例：`-a keywords="关键词1,关键词2,关键词3"`

## 使用示例

### 单个参数
```bash
scrapy crawl javbus -a page=10
```

### 多个参数
```bash
scrapy crawl javbus -a page=10 -a start_time=1702540800 -a end_time=1702627200
```

### 所有参数
```bash
scrapy crawl javbus -a rabbitmq_queue=custom_queue -a page=5 -a start_time=1702540800 -a end_time=1702627200 -a keywords="关键词1,关键词2,关键词3"
```

## 在爬虫代码中使用

所有参数都会自动转换为正确的类型并赋值给 `self`：

```python
class MySpider(BaseSpider):
    name = "myspider"
    
    def parse(self, response):
        # 直接使用参数
        if self.page:
            self.logger.info(f"当前处理第 {self.page} 页")
        
        if self.start_time and self.end_time:
            self.logger.info(f"时间范围: {self.start_time} - {self.end_time}")
        
        if self.keywords:
            for keyword in self.keywords:
                self.logger.info(f"搜索关键词: {keyword}")
```

## 参数类型说明

- `rabbitmq_queue`: `str | None`
- `page`: `int | None`
- `start_time`: `int | None`
- `end_time`: `int | None`
- `keywords`: `list[str]` (默认为空列表 `[]`)

所有参数都是可选的，如果不提供则为 `None`（keywords 为空列表）。


