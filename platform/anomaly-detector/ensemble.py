"""
Ensemble scorer — combines Isolation Forest and LSTM Autoencoder
scores using weighted averaging.
"""

import logging

logger = logging.getLogger("ensemble")


class EnsembleScorer:
    """Combines multiple detector scores into a single anomaly score."""

    def __init__(self, weights: dict = None):
        self.weights = weights or {"isoforest": 0.4, "lstm": 0.6}

    def combine(self, isoforest_score: float, lstm_score: float) -> float:
        """Weighted combination of detector scores."""
        w_iso = self.weights.get("isoforest", 0.4)
        w_lstm = self.weights.get("lstm", 0.6)

        # Weighted average
        combined = (w_iso * isoforest_score + w_lstm * lstm_score) / (w_iso + w_lstm)

        # Apply non-linear scaling: amplify strong signals
        # If either detector is very confident (>0.8), boost the ensemble score
        max_score = max(isoforest_score, lstm_score)
        if max_score > 0.8:
            combined = max(combined, max_score * 0.9)

        return min(1.0, max(0.0, combined))
