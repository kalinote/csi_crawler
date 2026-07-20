import sys
import os
import json

# 将项目根目录加入 python 搜索路径并设置 settings 模块
root_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, root_dir)
os.environ.setdefault('SCRAPY_SETTINGS_MODULE', 'csi_crawlers.settings')

from csi_base_component_sdk import ComponentContext, ComponentFailure
from scrapy.crawler import CrawlerProcess
from scrapy.utils.project import get_project_settings
from scrapy import signals
import logging
from twisted.internet.task import LoopingCall
from typing import Any, Dict, List

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] [CSI_CRAWLER] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("csi_crawler")


class SpiderMonitor:
    def __init__(self, total_spiders: int, ctx: ComponentContext):
        self.total_spiders = total_spiders
        self.ctx = ctx
        self.spider_progress = {}
        self.spider_errors = {}
        self.spider_success = {}
        self.item_counts = {}
        
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
        self.ctx.report_progress(int(avg_progress), message)
    
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
            "total_spiders": self.total_spiders,
            "success_spiders": success_spiders,
            "failed_spiders": failed_spiders,
            "total_items_scraped": total_items,
            "item_counts": self.item_counts
        }
    
    def get_error_message(self) -> str:
        errors = [f"{name}: {error}" for name, error in self.spider_errors.items()]
        return "所有爬虫都失败了。错误信息: " + "; ".join(errors)


def extract_resources_config(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """提取平台专属配置，整体可选，不存在或为 null 时返回空 dict。"""
    data = inputs.get('resources_config')
    if not data:
        return {}
    if isinstance(data, dict) and data.get('type') == 'value':
        return data.get('value') or {}
    return {}


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
        # output 是 Runner 本地文件导出配置，不应作为爬虫参数下发。
        if key == 'output':
            continue
        if isinstance(value, list):
            args[key] = ','.join(str(v) for v in value)
        else:
            args[key] = str(value)
    
    for key, input_data in inputs.items():
        if key in ('platforms', 'resources_config'):
            continue
        
        if isinstance(input_data, dict) and input_data.get('type') == 'value':
            value = input_data.get('value')
            if isinstance(value, list):
                args[key] = ','.join(str(v) for v in value)
            else:
                args[key] = str(value)
        
    queues = []
    for output in outputs.values():
        if isinstance(output, dict) and output.get('type') == 'reference':
            value = output.get('value', [])
            if isinstance(value, list):
                queues.extend(value)
            else:
                queues.append(str(value))

    if queues:
        args['rabbitmq_queue'] = ','.join(queues)
    
    return args


def run(ctx: ComponentContext) -> Dict[str, Any]:
    """根据运行上下文启动指定 Scrapy 爬虫并返回汇总结果。"""
    ctx.logger.info("启动 Scrapy 爬虫调度器")

    config = ctx.config
    inputs = ctx.inputs
    outputs = ctx.outputs

    # 不记录完整值：resources_config 可能包含 cookie、代理认证和请求头。
    ctx.logger.info(
        "运行上下文已加载",
        config_keys=sorted(config),
        input_keys=sorted(inputs),
        output_keys=sorted(outputs),
    )

    platforms = extract_platforms(inputs)
    if not platforms:
        raise ComponentFailure("未能从配置中提取到有效的平台列表(platforms)")

    ctx.logger.info("爬虫列表解析完成", platforms=platforms, spider_count=len(platforms))

    resources_config = extract_resources_config(inputs)
    ctx.logger.info("平台资源配置已加载", configured_platforms=sorted(resources_config))

    spider_args = parse_spider_args(config, inputs, outputs)
    ctx.logger.info("爬虫参数解析完成", argument_keys=sorted(spider_args))

    monitor = SpiderMonitor(len(platforms), ctx)
    settings = get_project_settings()
    output_file = ctx.get_config("output")

    if output_file:
        _, ext = os.path.splitext(str(output_file))
        ext_map = {
            '.jsonl': 'jsonlines',
            '.csv': 'csv',
            '.xml': 'xml',
            '.json': 'json'
        }
        out_format = ext_map.get(ext.lower(), 'json')
        settings.set('FEEDS', {
            str(output_file): {
                'format': out_format,
                'encoding': 'utf8',
                'indent': 4,
            }
        }, priority='cmdline')
        logger.info(f"已启用文件输出: {output_file} (格式: {out_format})")

    # SDK Runner 已接管根日志处理器。禁止 Scrapy 再向 stderr 安装 handler，
    # 否则普通 Scrapy 日志会被重复采集并按 stderr 错误地标记为 ERROR；
    # urllib3 的日志上传诊断还可能进一步形成自采集反馈回路。
    process = CrawlerProcess(settings, install_root_handler=False)

    for spider_name in platforms:
        try:
            crawler = process.create_crawler(spider_name)

            crawler.signals.connect(monitor.on_spider_opened, signal=signals.spider_opened)
            crawler.signals.connect(monitor.on_spider_closed, signal=signals.spider_closed)
            crawler.signals.connect(monitor.on_item_scraped, signal=signals.item_scraped)
            crawler.signals.connect(monitor.on_spider_error, signal=signals.spider_error)

            per = resources_config.get(spider_name, {})
            merged = {**spider_args}

            if per.get('sections'):
                secs = per['sections']
                merged['sections'] = ','.join(secs) if isinstance(secs, list) else str(secs)

            if per.get('proxy') is not None:
                merged['proxy_url'] = per['proxy'] or ''

            if per.get('headers'):
                merged['platform_headers'] = json.dumps(per['headers'], ensure_ascii=False)

            if per.get('cookies') is not None:
                value = per['cookies']
                merged['platform_cookies'] = (
                    json.dumps(value) if isinstance(value, dict) else (value or '')
                )

            process.crawl(crawler, **merged)
            logger.info(f"爬虫 {spider_name} 已加入执行队列")
        except KeyError:
            error_msg = f"爬虫不存在: {spider_name}"
            monitor.record_startup_error(spider_name, error_msg)
        except Exception as exc:
            error_msg = f"启动失败: {str(exc)}"
            monitor.record_startup_error(spider_name, error_msg)
            logger.error(f"爬虫 {spider_name} 启动异常: {error_msg}")

    if not process.crawlers:
        raise ComponentFailure("所有爬虫都启动失败")

    logger.info("开始执行爬虫...")
    ctx.report_progress(5, "爬虫开始执行")
    ctx.raise_if_cancelled()

    def stop_if_cancelled() -> None:
        try:
            ctx.raise_if_cancelled()
        except ComponentFailure:
            logger.warning("收到取消或超时请求，正在停止爬虫")
            process.stop()

    cancel_check = LoopingCall(stop_if_cancelled)
    cancel_check.start(1.0, now=False)

    try:
        process.start()
    except ComponentFailure:
        raise
    except Exception as exc:
        logger.error(f"爬虫执行过程中发生异常: {exc}")
        raise ComponentFailure(f"爬虫执行异常: {str(exc)}") from exc
    finally:
        if cancel_check.running:
            cancel_check.stop()

    ctx.raise_if_cancelled()

    logger.info("所有爬虫执行完毕，开始汇总结果")

    if monitor.has_success():
        summary = monitor.get_summary()
        logger.info(f"执行成功: {summary}")
        return summary

    error_msg = monitor.get_error_message()
    logger.error(f"执行失败: {error_msg}")
    raise ComponentFailure(error_msg)
