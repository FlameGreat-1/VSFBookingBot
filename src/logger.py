import logging
import asyncio
from logging.handlers import TimedRotatingFileHandler, RotatingFileHandler
import time
import json
import os
from datetime import datetime
import psutil
from elasticsearch import AsyncElasticsearch
import sentry_sdk
from sentry_sdk.integrations.logging import LoggingIntegration
from prometheus_client import Counter, Histogram, Gauge
import threading
import queue
import aiofiles
from typing import Dict, Any, Optional
import traceback
import socket
import uuid

class AsyncHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.queue = asyncio.Queue()
        self.task = None

    def emit(self, record):
        asyncio.create_task(self.queue.put(record))

    async def run(self):
        while True:
            record = await self.queue.get()
            await self.async_emit(record)
            self.queue.task_done()

    async def async_emit(self, record):
        raise NotImplementedError

    def start(self):
        if self.task is None:
            self.task = asyncio.create_task(self.run())

    async def stop(self):
        if self.task:
            await self.queue.join()
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

class AsyncRotatingFileHandler(RotatingFileHandler, AsyncHandler):
    def __init__(self, filename, mode='a', maxBytes=0, backupCount=0, encoding=None, delay=False):
        RotatingFileHandler.__init__(self, filename, mode, maxBytes, backupCount, encoding, delay)
        AsyncHandler.__init__(self)
        self.stream = None

    async def async_emit(self, record):
        try:
            msg = self.format(record)
            encoding = self.encoding or "utf-8"
            async with aiofiles.open(self.baseFilename, 'a', encoding=encoding) as file:
                await file.write(msg + self.terminator)
            if self.shouldRollover(record):
                await self.doRollover()
        except Exception:
            self.handleError(record)

    async def doRollover(self):
        if self.stream:
            await self.stream.close()
            self.stream = None
        if self.backupCount > 0:
            for i in range(self.backupCount - 1, 0, -1):
                sfn = self.rotation_filename("%s.%d" % (self.baseFilename, i))
                dfn = self.rotation_filename("%s.%d" % (self.baseFilename, i + 1))
                if os.path.exists(sfn):
                    if os.path.exists(dfn):
                        os.remove(dfn)
                    os.rename(sfn, dfn)
            dfn = self.rotation_filename(self.baseFilename + ".1")
            if os.path.exists(dfn):
                os.remove(dfn)
            self.rotate(self.baseFilename, dfn)
        if not self.delay:
            self.stream = self._open()

class AsyncElasticsearchHandler(AsyncHandler):
    def __init__(self, es_node: str, index_prefix: str):
        super().__init__()
        self.es = AsyncElasticsearch([es_node])
        self.index_prefix = index_prefix

    async def async_emit(self, record):
        log_entry = self.format(record)
        action = {
            "_index": f"{self.index_prefix}-{datetime.now().strftime('%Y.%m.%d')}",
            "_source": log_entry
        }
        try:
            await self.es.index(body=action['_source'], index=action['_index'])
        except Exception:
            self.handleError(record)

