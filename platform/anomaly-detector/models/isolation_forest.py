"""
Isolation Forest Anomaly Detector — unsupervised model that
identifies anomalies as points isolated from the majority.
"""

import numpy as np
import logging
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

logger = logging.getLogger("isoforest")


class IsolationForestDetector:
    """Isolation Forest wrapper with online learning support."""

    def __init__(self, contamination: float = 0.05, n_estimators: int = 100):
        self.contamination = contamination
        self.n_estimators = n_estimators
        self.model = None
        self.scaler = StandardScaler()
        self.fitted = False
        self._training_buffer = []
        self._min_samples = 20

    def fit(self, X: np.ndarray) -> None:
        """Train the Isolation Forest on feature matrix."""
        if len(X) < self._min_samples:
            self._training_buffer.extend(X.tolist())
            if len(self._training_buffer) >= self._min_samples:
                X = np.array(self._training_buffer)
            else:
                return

        self.scaler.fit(X)
        X_scaled = self.scaler.transform(X)

        self.model = IsolationForest(
            contamination=self.contamination,
            n_estimators=self.n_estimators,
            random_state=42,
            warm_start=False,
        )
        self.model.fit(X_scaled)
        self.fitted = True
        logger.info(f"Isolation Forest trained on {len(X)} samples")

    def score(self, X: np.ndarray) -> float:
        """Score a single observation. Returns 0.0-1.0 (higher=more anomalous)."""
        if not self.fitted:
            # Add to buffer for future training
            self._training_buffer.extend(X.tolist())
            return 0.0

        X_scaled = self.scaler.transform(X)

        # sklearn decision_function: negative = anomaly, positive = normal
        raw_score = self.model.decision_function(X_scaled)[0]

        # Convert to 0-1 range: more negative → closer to 1.0
        # Typical range is roughly -0.5 to 0.5
        anomaly_score = max(0.0, min(1.0, 0.5 - raw_score))

        return float(anomaly_score)

    def partial_fit(self, X: np.ndarray) -> None:
        """Incrementally update the model with new data."""
        self._training_buffer.extend(X.tolist())

        # Retrain periodically when buffer grows
        if len(self._training_buffer) > self._min_samples * 2:
            full_data = np.array(self._training_buffer[-500:])  # Keep last 500
            self.fit(full_data)
            self._training_buffer = self._training_buffer[-500:]
