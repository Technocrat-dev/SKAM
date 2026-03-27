"""
Risk assessor — evaluates whether a healing action is safe to execute
based on service criticality, recent history, and cluster state.
"""

import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("risk")


class RiskAssessor:
    """Assesses risk before executing recovery actions."""

    def __init__(self):
        # Track recent actions per service for backoff
        self._action_history: dict[str, list[datetime]] = {}

        # Service criticality tiers
        self._criticality = {
            "api-gateway": "critical",      # Single entry point
            "payment-service": "critical",   # Financial data
            "order-service": "high",
            "user-service": "high",
            "product-service": "medium",
            "cart-service": "medium",
            "notification-service": "low",
        }

    def assess(self, service: str, policy: dict, anomaly_score: float) -> str:
        """
        Returns risk level: 'low', 'medium', 'high', or 'blocked'.
        'blocked' means the action should NOT be executed.
        """
        risk_factors = []

        # 1. Service criticality
        criticality = self._criticality.get(service, "medium")
        if criticality == "critical":
            risk_factors.append(("service_criticality", 0.3))
        elif criticality == "high":
            risk_factors.append(("service_criticality", 0.2))
        else:
            risk_factors.append(("service_criticality", 0.1))

        # 2. Action aggressiveness
        aggressive_actions = {"restart_pods": 0.3, "rolling_restart": 0.2, "increase_memory": 0.15, "scale_up": 0.1}
        action_risk = aggressive_actions.get(policy["action"], 0.1)
        risk_factors.append(("action_type", action_risk))

        # 3. Recent action frequency (circuit breaker)
        recent_count = self._count_recent_actions(service, minutes=10)
        if recent_count >= 3:
            logger.warning(f"🚫 Circuit breaker: {service} had {recent_count} actions in 10m")
            return "blocked"
        frequency_risk = recent_count * 0.15
        risk_factors.append(("action_frequency", frequency_risk))

        # 4. Anomaly score confidence
        # Lower scores → less confidence → higher risk
        if anomaly_score < 0.75:
            risk_factors.append(("low_confidence", 0.15))
        else:
            risk_factors.append(("high_confidence", 0.0))

        # Calculate total risk
        total_risk = sum(r[1] for r in risk_factors)

        # Determine level
        if total_risk >= 0.6:
            level = "high"
        elif total_risk >= 0.3:
            level = "medium"
        else:
            level = "low"

        # Check against policy max_risk
        risk_order = {"low": 0, "medium": 1, "high": 2}
        max_risk = policy.get("max_risk", "high")
        if risk_order.get(level, 0) > risk_order.get(max_risk, 2):
            logger.warning(f"🚫 Risk too high for policy {policy['name']}: {level} > {max_risk}")
            return "blocked"

        # Record this action
        self._record_action(service)

        logger.info(f"⚖️ Risk assessment for {service}: {level} (score={total_risk:.2f}, factors={risk_factors})")
        return level

    def _count_recent_actions(self, service: str, minutes: int) -> int:
        """Count actions for a service in the last N minutes."""
        if service not in self._action_history:
            return 0
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        recent = [t for t in self._action_history[service] if t > cutoff]
        self._action_history[service] = recent  # Prune old entries
        return len(recent)

    def _record_action(self, service: str):
        """Record that an action was taken for a service."""
        if service not in self._action_history:
            self._action_history[service] = []
        self._action_history[service].append(datetime.now(timezone.utc))
