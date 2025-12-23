import sys
import os

# 将项目根目录加入 python 搜索路径并设置 settings 模块
root_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, root_dir)
os.environ.setdefault('SCRAPY_SETTINGS_MODULE', 'csi_crawlers.settings')

from csi_base_component_sdk import BaseComponent
from scrapy.crawler import CrawlerProcess
from scrapy.utils.project import get_project_settings
from scrapy import signals
import logging
from typing import Dict, List, Any, Optional

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] [LAUNCHER] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("LAUNCHER")


class SpiderMonitor:
    def __init__(self, total_spiders: int, sdk_node: BaseComponent):
        self.total_spiders = total_spiders
        self.sdk_node = sdk_node
        self.spider_progress = {}
        self.spider_errors = {}
        self.spider_success = {}
        self.item_counts = {}
        self.base_progress = 0
        
    def on_spider_opened(self, spider):
        spider_name = spider.name
        self.spider_progress[spider_name] = 10
        logger.info(f"爬虫 {spider_name} 已启动")
        self._update_overall_progress(f"爬虫 {spider_name} 已启动")
    
    def on_spider_closed(self, spider, reason):
        spider_name = spider.name
        if reason == 'finished':
            self.spider_progress[spider_name] = 100
            self.spider_success[spider_name] = True
            logger.info(f"爬虫 {spider_name} 已完成，原因: {reason}")
        else:
            self.spider_errors[spider_name] = f"关闭原因: {reason}"
            self.spider_success[spider_name] = False
            logger.warning(f"爬虫 {spider_name} 异常关闭，原因: {reason}")
        
        self._update_overall_progress(f"爬虫 {spider_name} 已结束")
    
    def on_item_scraped(self, item, spider):
        spider_name = spider.name
        self.item_counts[spider_name] = self.item_counts.get(spider_name, 0) + 1
        
        if self.item_counts[spider_name] % 10 == 0:
            current = min(90, 10 + (self.item_counts[spider_name] // 10) * 5)
            self.spider_progress[spider_name] = current
            self._update_overall_progress(f"爬虫 {spider_name} 已采集 {self.item_counts[spider_name]} 条数据")
    
    def on_spider_error(self, failure, spider):
        spider_name = spider.name
        error_msg = str(failure.value)
        self.spider_errors[spider_name] = error_msg
        logger.error(f"爬虫 {spider_name} 发生错误: {error_msg}")
    
    def _update_overall_progress(self, message: str):
        if not self.spider_progress:
            return
        
        avg_progress = sum(self.spider_progress.values()) / self.total_spiders
        self.sdk_node.report_progress(int(avg_progress), message)
    
    def record_startup_error(self, spider_name: str, error: str):
        self.spider_errors[spider_name] = error
        self.spider_success[spider_name] = False
        logger.error(f"爬虫 {spider_name} 启动失败: {error}")
    
    def has_success(self) -> bool:
        return any(self.spider_success.values())
    
    def get_summary(self) -> Dict[str, Any]:
        success_spiders = [name for name, success in self.spider_success.items() if success]
        failed_spiders = [
            {"name": name, "error": self.spider_errors.get(name, "未知错误")}
            for name, success in self.spider_success.items() if not success
        ]
        
        total_items = sum(self.item_counts.values())
        
        return {
            "status": "success",
            "total_spiders": self.total_spiders,
            "success_spiders": success_spiders,
            "failed_spiders": failed_spiders,
            "total_items_scraped": total_items,
            "item_counts": self.item_counts
        }
    
    def get_error_message(self) -> str:
        errors = [f"{name}: {error}" for name, error in self.spider_errors.items()]
        return "所有爬虫都失败了。错误信息: " + "; ".join(errors)


def extract_platforms(inputs: Dict[str, Any]) -> List[str]:
    platforms_data = inputs.get('platforms')
    
    if not platforms_data:
        logger.warning("配置中未找到 platforms 参数，将尝试从其他字段中查找")
        for key, value in inputs.items():
            if isinstance(value, dict) and value.get('type') == 'value':
                val = value.get('value')
                if isinstance(val, list) and all(isinstance(v, str) for v in val):
                    logger.info(f"从 {key} 字段中提取到平台列表: {val}")
                    return val
        return []
    
    if isinstance(platforms_data, dict) and platforms_data.get('type') == 'value':
        platforms = platforms_data.get('value', [])
    elif isinstance(platforms_data, list):
        platforms = platforms_data
    else:
        platforms = [str(platforms_data)]
    
    if not platforms:
        logger.error("未能提取到有效的平台列表")
    
    return platforms


def parse_spider_args(config: Dict[str, Any], inputs: Dict[str, Any], outputs: Dict[str, Any]) -> Dict[str, str]:
    args = {}
    
    for key, value in config.items():
        if isinstance(value, list):
            args[key] = ','.join(str(v) for v in value)
        else:
            args[key] = str(value)
    
    for key, input_data in inputs.items():
        if key == 'platforms':
            continue
        
        if isinstance(input_data, dict) and input_data.get('type') == 'value':
            value = input_data.get('value')
            if isinstance(value, list):
                args[key] = ','.join(str(v) for v in value)
            else:
                args[key] = str(value)
        
    for key, output in outputs.items():
        queues = []
        if isinstance(output, dict) and output.get('type') == 'reference':
            value = output.get('value', [])
            if isinstance(value, list):
                queues.extend(value)
            else:
                queues.append(str(value))
        
        if queues:
            args['rabbitmq_queue'] = ','.join(queues)
    
    return args


def main():
    with BaseComponent() as node:
        logger.info("启动 Scrapy 爬虫调度器")
        
        config = node.config
        inputs = node.inputs
        outputs = node.outputs
        
        logger.info(f"接收到配置: config={config}")
        logger.info(f"接收到输入: inputs={inputs}")
        logger.info(f"接收到输出: outputs={outputs}")
        
        platforms = extract_platforms(inputs)
        if not platforms:
            node.fail("未能从配置中提取到有效的平台列表(platforms)")
            return
        
        logger.info(f"将要运行的爬虫: {platforms}")
        
        spider_args = parse_spider_args(config, inputs, outputs)
        logger.info(f"解析的爬虫参数: {spider_args}")
        
        monitor = SpiderMonitor(len(platforms), node)
        
        settings = get_project_settings()
        process = CrawlerProcess(settings)
        
        for spider_name in platforms:
            try:
                crawler = process.create_crawler(spider_name)
                
                crawler.signals.connect(monitor.on_spider_opened, signal=signals.spider_opened)
                crawler.signals.connect(monitor.on_spider_closed, signal=signals.spider_closed)
                crawler.signals.connect(monitor.on_item_scraped, signal=signals.item_scraped)
                crawler.signals.connect(monitor.on_spider_error, signal=signals.spider_error)
                
                process.crawl(crawler, **spider_args)
                
                logger.info(f"爬虫 {spider_name} 已加入执行队列")
            except KeyError as e:
                error_msg = f"爬虫不存在: {spider_name}"
                monitor.record_startup_error(spider_name, error_msg)
                logger.error(error_msg)
            except Exception as e:
                error_msg = f"启动失败: {str(e)}"
                monitor.record_startup_error(spider_name, error_msg)
                logger.error(f"爬虫 {spider_name} 启动异常: {error_msg}")
        
        if not process.crawlers:
            node.fail("所有爬虫都启动失败")
            return
        
        logger.info("开始执行爬虫...")
        node.report_progress(5, "爬虫开始执行")
        
        try:
            process.start()
        except Exception as e:
            logger.error(f"爬虫执行过程中发生异常: {e}")
            node.fail(f"爬虫执行异常: {str(e)}")
            return
        
        logger.info("所有爬虫执行完毕，开始汇总结果")
        
        if monitor.has_success():
            summary = monitor.get_summary()
            logger.info(f"执行成功: {summary}")
            node.finish(summary)
        else:
            error_msg = monitor.get_error_message()
            logger.error(f"执行失败: {error_msg}")
            node.fail(error_msg)


if __name__ == '__main__':
    main()
