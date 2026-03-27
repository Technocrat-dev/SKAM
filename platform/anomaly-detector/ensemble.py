"""
Ensemble scorer — combines Isolation Forest and LSTM Autoencoder
scores using weighted averaging with adaptive boosting.
"""

import logging

logger = logging.getLogger("ensemble")


class EnsembleScorer:
    """Combines multiple detector scores with adaptive signal boosting."""

    def __init__(self, weights: dict = None):
        self.weights = weights or {"isoforest": 0.4, "lstm": 0.6}

    def combine(self, isoforest_score: float, lstm_score: float) -> float:
        """Weighted combination with agreement boosting.
        
        When both detectors agree (both high or both low), the signal
        is strengthened. When they disagree, the result is dampened.
        """
        w_iso = self.weights.get("isoforest", 0.4)
        w_lstm = self.weights.get("lstm", 0.6)

        # Weighted average
        combined = (w_iso * isoforest_score + w_lstm * lstm_score) / (w_iso + w_lstm)

        # Agreement factor: how much do both models agree?
        # Both high → boost up, both low → keep low, disagreement → pull toward center
        agreement = 1.0 - abs(isoforest_score - lstm_score)

        # When models agree on anomaly (both > 0.5), boost the signal
        if isoforest_score > 0.5 and lstm_score > 0.5:
            boost = agreement * 0.15
            combined = min(1.0, combined + boost)
        # When models agree on normal (both < 0.3), suppress false positives
        elif isoforest_score < 0.3 and lstm_score < 0.3:
            combined *= (0.85 + 0.15 * agreement)

        return min(1.0, max(0.0, combined))
