import sys
import os
import asyncio
import logging

# 1. 引入 Scrapy 核心组件
from scrapy.crawler import CrawlerRunner
from scrapy.utils.project import get_project_settings
from scrapy.utils.log import configure_logging
from scrapy import signals
from twisted.internet import reactor, defer

# 2. 引入你的 SDK 和 爬虫类
from csi_base_components_sdk.node import AsyncFlowNode
from csi_crawlers.spiders.javbus import JavbusSpider

# 建立映射
SPIDER_MAP = {
    'javbus': JavbusSpider,
}

# ==========================================
# 核心组件：监控器 (Sidecar Monitor)
# 它负责在爬虫运行时“偷听”爬虫的状态
# ==========================================
class SpiderMonitor:
    def __init__(self):
        self.stats = {
            "item_count": 0,
            "error_count": 0,
            "finished_spiders": 0
        }

    def on_item_scraped(self, item, response, spider):
        """每当爬虫采集到一个 Item，这个函数就会被调用"""
        self.stats["item_count"] += 1
        # 你可以在这里做简单的打印，调度平台会收集到 stdout
        # print(f"[{spider.name}] 采集到数据: {str(item)[:50]}...") 

    def on_spider_error(self, failure, response, spider):
        """爬虫报错时调用"""
        self.stats["error_count"] += 1
        print(f"!! [{spider.name}] 发生错误: {failure}")

    def on_spider_closed(self, spider, reason):
        """单个爬虫结束时调用"""
        self.stats["finished_spiders"] += 1
        print(f"[{spider.name}] 任务结束，原因: {reason}")


# ==========================================
# 核心逻辑：Scrapy 启动器 (Twisted 环境)
# ==========================================
def run_scrapy_engine(inputs, config, monitor):
    """
    这里运行的是 Twisted 事件循环
    """
    # 1. 获取基础配置
    settings = get_project_settings()
    
    # 【高阶技巧】在这里动态修改 Settings
    # 比如：根据后端传来的配置，动态设置 Pipelines 输出的队列名
    output_queue = config.get("output_queue", "default_queue")
    # 我们利用环境变量传给 Pipeline (这是最不侵入代码的方式)
    os.environ["TARGET_RABBITMQ_QUEUE"] = output_queue
    
    # 或者直接覆盖设置 (如果 Pipeline 读取的是 settings)
    # settings.set('MY_QUEUE_NAME', output_queue)

    configure_logging(settings)
    runner = CrawlerRunner(settings)

    # 2. 解析目标平台
    # 假设 inputs = { "platforms": { "content": ["bilibili"] }, "keyword": { "content": "AI" } }
    platforms = inputs.get('platforms', {}).get('content', [])
    keyword = inputs.get('keyword', {}).get('content', '')

    if isinstance(platforms, str): platforms = [platforms]

    crawlers = []
    for p_name in platforms:
        spider_cls = SPIDER_MAP.get(p_name)
        if not spider_cls:
            continue
            
        # 3. 创建 Crawler 实例但不立即启动
        crawler = runner.create_crawler(spider_cls)

        # 4. 【关键】挂载监控钩子 (Hook Signals)
        # 将 monitor 的方法绑定到 Scrapy 的信号上
        crawler.signals.connect(monitor.on_item_scraped, signal=signals.item_scraped)
        crawler.signals.connect(monitor.on_spider_error, signal=signals.spider_error)
        crawler.signals.connect(monitor.on_spider_closed, signal=signals.spider_closed)

        # 5. 【关键】启动爬虫并注入参数
        # 这里的 kwargs (keyword=...) 会被 Scrapy 自动变成 spider.keyword
        # 爬虫代码里直接用 self.keyword 就能拿到，不需要写 __init__
        d = runner.crawl(crawler, keyword=keyword, extra_config=config)
        crawlers.append(d)

    # 6. 等待所有爬虫结束
    if crawlers:
        d_list = defer.DeferredList(crawlers)
        d_list.addBoth(lambda _: reactor.stop())
        reactor.run() # 阻塞执行
    else:
        print("没有可执行的爬虫任务")


# ==========================================
# 主入口：Asyncio 环境
# ==========================================
if __name__ == "__main__":
    # 阶段 1: 异步拉取配置 (SDK)
    # -----------------------------------
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    sdk_node = AsyncFlowNode()
    # 手动运行初始化
    loop.run_until_complete(sdk_node.initialize())
    
    inputs = sdk_node.inputs
    config = sdk_node.config
    
    print(f">>> 任务启动，配置已拉取: {inputs}")

    # 阶段 2: 运行 Scrapy (阻塞)
    # -----------------------------------
    # 创建监控器实例
    monitor = SpiderMonitor()
    
    # 启动 Twisted Reactor (这行代码会一直运行直到爬虫结束)
    run_scrapy_engine(inputs, config, monitor)
    
    print(">>> 所有爬虫任务已结束")
    print(f">>> 统计数据: {monitor.stats}")

    # 阶段 3: 异步上报结果 (SDK)
    # -----------------------------------
    async def report_result():
        # 重新建立 session (因为之前的 loop 可能干扰)
        # 也可以在 SDK 内部优化这个逻辑
        async with AsyncFlowNode(action_node_id=sdk_node.action_node_id, api_base_url=sdk_node.api_base_url) as node:
            # 构造最终输出
            # 假设所有数据都进了一个 MQ，我们返回 MQ 的地址
            queue_uri = f"amqp://guest:guest@localhost/{os.environ.get('TARGET_RABBITMQ_QUEUE')}"
            
            # 根据监控统计判断状态
            final_status = "success"
            if monitor.stats["error_count"] > 0:
                final_status = "warning" # 或者 failed
            
            await node.finish(outputs={
                "data_queue": {
                    "type": "reference",
                    "uri": queue_uri
                },
                "job_stats": {
                    "type": "value",
                    "content": monitor.stats
                }
            })

    loop.run_until_complete(report_result())
    loop.close()