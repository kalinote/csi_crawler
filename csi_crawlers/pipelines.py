# Define your item pipelines here
#
# Don't forget to add your pipeline to the ITEM_PIPELINES setting
# See: https://docs.scrapy.org/en/latest/topics/item-pipeline.html


# useful for handling different item types with a single interface
import json
from uuid import uuid4

from itemadapter import ItemAdapter
from scrapy.utils.serialize import ScrapyJSONEncoder


class CsiCrawlersPipeline:
    def process_item(self, item, spider):
        return item


class RabbitMQPipeline:
    def __init__(self, rabbitmq_client, rabbitmq_queue, component_context=None):
        self.rabbitmq = rabbitmq_client
        self.rabbitmq_queue = rabbitmq_queue
        self.component_context = component_context
        self.encoder = ScrapyJSONEncoder()
        self.spider = None

    @classmethod
    def from_crawler(cls, crawler):
        instance = cls(
            rabbitmq_client=getattr(crawler, 'csi_rabbitmq_client', None),
            rabbitmq_queue=crawler.settings.get('RABBITMQ_QUEUE', 'scrapy_items'),
            component_context=getattr(crawler, 'csi_component_context', None),
        )
        instance.crawler = crawler
        return instance

    def open_spider(self):
        spider = self.crawler.spider
        self.spider = spider
        custom_queue = getattr(spider, 'rabbitmq_queue', None)
        if custom_queue:
            if ',' in custom_queue:
                self.rabbitmq_queues = list(dict.fromkeys(
                    q.strip() for q in custom_queue.split(',') if q.strip()
                ))
                spider.logger.info(f'Pipeline 使用自定义 RabbitMQ 队列(多个): {self.rabbitmq_queues}')
            else:
                self.rabbitmq_queues = [custom_queue]
                spider.logger.info(f'Pipeline 使用自定义 RabbitMQ 队列: {custom_queue}')
        else:
            self.rabbitmq_queues = [self.rabbitmq_queue]
        if self.rabbitmq is None:
            raise RuntimeError('Scrapy Pipeline 未获得 SDK RabbitMQ 客户端')

    def close_spider(self):
        # RabbitMQ 生命周期由 SDK Runner 统一管理。
        return None

    def process_item(self, item):
        adapter = ItemAdapter(item)
        item_dict = dict(adapter)
        
        message = json.loads(self.encoder.encode(item_dict))
        # 同一逻辑记录在多队列 fan-out 和重试中必须复用同一 ID。
        message_id = uuid4().hex
        queue_names = list(dict.fromkeys(self.rabbitmq_queues))
        if not queue_names:
            raise RuntimeError('采集结果没有可用的 Reference 输出队列')
        success_count = self.rabbitmq.send_messages_batch(
            queue_names,
            message,
            message_id=message_id,
        )
        if success_count != len(queue_names):
            raise RuntimeError(
                'SDK 未能将采集结果发布到全部 Reference 输出队列，'
                f'message_id={message_id}'
            )
        if self.component_context is not None:
            self.component_context.mark_successful_result()
        
        return item
