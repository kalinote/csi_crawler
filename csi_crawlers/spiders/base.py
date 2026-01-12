import scrapy


class BaseSpider(scrapy.Spider):
    """
    基本爬虫类，自动解析通用命令行参数

    - rabbitmq_queue: RabbitMQ 队列
    - page: 页数
    - start_time: 开始时间
    - end_time: 结束时间
    - keywords: 关键词
    - crawler_type: 爬虫类型
    """
    def __init__(self, rabbitmq_queue=None, page=None, start_time=None, end_time=None, keywords=None, crawler_type=None, *args, **kwargs):
        super(BaseSpider, self).__init__(*args, **kwargs)
        
        if rabbitmq_queue:
            self.rabbitmq_queue = rabbitmq_queue
            self.logger.info(f'RabbitMQ 队列: {rabbitmq_queue}')
        
        if page is not None:
            try:
                self.page = int(page)
                self.logger.info(f'页数: {self.page}')
            except (ValueError, TypeError):
                self.logger.warning(f'无效的页数参数: {page}，将被忽略')
                self.page = None
        else:
            self.page = None
        
        if start_time is not None:
            try:
                self.start_time = int(start_time)
                self.logger.info(f'开始时间戳: {self.start_time}')
            except (ValueError, TypeError):
                self.logger.warning(f'无效的开始时间戳: {start_time}，将被忽略')
                self.start_time = None
        else:
            self.start_time = None
        
        if end_time is not None:
            try:
                self.end_time = int(end_time)
                self.logger.info(f'结束时间戳: {self.end_time}')
            except (ValueError, TypeError):
                self.logger.warning(f'无效的结束时间戳: {end_time}，将被忽略')
                self.end_time = None
        else:
            self.end_time = None
        
        if keywords is not None:
            if isinstance(keywords, str):
                self.keywords = [k.strip() for k in keywords.split(',') if k.strip()]
            elif isinstance(keywords, list):
                self.keywords = keywords
            else:
                self.keywords = []
            
            if self.keywords:
                self.logger.info(f'关键词列表: {self.keywords}')
        else:
            self.keywords = []

        if crawler_type is not None:
            if crawler_type not in ['default', 'keyword', 'user', 'video', 'forum']:
                self.logger.warning(f'无效的爬虫类型: {crawler_type}，将被忽略')
                self.crawler_type = 'default'
            else:
                self.crawler_type = crawler_type
                self.logger.info(f'爬虫类型: {self.crawler_type}')
        else:
            self.crawler_type = 'default'
            