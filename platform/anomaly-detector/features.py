"""
Feature engineering pipeline — transforms raw Prometheus metrics
into ML-ready feature vectors with derived signals.
"""

import numpy as np
from collections import deque


class FeatureEngineer:
    """Extracts and engineers features from raw Prometheus metrics."""

    def __init__(self, window_size: int = 20):
        self.window_size = window_size
        # Rolling windows per service per metric
        self._history: dict[str, dict[str, deque]] = {}

    def extract(self, raw_metrics: dict, service: str) -> dict:
        """Transform raw metrics into feature vector."""
        if service not in self._history:
            self._history[service] = {k: deque(maxlen=self.window_size) for k in raw_metrics}

        # Store in rolling window
        for k, v in raw_metrics.items():
            if k not in self._history[service]:
                self._history[service][k] = deque(maxlen=self.window_size)
            self._history[service][k].append(v)

        features = {}

        # ─── Raw metrics (normalized) ────────────────────────
        features["request_rate"] = raw_metrics.get("request_rate", 0.0)
        features["error_rate"] = raw_metrics.get("error_rate", 0.0)
        features["latency_p50"] = raw_metrics.get("latency_p50", 0.0)
        features["latency_p99"] = raw_metrics.get("latency_p99", 0.0)
        features["cpu_usage"] = raw_metrics.get("cpu_usage", 0.0)
        features["memory_usage_mb"] = raw_metrics.get("memory_usage", 0.0) / (1024 * 1024)
        features["restart_count"] = raw_metrics.get("restart_count", 0.0)

        # ─── Derived features ────────────────────────────────

        # Error ratio (error_rate / request_rate)
        req_rate = features["request_rate"]
        features["error_ratio"] = (
            features["error_rate"] / req_rate if req_rate > 0 else 0.0
        )

        # Latency spread (p99-p50 gap indicates tail latency issues)
        features["latency_spread"] = features["latency_p99"] - features["latency_p50"]

        # ─── Statistical features (from rolling window) ──────

        history = self._history[service]

        # Request rate z-score (how far from recent mean)
        features["request_rate_zscore"] = self._zscore(history.get("request_rate", deque()))

        # Error rate z-score
        features["error_rate_zscore"] = self._zscore(history.get("error_rate", deque()))

        # Latency p99 z-score
        features["latency_p99_zscore"] = self._zscore(history.get("latency_p99", deque()))

        # CPU usage z-score
        features["cpu_zscore"] = self._zscore(history.get("cpu_usage", deque()))

        # Rate of change (derivative) for request rate
        features["request_rate_delta"] = self._rate_of_change(history.get("request_rate", deque()))

        # Rate of change for error rate
        features["error_rate_delta"] = self._rate_of_change(history.get("error_rate", deque()))

        # Rate of change for latency
        features["latency_delta"] = self._rate_of_change(history.get("latency_p99", deque()))

        return features

    @staticmethod
    def _zscore(window: deque) -> float:
        """Compute z-score of the latest value in a rolling window."""
        if len(window) < 3:
            return 0.0
        arr = np.array(list(window))
        mean = arr.mean()
        std = arr.std()
        if std < 1e-10:
            return 0.0
        return float((arr[-1] - mean) / std)

    @staticmethod
    def _rate_of_change(window: deque) -> float:
        """Compute rate of change between last two values."""
        if len(window) < 2:
            return 0.0
        prev = window[-2]
        curr = window[-1]
        if abs(prev) < 1e-10:
            return 0.0
        return float((curr - prev) / abs(prev))
