"""
Policy engine — defines and evaluates self-healing policies.
Each policy maps anomaly patterns to recovery actions.
"""

import logging

logger = logging.getLogger("policies")


class PolicyEngine:
    """Evaluates anomaly data against defined healing policies."""

    def __init__(self):
        self.policies = self._load_default_policies()

    def _load_default_policies(self) -> list[dict]:
        """Load built-in self-healing policies."""
        return [
            # ─── Critical: Service completely down ───────────
            {
                "name": "service_down_restart",
                "description": "Restart pods when service is completely unresponsive",
                "condition": lambda svc, score, data: (
                    score > 0.9 and
                    data.get("features", {}).get("request_rate", 0) < 0.01
                ),
                "action": "restart_pods",
                "priority": 100,
                "max_risk": "high",
            },

            # ─── High error rate → scale up replicas ────────
            {
                "name": "high_error_rate_scale",
                "description": "Scale up when error ratio exceeds 20%",
                "condition": lambda svc, score, data: (
                    score > 0.7 and
                    data.get("features", {}).get("error_ratio", 0) > 0.2
                ),
                "action": "scale_up",
                "priority": 80,
                "max_risk": "medium",
            },

            # ─── High latency → scale up ────────────────────
            {
                "name": "high_latency_scale",
                "description": "Scale up when p99 latency exceeds 2s",
                "condition": lambda svc, score, data: (
                    score > 0.6 and
                    data.get("features", {}).get("latency_p99", 0) > 2.0
                ),
                "action": "scale_up",
                "priority": 70,
                "max_risk": "low",
            },

            # ─── CPU saturation → scale up ──────────────────
            {
                "name": "cpu_saturation_scale",
                "description": "Scale up when CPU z-score is very high",
                "condition": lambda svc, score, data: (
                    score > 0.6 and
                    data.get("features", {}).get("cpu_zscore", 0) > 2.5
                ),
                "action": "scale_up",
                "priority": 60,
                "max_risk": "low",
            },

            # ─── Pod restarts → rolling restart deployment ──
            {
                "name": "restart_loop_rollback",
                "description": "Rolling restart when pod restart count spikes",
                "condition": lambda svc, score, data: (
                    score > 0.7 and
                    data.get("features", {}).get("restart_count", 0) > 3
                ),
                "action": "rolling_restart",
                "priority": 90,
                "max_risk": "medium",
            },

            # ─── Memory pressure → adjust limits ────────────
            {
                "name": "memory_spike_adjust",
                "description": "Increase memory limits when usage is critical",
                "condition": lambda svc, score, data: (
                    score > 0.65 and
                    data.get("features", {}).get("memory_usage_mb", 0) > 200
                ),
                "action": "increase_memory",
                "priority": 50,
                "max_risk": "medium",
            },
        ]

    def evaluate(self, service: str, score: float, data: dict) -> dict | None:
        """Evaluate all policies and return the highest-priority match."""
        matches = []

        for policy in self.policies:
            try:
                if policy["condition"](service, score, data):
                    matches.append(policy)
            except Exception as e:
                logger.debug(f"Policy {policy['name']} evaluation error: {e}")

        if not matches:
            return None

        # Return highest priority match
        best = max(matches, key=lambda p: p["priority"])
        logger.info(f"📋 Policy matched for {service}: {best['name']} (priority={best['priority']})")
        return best

    def list_policies(self) -> list[dict]:
        """Return serializable policy list (without lambda)."""
        return [
            {
                "name": p["name"],
                "description": p["description"],
                "action": p["action"],
                "priority": p["priority"],
                "max_risk": p["max_risk"],
            }
            for p in self.policies
        ]

    def count(self) -> int:
        return len(self.policies)
