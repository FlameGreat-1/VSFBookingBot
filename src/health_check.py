import asyncio
import time
import psutil
from typing import Dict, Any, List, Callable
from dataclasses import dataclass, asdict
from enum import Enum
import aiohttp
import aiofiles
from prometheus_client import Gauge, Counter, Histogram, REGISTRY
import logging
from datetime import datetime, timedelta
import json
import os

# Import custom components
from logger import Logger
from config import config

class HealthStatus(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    CRITICAL = "critical"
    UNKNOWN = "unknown"

@dataclass
class ComponentHealth:
    status: HealthStatus
    response_time: float
    last_checked: str
    error: str = None

@dataclass
class SystemHealth:
    cpu_usage: float
    memory_usage: float
    disk_usage: float
    network_latency: float
    uptime: float

class HealthCheck:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.logger = Logger(config).create_logger()
        self.session = None
        self.health_status = {
            'overall': HealthStatus.UNKNOWN,
            'components': {},
            'system': None,
            'last_check': None,
        }
        self.error_counts: Dict[str, int] = {}
        self.total_checks = 0
        self.is_running = False

        # Prometheus metrics for overall health
        try:
            self.health_gauge = Gauge('system_health_status', 'Overall system health status', ['status'])
        except ValueError:
            self.health_gauge = REGISTRY._names_to_collectors.get('system_health_status')
            if self.health_gauge is None:
                raise

        # Prometheus metrics for component health
        try:
            self.component_health_gauge = Gauge('component_health_status', 'Component health status', ['component', 'status'])
        except ValueError:
            self.component_health_gauge = REGISTRY._names_to_collectors.get('component_health_status')
            if self.component_health_gauge is None:
                raise

        # Prometheus metrics for response time
        try:
            self.response_time_histogram = Histogram('response_time_seconds', 'Response time in seconds', ['component'])
        except ValueError:
            self.response_time_histogram = REGISTRY._names_to_collectors.get('response_time_seconds')
            if self.response_time_histogram is None:
                raise

        # Prometheus metrics for health check errors
        try:
            self.error_counter = Counter('health_check_errors_total', 'Total number of health check errors', ['component'])
        except ValueError:
            self.error_counter = REGISTRY._names_to_collectors.get('health_check_errors_total')
            if self.error_counter is None:
                raise

        
    async def initialize(self):
        self.logger.info("Initializing HealthCheck")
        self.session = aiohttp.ClientSession()
        await self.load_health_history()

    async def start(self):
        self.logger.info("Starting HealthCheck")
        self.is_running = True
        while self.is_running:
            await self.perform_health_check()
            await asyncio.sleep(self.config['health_check_interval'])

    async def stop(self):
        self.logger.info("Stopping HealthCheck")
        self.is_running = False
        if self.session:
            await self.session.close()

    async def perform_health_check(self):
        start_time = time.time()
        self.total_checks += 1

        try:
            await self.check_components()
            await self.check_system_health()
            self.update_overall_health()
            
            end_time = time.time()
            self.health_status['last_check'] = datetime.now().isoformat()
            self.health_status['check_duration'] = end_time - start_time

            if self.health_status['overall'] != HealthStatus.HEALTHY:
                await self.attempt_recovery()

            await self.save_health_history()
            self.update_prometheus_metrics()
        except Exception as error:
            self.logger.error(f"Health check error: {str(error)}", exc_info=True)

    async def check_components(self):
        for component, url in self.config['health_check_endpoints'].items():
            try:
                start_time = time.time()
                async with self.session.get(url, timeout=self.config['health_check_timeout']) as response:
                    end_time = time.time()
                    response_time = end_time - start_time

                    if response.status == 200:
                        status = HealthStatus.HEALTHY
                        self.error_counts[component] = 0  # Reset error count on success
                    else:
                        status = HealthStatus.DEGRADED
                        self.error_counts[component] = self.error_counts.get(component, 0) + 1

                    self.health_status['components'][component] = ComponentHealth(
                        status=status,
                        response_time=response_time,
                        last_checked=datetime.now().isoformat()
                    )

                    self.response_time_histogram.labels(component).observe(response_time)

                    if response_time > self.config['health_check_timeout']:
                        self.logger.warning(f"Slow response from {component}: {response_time:.2f} seconds")

            except asyncio.TimeoutError:
                self.handle_component_error(component, "Timeout")
            except Exception as error:
                self.handle_component_error(component, str(error))

    def handle_component_error(self, component: str, error: str):
        self.error_counts[component] = self.error_counts.get(component, 0) + 1
        self.health_status['components'][component] = ComponentHealth(
            status=HealthStatus.CRITICAL,
            response_time=-1,
            last_checked=datetime.now().isoformat(),
            error=error
        )
        self.logger.error(f"{component} error: {error}")
        self.error_counter.labels(component).inc()

    async def check_system_health(self):
        cpu_usage = psutil.cpu_percent() / 100
        memory_usage = psutil.virtual_memory().percent / 100
        disk_usage = psutil.disk_usage('/').percent / 100
        
        # Check network latency
        start_time = time.time()
        try:
            async with self.session.get(self.config['network_check_url'], timeout=5) as response:
                end_time = time.time()
                network_latency = end_time - start_time
        except:
            network_latency = -1

        self.health_status['system'] = SystemHealth(
            cpu_usage=cpu_usage,
            memory_usage=memory_usage,
            disk_usage=disk_usage,
            network_latency=network_latency,
            uptime=time.time() - psutil.boot_time()
        )

        if cpu_usage > self.config['health_check_thresholds']['cpu_usage']:
            self.logger.warning(f"High CPU usage: {cpu_usage:.2%}")
        if memory_usage > self.config['health_check_thresholds']['memory_usage']:
            self.logger.warning(f"High memory usage: {memory_usage:.2%}")
        if disk_usage > self.config['health_check_thresholds']['disk_usage']:
            self.logger.warning(f"High disk usage: {disk_usage:.2%}")

    def update_overall_health(self):
        component_statuses = [comp.status for comp in self.health_status['components'].values()]
        error_rate = sum(self.error_counts.values()) / (self.total_checks * len(self.error_counts)) if self.error_counts else 0

        if all(status == HealthStatus.HEALTHY for status in component_statuses) and \
           error_rate < self.config['health_check_thresholds']['error_rate'] and \
           self.health_status['system'].cpu_usage < self.config['health_check_thresholds']['cpu_usage'] and \
           self.health_status['system'].memory_usage < self.config['health_check_thresholds']['memory_usage'] and \
           self.health_status['system'].disk_usage < self.config['health_check_thresholds']['disk_usage']:
            self.health_status['overall'] = HealthStatus.HEALTHY
        elif any(status == HealthStatus.CRITICAL for status in component_statuses):
            self.health_status['overall'] = HealthStatus.CRITICAL
        else:
            self.health_status['overall'] = HealthStatus.DEGRADED

    async def attempt_recovery(self):
        self.logger.info("Attempting system recovery")
        for component, health in self.health_status['components'].items():
            if health.status != HealthStatus.HEALTHY:
                for i in range(self.config['max_retries']):
                    try:
                        url = self.config['health_check_endpoints'][component]
                        async with self.session.get(url, timeout=self.config['health_check_timeout']) as response:
                            if response.status == 200:
                                self.logger.info(f"Recovery successful for {component} after {i+1} attempts")
                                break
                    except Exception as error:
                        if i == self.config['max_retries'] - 1:
                            self.logger.error(f"Recovery failed for {component}: {str(error)}")
                    await asyncio.sleep(self.config['retry_base_delay'] * (2 ** i))  # Exponential backoff

    def get_health_status(self) -> Dict[str, Any]:
        return {
            'overall': self.health_status['overall'].value,
            'components': {k: asdict(v) for k, v in self.health_status['components'].items()},
            'system': asdict(self.health_status['system']) if self.health_status['system'] else None,
            'last_check': self.health_status['last_check'],
            'check_duration': self.health_status.get('check_duration')
        }

    def update_prometheus_metrics(self):
        self.health_gauge.labels(self.health_status['overall'].value).set(1)
        for component, health in self.health_status['components'].items():
            self.component_health_gauge.labels(component, health.status.value).set(1)

    async def record_error(self, component: str, error: str):
        self.logger.error(f"Error in {component}: {error}")
        self.error_counter.labels(component).inc()
        self.error_counts[component] = self.error_counts.get(component, 0) + 1
        await self.save_health_history()

    async def record_success(self, component: str):
        self.logger.info(f"Successful operation in {component}")
        self.error_counts[component] = 0
        await self.save_health_history()

    async def save_health_history(self):
        history = {
            'timestamp': datetime.now().isoformat(),
            'health_status': self.get_health_status(),
            'error_counts': self.error_counts
        }
        os.makedirs(self.config['health_history_dir'], exist_ok=True)
        file_path = os.path.join(self.config['health_history_dir'], f"health_history_{datetime.now().strftime('%Y%m%d')}.json")
        async with aiofiles.open(file_path, 'a') as f:
            await f.write(json.dumps(history) + '\n')

    async def load_health_history(self):
        today = datetime.now().strftime('%Y%m%d')
        file_path = os.path.join(self.config['health_history_dir'], f"health_history_{today}.json")
        if os.path.exists(file_path):
            async with aiofiles.open(file_path, 'r') as f:
                lines = await f.readlines()
                if lines:
                    last_record = json.loads(lines[-1])
                    self.error_counts = last_record['error_counts']
                    self.total_checks = sum(self.error_counts.values())

    async def __aenter__(self):
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.stop()

