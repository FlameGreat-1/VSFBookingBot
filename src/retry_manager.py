import asyncio
import time
from typing import Dict, Any, Callable, Optional
from dataclasses import dataclass
import random
import logging
from enum import Enum
from prometheus_client import Counter, Histogram
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from aiohttp import ClientError, ServerTimeoutError

# Import custom components
from logger import Logger
from health_check import HealthCheck
from security_proof import SecurityProof

@dataclass
class RetryError(Exception):
    message: str
    last_error: Exception
    attempts: int

class CircuitBreakerState(Enum):
    CLOSED = 'CLOSED'
    OPEN = 'OPEN'
    HALF_OPEN = 'HALF-OPEN'

class CircuitBreaker:
    def __init__(self, options: Dict[str, Any]):
        self.failure_threshold = options.get('failure_threshold', 5)
        self.reset_timeout = options.get('reset_timeout', 30)
        self.failures = 0
        self.state = CircuitBreakerState.CLOSED
        self.last_failure_time = None
        self.logger = logging.getLogger(__name__)

    def record_success(self):
        self.failures = 0
        self.state = CircuitBreakerState.CLOSED
        self.logger.info("Circuit breaker recorded success, state: CLOSED")

    def record_failure(self):
        self.failures += 1
        self.last_failure_time = time.time()
        if self.failures >= self.failure_threshold:
            self.state = CircuitBreakerState.OPEN
            self.logger.warning(f"Circuit breaker opened after {self.failures} failures")
        else:
            self.logger.info(f"Circuit breaker recorded failure, current failures: {self.failures}")

    def can_request(self) -> bool:
        if self.state == CircuitBreakerState.CLOSED:
            return True
        if self.state == CircuitBreakerState.OPEN and self.last_failure_time and (time.time() - self.last_failure_time > self.reset_timeout):
            self.state = CircuitBreakerState.HALF_OPEN
            self.logger.info("Circuit breaker state changed to HALF-OPEN")
            return True
        return self.state != CircuitBreakerState.OPEN

class RetryManager:
    def __init__(self, config: Dict[str, Any], health_check: HealthCheck, security_proof: SecurityProof):
        self.config = config
        self.health_check = health_check
        self.security_proof = security_proof
        self.logger = Logger(config).create_logger()
        self.circuit_breaker = CircuitBreaker(config.get('circuit_breaker_options', {}))

        # Prometheus metrics
        self.retry_counter = Counter('retry_attempts_total', 'Total number of retry attempts', ['operation'])
        self.retry_latency = Histogram('retry_latency_seconds', 'Latency of retry operations', ['operation'])

    async def retry(self, fn: Callable, operation_name: str, options: Optional[Dict[str, Any]] = None) -> Any:
        retry_options = {**self.config, **(options or {})}
        attempts = 0
        last_error = None

        start = time.time()

        while attempts < retry_options['max_retries']:
            try:
                if not self.circuit_breaker.can_request():
                    raise RetryError('Circuit breaker is open', Exception('Circuit breaker open'), attempts)

                await self.security_proof.apply_security_measures()

                with self.retry_latency.labels(operation_name).time():
                    result = await asyncio.wait_for(fn(), timeout=retry_options['timeout'])

                end = time.time()
                self.circuit_breaker.record_success()
                self.logger.info(f"Success after {attempts} attempts, duration: {end - start:.2f}s", extra={'operation': operation_name})
                await self.health_check.record_success(operation_name)
                return result

            except (asyncio.TimeoutError, ClientError, ServerTimeoutError) as e:
                last_error = e
                attempts += 1
                self.circuit_breaker.record_failure()
                self.retry_counter.labels(operation_name).inc()
                self.logger.warning(f"Operation timed out (attempt {attempts})", extra={'operation': operation_name, 'error': str(e)})

            except Exception as e:
                last_error = e
                attempts += 1
                self.circuit_breaker.record_failure()
                self.retry_counter.labels(operation_name).inc()

                retry_delay = self.calculate_delay(attempts, retry_options)
                self.logger.warning(f"Retry attempt {attempts}, delay: {retry_delay:.2f}s, error: {str(e)}", 
                                    extra={'operation': operation_name, 'error': str(e)})

                if attempts >= retry_options['max_retries']:
                    break

                await asyncio.sleep(retry_delay)

        end = time.time()
        self.logger.error(f"Failure after {attempts} attempts, duration: {end - start:.2f}s", 
                          extra={'operation': operation_name, 'error': str(last_error)})
        await self.health_check.record_error(operation_name, str(last_error))
        raise RetryError(f"Max retries reached ({retry_options['max_retries']})", last_error, attempts)

    def calculate_delay(self, attempt: int, options: Dict[str, Any]) -> float:
        if options['retry_strategy'] == 'linear':
            delay = options['base_delay'] * attempt
        elif options['retry_strategy'] == 'exponential':
            delay = options['base_delay'] * (2 ** (attempt - 1))
        elif options['retry_strategy'] == 'fibonacci':
            delay = self.fibonacci(attempt) * options['base_delay']
        else:
            delay = options['base_delay']

        # Add jitter to avoid thundering herd problem
        jitter = random.uniform(0, 0.1 * delay)
        delay += jitter

        return min(delay, options['max_delay'])

    def fibonacci(self, n: int) -> int:
        if n <= 1:
            return 1
        a, b = 1, 1
        for _ in range(2, n):
            a, b = b, a + b
        return b


    async def perform_with_retry(self, operation: Callable, operation_name: str) -> Any:
        try:
            return await self.retry(operation, operation_name)
        except RetryError as e:
            self.logger.error(f"Operation {operation_name} failed after multiple retries", extra={'error': str(e)})
            raise

    async def initialize(self):
        self.logger.info("Initializing RetryManager")
        # Any additional initialization logic can be added here

    async def cleanup(self):
        self.logger.info("Cleaning up RetryManager")
        # Any cleanup logic can be added here

    async def __aenter__(self):
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.cleanup()

