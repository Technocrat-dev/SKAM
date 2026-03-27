"""
Isolation Forest Anomaly Detector — unsupervised model that
identifies anomalies as points isolated from the majority.

Uses sklearn IsolationForest with percentile-calibrated 3-zone scoring.
"""

import numpy as np
import logging
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import RobustScaler

logger = logging.getLogger("isoforest")


class IsolationForestDetector:
    """Isolation Forest wrapper with calibrated 3-zone score output."""

    def __init__(self, contamination: float = 0.05, n_estimators: int = 200):
        self.contamination = contamination
        self.n_estimators = n_estimators
        self.model = None
        self.scaler = RobustScaler()
        self.fitted = False
        self._training_buffer = []
        self._min_samples = 20
        self._score_p5 = 0.0    # 5th percentile of decision scores (most anomalous training)
        self._score_p50 = 0.0   # median decision score (typical normal)
        self._score_p95 = 0.0   # 95th percentile (most normal)

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
            max_samples=min(256, len(X)),
            random_state=42,
            warm_start=False,
        )
        self.model.fit(X_scaled)

        # Calibrate using training data decision scores
        raw_scores = self.model.decision_function(X_scaled)
        self._score_p5 = np.percentile(raw_scores, 5)
        self._score_p50 = np.percentile(raw_scores, 50)
        self._score_p95 = np.percentile(raw_scores, 95)

        self.fitted = True
        logger.info(
            f"Isolation Forest trained on {len(X)} samples, "
            f"p5={self._score_p5:.4f} p50={self._score_p50:.4f} p95={self._score_p95:.4f}"
        )

    def score(self, X: np.ndarray) -> float:
        """Score a single observation. Returns 0.0-1.0 (higher=more anomalous).
        
        3-zone scoring calibrated to training distribution:
        - Above p50 → 0.0-0.15 (clearly normal)
        - Between p5-p50 → 0.15-0.50 (borderline)
        - Below p5 → 0.50-1.0 (anomalous, outside training range)
        """
        if not self.fitted:
            self._training_buffer.extend(X.tolist())
            return 0.0

        X_scaled = self.scaler.transform(X)
        raw_score = self.model.decision_function(X_scaled)[0]

        # Higher raw_score = more normal, lower = more anomalous
        if raw_score >= self._score_p50:
            # Clearly normal — score near 0
            if self._score_p95 > self._score_p50:
                frac = min(1.0, (raw_score - self._score_p50) / (self._score_p95 - self._score_p50))
            else:
                frac = 1.0
            anomaly_score = 0.15 * (1.0 - frac)
        elif raw_score >= self._score_p5:
            # Borderline - between normal and edge of training distribution
            range_val = max(self._score_p50 - self._score_p5, 1e-10)
            frac = (self._score_p50 - raw_score) / range_val
            anomaly_score = 0.15 + 0.35 * frac
        else:
            # Below p5 — outside training distribution → anomalous
            range_val = max(self._score_p50 - self._score_p5, 1e-10)
            excess = (self._score_p5 - raw_score) / range_val
            # Sigmoid for smooth 0.5 → 1.0 mapping
            anomaly_score = 0.5 + 0.5 * (1.0 / (1.0 + np.exp(-3.0 * excess)))

        return float(np.clip(anomaly_score, 0.0, 1.0))

    def partial_fit(self, X: np.ndarray) -> None:
        """Incrementally update the model with new data."""
        self._training_buffer.extend(X.tolist())

        if len(self._training_buffer) > self._min_samples * 2:
            full_data = np.array(self._training_buffer[-500:])
            self.fit(full_data)
            self._training_buffer = self._training_buffer[-500:]
