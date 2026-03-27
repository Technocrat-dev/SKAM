"""
Prometheus metrics collector — queries Prometheus HTTP API for service metrics.
Uses a persistent aiohttp session to avoid connection churn.
"""

import time
import aiohttp
import logging

logger = logging.getLogger("collector")


class PrometheusCollector:
    """Collects raw metrics from Prometheus for a given service."""

    def __init__(self, prometheus_url: str):
        self.base_url = prometheus_url.rstrip("/")
        self._session: aiohttp.ClientSession | None = None
        self.queries = {
            # Request rate
            "request_rate": 'sum(rate(http_requests_total{{app="{service}"}}[2m]))',
            # Error rate
            "error_rate": 'sum(rate(http_errors_total{{app="{service}"}}[2m]))',
            # p50 latency
            "latency_p50": 'histogram_quantile(0.50, sum(rate(http_request_duration_seconds_bucket{{app="{service}"}}[2m])) by (le))',
            # p99 latency
            "latency_p99": 'histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket{{app="{service}"}}[2m])) by (le))',
            # CPU usage
            "cpu_usage": 'sum(rate(container_cpu_usage_seconds_total{{container="{service}", namespace="default"}}[2m]))',
            # Memory usage (bytes)
            "memory_usage": 'sum(container_memory_usage_bytes{{container="{service}", namespace="default"}})',
            # Pod restart count
            "restart_count": 'sum(kube_pod_container_status_restarts_total{{container="{service}", namespace="default"}})',
            # gRPC request rate (for backend services)
            "grpc_rate": 'sum(rate(grpc_server_handled_total{{grpc_service=~".*{service}.*"}}[2m]))',
            # Active connections (if available)
            "active_connections": 'sum(http_active_connections{{app="{service}"}})',
        }

    async def start_session(self):
        """Create a persistent aiohttp session."""
        if not self._session or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=5),
                connector=aiohttp.TCPConnector(limit=20),
            )

    async def close_session(self):
        """Close the persistent session."""
        if self._session and not self._session.closed:
            await self._session.close()

    async def collect_service_metrics(self, service: str) -> dict:
        """Query Prometheus for all metrics of a service."""
        if not self._session or self._session.closed:
            await self.start_session()

        metrics = {}
        for metric_name, query_template in self.queries.items():
            query = query_template.format(service=service)
            try:
                value = await self._query_instant(query)
                metrics[metric_name] = value
            except Exception as e:
                logger.debug(f"Metric {metric_name} not available for {service}: {e}")
                metrics[metric_name] = 0.0

        return metrics

    async def _query_instant(self, query: str) -> float:
        """Execute an instant query against Prometheus."""
        url = f"{self.base_url}/api/v1/query"
        params = {"query": query}

        async with self._session.get(url, params=params) as resp:
            if resp.status != 200:
                return 0.0

            data = await resp.json()
            results = data.get("data", {}).get("result", [])

            if not results:
                return 0.0

            # Return the first result's value
            value = float(results[0]["value"][1])
            # Handle NaN/Inf
            if value != value or value == float("inf") or value == float("-inf"):
                return 0.0
            return value

    async def collect_range_metrics(self, service: str, duration: str = "30m", step: str = "15s") -> dict:
        """Query Prometheus for range data (for LSTM time series)."""
        if not self._session or self._session.closed:
            await self.start_session()

        metrics = {}
        for metric_name, query_template in self.queries.items():
            query = query_template.format(service=service)
            try:
                values = await self._query_range(query, duration, step)
                metrics[metric_name] = values
            except Exception:
                metrics[metric_name] = []

        return metrics

    async def _query_range(self, query: str, duration: str, step: str) -> list:
        """Execute a range query against Prometheus."""
        url = f"{self.base_url}/api/v1/query_range"
        end = time.time()
        start = end - self._parse_duration(duration)

        params = {"query": query, "start": start, "end": end, "step": step}

        async with self._session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status != 200:
                return []

            data = await resp.json()
            results = data.get("data", {}).get("result", [])

            if not results:
                return []

            return [float(v[1]) for v in results[0]["values"]]

    @staticmethod
    def _parse_duration(duration: str) -> float:
        """Parse Prometheus duration string to seconds."""
        unit = duration[-1]
        value = int(duration[:-1])
        multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400}
        return value * multipliers.get(unit, 60)
