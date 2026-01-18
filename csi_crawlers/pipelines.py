# Define your item pipelines here
#
# Don't forget to add your pipeline to the ITEM_PIPELINES setting
# See: https://docs.scrapy.org/en/latest/topics/item-pipeline.html


# useful for handling different item types with a single interface
from itemadapter import ItemAdapter
import json
import pika
from scrapy.utils.serialize import ScrapyJSONEncoder


class CsiCrawlersPipeline:
    def process_item(self, item, spider):
        return item


class RabbitMQPipeline:
    def __init__(self, rabbitmq_host, rabbitmq_port, rabbitmq_user, rabbitmq_password, 
                 rabbitmq_vhost, rabbitmq_exchange, rabbitmq_routing_key, rabbitmq_queue):
        self.rabbitmq_host = rabbitmq_host
        self.rabbitmq_port = rabbitmq_port
        self.rabbitmq_user = rabbitmq_user
        self.rabbitmq_password = rabbitmq_password
        self.rabbitmq_vhost = rabbitmq_vhost
        self.rabbitmq_exchange = rabbitmq_exchange
        self.rabbitmq_routing_key = rabbitmq_routing_key
        self.rabbitmq_queue = rabbitmq_queue
        self.connection = None
        self.channel = None
        self.encoder = ScrapyJSONEncoder()
        self.spider = None

    @classmethod
    def from_crawler(cls, crawler):
        return cls(
            rabbitmq_host=crawler.settings.get('RABBITMQ_HOST', 'localhost'),
            rabbitmq_port=crawler.settings.get('RABBITMQ_PORT', 5672),
            rabbitmq_user=crawler.settings.get('RABBITMQ_USER', 'guest'),
            rabbitmq_password=crawler.settings.get('RABBITMQ_PASSWORD', 'guest'),
            rabbitmq_vhost=crawler.settings.get('RABBITMQ_VHOST', '/'),
            rabbitmq_exchange=crawler.settings.get('RABBITMQ_EXCHANGE', ''),
            rabbitmq_routing_key=crawler.settings.get('RABBITMQ_ROUTING_KEY', 'scrapy_items'),
            rabbitmq_queue=crawler.settings.get('RABBITMQ_QUEUE', 'scrapy_items')
        )

    def _connect_rabbitmq(self):
        """创建或重新创建RabbitMQ连接"""
        try:
            if self.connection and not self.connection.is_closed:
                self.connection.close()
        except Exception as e:
            if self.spider:
                self.spider.logger.warning(f'关闭旧连接时出错: {e}')
        
        credentials = pika.PlainCredentials(self.rabbitmq_user, self.rabbitmq_password)
        parameters = pika.ConnectionParameters(
            host=self.rabbitmq_host,
            port=self.rabbitmq_port,
            virtual_host=self.rabbitmq_vhost,
            credentials=credentials,
            heartbeat=600,
            blocked_connection_timeout=300,
        )
        self.connection = pika.BlockingConnection(parameters)
        self.channel = self.connection.channel()
        
        for queue in self.rabbitmq_queues:
            if self.rabbitmq_exchange:
                self.channel.exchange_declare(
                    exchange=self.rabbitmq_exchange,
                    exchange_type='direct',
                    durable=True
                )
                self.channel.queue_declare(queue=queue, durable=True)
                self.channel.queue_bind(
                    exchange=self.rabbitmq_exchange,
                    queue=queue,
                    routing_key=queue
                )
            else:
                self.channel.queue_declare(queue=queue, durable=True)
        
        if self.spider:
            self.spider.logger.info('RabbitMQ 连接已建立')
    
    def _ensure_connection(self):
        """确保连接和channel处于正常状态"""
        if not self.connection or self.connection.is_closed:
            if self.spider:
                self.spider.logger.warning('检测到连接已关闭，正在重新连接...')
            self._connect_rabbitmq()
            return
        
        if not self.channel or self.channel.is_closed:
            if self.spider:
                self.spider.logger.warning('检测到channel已关闭，正在重新创建...')
            self._connect_rabbitmq()

    def open_spider(self, spider):
        self.spider = spider
        custom_queue = getattr(spider, 'rabbitmq_queue', None)
        if custom_queue:
            if ',' in custom_queue:
                self.rabbitmq_queues = [q.strip() for q in custom_queue.split(',') if q.strip()]
                spider.logger.info(f'Pipeline 使用自定义 RabbitMQ 队列(多个): {self.rabbitmq_queues}')
            else:
                self.rabbitmq_queues = [custom_queue]
                spider.logger.info(f'Pipeline 使用自定义 RabbitMQ 队列: {custom_queue}')
        else:
            self.rabbitmq_queues = [self.rabbitmq_queue]
        
        self._connect_rabbitmq()

    def close_spider(self, spider):
        if self.connection and not self.connection.is_closed:
            self.connection.close()

    def process_item(self, item, spider):
        adapter = ItemAdapter(item)
        item_dict = dict(adapter)
        
        message = json.dumps(item_dict, ensure_ascii=False, cls=self.encoder.__class__)
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                self._ensure_connection()
                
                for queue in self.rabbitmq_queues:
                    if self.rabbitmq_exchange:
                        self.channel.basic_publish(
                            exchange=self.rabbitmq_exchange,
                            routing_key=queue,
                            body=message,
                            properties=pika.BasicProperties(
                                delivery_mode=2,
                            )
                        )
                    else:
                        self.channel.basic_publish(
                            exchange='',
                            routing_key=queue,
                            body=message,
                            properties=pika.BasicProperties(
                                delivery_mode=2,
                            )
                        )
                break
            except (pika.exceptions.ChannelWrongStateError, 
                    pika.exceptions.ChannelClosedByBroker,
                    pika.exceptions.ConnectionClosedByBroker,
                    pika.exceptions.AMQPConnectionError) as e:
                spider.logger.warning(f'发送消息到 RabbitMQ 失败 (尝试 {attempt + 1}/{max_retries}): {e}')
                if attempt < max_retries - 1:
                    self._connect_rabbitmq()
                else:
                    spider.logger.error(f'发送消息到 RabbitMQ 失败，已重试{max_retries}次')
                    raise
            except Exception as e:
                spider.logger.error(f'发送消息到 RabbitMQ 时发生未知错误: {e}')
                raise
        
        return item