class Logger:
    def __init__(self, options: Optional[Dict[str, Any]] = None):
        self.options = {
            'app_name': 'VFSBookingBot',
            'environment': 'development',
            'log_level': 'INFO',
            'log_rotation_period': 'D',
            'log_retention_period': 14,
            'log_max_size': 100 * 1024 * 1024,  # 100 MB
            'elasticsearch_node': None,
            'sentry_dsn': None,
            'log_dir': 'logs',
            **(options or {})
        }
        self.logger = None
        self.start_performance_monitoring()
        self.initialize_prometheus_metrics()

    def initialize_sentry(self):
        if self.options['sentry_dsn']:
            sentry_logging = LoggingIntegration(
                level=logging.INFO,
                event_level=logging.ERROR
            )
            sentry_sdk.init(
                dsn=self.options['sentry_dsn'],
                integrations=[sentry_logging],
                environment=self.options['environment'],
                release=self.options.get('app_version', '0.0.1')
            )

    def create_logger(self):
        logger = logging.getLogger(self.options['app_name'])
        logger.setLevel(self.options['log_level'])

        formatter = logging.Formatter('%(asctime)s [%(levelname)s] [%(name)s] [%(filename)s:%(lineno)d] - %(message)s')

        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

        os.makedirs(self.options['log_dir'], exist_ok=True)
        log_file = os.path.join(self.options['log_dir'], f"{self.options['app_name']}.log")
        file_handler = AsyncRotatingFileHandler(
            log_file,
            mode='a',
            maxBytes=self.options['log_max_size'],
            backupCount=self.options['log_retention_period'],
            encoding='utf-8'
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

        if self.options['elasticsearch_node']:
            es_handler = AsyncElasticsearchHandler(
                self.options['elasticsearch_node'],
                f"logs-{self.options['app_name'].lower()}"
            )
            es_handler.setFormatter(formatter)
            logger.addHandler(es_handler)

        return logger

    def start_performance_monitoring(self):
        self.performance_metrics = {
            'start_time': time.time(),
            'log_counts': {'INFO': 0, 'WARNING': 0, 'ERROR': 0, 'CRITICAL': 0}
        }

    def initialize_prometheus_metrics(self):
        from prometheus_client import REGISTRY
        try:
            self.log_counter = Counter('log_entries_total', 'Total number of log entries', ['level'])
        except ValueError:
            self.log_counter = REGISTRY._names_to_collectors.get('log_entries_total')
        
        try:
            self.log_latency = Histogram('log_latency_seconds', 'Latency of logging operations')
        except ValueError:
            self.log_latency = REGISTRY._names_to_collectors.get('log_latency_seconds')
        
        try:
            self.memory_usage_gauge = Gauge('memory_usage_bytes', 'Memory usage in bytes')
        except ValueError:
            self.memory_usage_gauge = REGISTRY._names_to_collectors.get('memory_usage_bytes')
        
        try:
            self.cpu_usage_gauge = Gauge('cpu_usage_percent', 'CPU usage percentage')
        except ValueError:
            self.cpu_usage_gauge = REGISTRY._names_to_collectors.get('cpu_usage_percent')

    async def log_performance_metrics(self):
        current_time = time.time()
        uptime = current_time - self.performance_metrics['start_time']

        memory_usage = psutil.virtual_memory()
        cpu_usage = psutil.cpu_percent()

        self.memory_usage_gauge.set(memory_usage.used)
        self.cpu_usage_gauge.set(cpu_usage)

        await self.info('Performance Metrics', {
            'uptime': uptime,
            'log_counts': self.performance_metrics['log_counts'],
            'memory_usage': {
                'total': memory_usage.total,
                'available': memory_usage.available,
                'percent': memory_usage.percent
            },
            'cpu_usage': cpu_usage
        })

    async def log(self, level: str, message: str, meta: Optional[Dict[str, Any]] = None):
        meta = meta or {}
        meta.update({
            'hostname': socket.gethostname(),
            'process_id': os.getpid(),
            'thread_id': threading.get_ident(),
            'log_id': str(uuid.uuid4())
        })
        log_message = f"{message} {json.dumps(meta)}"
        
        with self.log_latency.time():
            getattr(self.logger, level.lower())(log_message)
        
        self.performance_metrics['log_counts'][level.upper()] += 1
        self.log_counter.labels(level=level.lower()).inc()

        if level.upper() == 'ERROR' and self.options['sentry_dsn']:
            sentry_sdk.capture_exception(Exception(message), extra=meta)

    async def info(self, message: str, meta: Optional[Dict[str, Any]] = None):
        await self.log('INFO', message, meta)

    async def warn(self, message: str, meta: Optional[Dict[str, Any]] = None):
        await self.log('WARNING', message, meta)

    async def error(self, message: str, error: Optional[Exception] = None, meta: Optional[Dict[str, Any]] = None):
        meta = meta or {}
        if error:
            meta['error'] = str(error)
            meta['traceback'] = traceback.format_exc()
        await self.log('ERROR', message, meta)

    async def critical(self, message: str, error: Optional[Exception] = None, meta: Optional[Dict[str, Any]] = None):
        meta = meta or {}
        if error:
            meta['error'] = str(error)
            meta['traceback'] = traceback.format_exc()
        await self.log('CRITICAL', message, meta)

    def start_timer(self):
        return time.time()

    async def end_timer(self, start: float, message: str, meta: Optional[Dict[str, Any]] = None):
        duration = time.time() - start
        meta = meta or {}
        meta['duration'] = f"{duration:.3f}s"
        await self.info(message, meta)
        return duration

    async def initialize(self):
        self.logger = self.create_logger()
        for handler in self.logger.handlers:
            if isinstance(handler, AsyncHandler):
                handler.start()
        self.initialize_sentry()

    async def close(self):
        for handler in self.logger.handlers:
            if isinstance(handler, AsyncHandler):
                await handler.stop()

    async def __aenter__(self):
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
