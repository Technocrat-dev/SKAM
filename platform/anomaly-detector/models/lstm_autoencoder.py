"""
LSTM Autoencoder — deep autoencoder for time-series anomaly detection.
Detects anomalies based on reconstruction error. High error = anomalous.

Architecture: Input → Dense(hidden1) → Dense(bottleneck) → Dense(hidden2) → Output
Uses tanh activations, Adam-like optimizer, and percentile-calibrated scoring.
"""

import numpy as np
import logging

logger = logging.getLogger("lstm-autoencoder")


class LSTMAutoencoder:
    """
    Deep autoencoder for anomaly detection.

    3-layer encoder/decoder with tight bottleneck. Trained to minimize
    reconstruction error on normal data so anomalous inputs produce
    distinctly higher errors.
    """

    def __init__(self, sequence_length: int = 10, encoding_dim: int = 4):
        self.sequence_length = sequence_length
        self.encoding_dim = encoding_dim
        self.fitted = False
        self._buffer = []
        self._mean = None
        self._std = None
        self._threshold = None
        self._error_p50 = None
        self._error_p95 = None
        self._min_samples = 20

        # 3-layer autoencoder weights
        self._w1 = None; self._b1 = None
        self._w2 = None; self._b2 = None
        self._w3 = None; self._b3 = None
        self._w4 = None; self._b4 = None

    def _init_weights(self, n_features):
        """Xavier initialization for all layers."""
        rng = np.random.RandomState(42)
        h1 = n_features * 2          # wider hidden layer for better reconstruction
        bn = self.encoding_dim        # tight bottleneck
        h2 = n_features * 2

        self._w1 = rng.randn(n_features, h1) * np.sqrt(2.0 / (n_features + h1))
        self._b1 = np.zeros(h1)
        self._w2 = rng.randn(h1, bn) * np.sqrt(2.0 / (h1 + bn))
        self._b2 = np.zeros(bn)
        self._w3 = rng.randn(bn, h2) * np.sqrt(2.0 / (bn + h2))
        self._b3 = np.zeros(h2)
        self._w4 = rng.randn(h2, n_features) * np.sqrt(2.0 / (h2 + n_features))
        self._b4 = np.zeros(n_features)

    def _forward(self, X):
        """Forward pass through encoder → bottleneck → decoder."""
        z1 = np.tanh(X @ self._w1 + self._b1)
        z2 = np.tanh(z1 @ self._w2 + self._b2)
        z3 = np.tanh(z2 @ self._w3 + self._b3)
        out = z3 @ self._w4 + self._b4
        return z1, z2, z3, out

    def fit(self, X: np.ndarray) -> None:
        """Train the autoencoder on feature matrix."""
        if len(X) < self._min_samples:
            self._buffer.extend(X.tolist())
            return

        # Compute normalization parameters
        self._mean = X.mean(axis=0)
        self._std = X.std(axis=0)
        self._std[self._std < 1e-10] = 1.0

        X_norm = (X - self._mean) / self._std
        n_features = X_norm.shape[1]
        N = len(X_norm)

        self._init_weights(n_features)

        # Adam-like optimizer
        lr = 0.003
        beta1, beta2, eps = 0.9, 0.999, 1e-8
        epochs = 500

        # All parameter groups
        params = [self._w1, self._b1, self._w2, self._b2,
                  self._w3, self._b3, self._w4, self._b4]
        m = [np.zeros_like(p) for p in params]  # first moment
        v = [np.zeros_like(p) for p in params]  # second moment

        for epoch in range(1, epochs + 1):
            # Forward
            z1, z2, z3, out = self._forward(X_norm)
            error = out - X_norm

            # Backprop
            dw4 = z3.T @ error / N
            db4 = error.mean(axis=0)

            d3 = (error @ self._w4.T) * (1 - z3 ** 2)
            dw3 = z2.T @ d3 / N
            db3 = d3.mean(axis=0)

            d2 = (d3 @ self._w3.T) * (1 - z2 ** 2)
            dw2 = z1.T @ d2 / N
            db2 = d2.mean(axis=0)

            d1 = (d2 @ self._w2.T) * (1 - z1 ** 2)
            dw1 = X_norm.T @ d1 / N
            db1 = d1.mean(axis=0)

            grads = [dw1, db1, dw2, db2, dw3, db3, dw4, db4]

            # Adam update
            for i, (p, g) in enumerate(zip(params, grads)):
                np.clip(g, -1.0, 1.0, out=g)
                m[i] = beta1 * m[i] + (1 - beta1) * g
                v[i] = beta2 * v[i] + (1 - beta2) * (g ** 2)
                m_hat = m[i] / (1 - beta1 ** epoch)
                v_hat = v[i] / (1 - beta2 ** epoch)
                p -= lr * m_hat / (np.sqrt(v_hat) + eps)

        # Compute reconstruction error distribution on training data
        _, _, _, decoded = self._forward(X_norm)
        errors = np.mean((X_norm - decoded) ** 2, axis=1)

        self._error_p50 = np.percentile(errors, 50)
        self._error_p95 = np.percentile(errors, 95)
        self._threshold = self._error_p95

        self.fitted = True
        logger.info(
            f"LSTM Autoencoder trained on {len(X)} samples, "
            f"p50_err={self._error_p50:.6f}, p95_err={self._error_p95:.6f}"
        )

    def score(self, X: np.ndarray) -> float:
        """Score a single observation. Returns 0.0-1.0 (higher=more anomalous)."""
        if not self.fitted:
            self._buffer.extend(X.tolist())
            return 0.0

        X_norm = (X - self._mean) / self._std
        _, _, _, decoded = self._forward(X_norm)

        recon_error = float(np.mean((X_norm - decoded) ** 2))

        # Percentile-calibrated scoring:
        # Errors below p50 → score near 0
        # Errors at p95 → score ~0.7
        # Errors well above p95 → score → 1.0
        #
        # Use a shifted/scaled sigmoid centered at p95:
        scale = max(self._error_p95 - self._error_p50, 1e-10)
        z = (recon_error - self._error_p95) / scale

        # Sigmoid: z=0 → 0.5, z=1 → 0.73, z=2 → 0.88, z=-1 → 0.27
        # Then shift so that p95 maps to ~0.5
        raw = 1.0 / (1.0 + np.exp(-2.0 * z))

        # Normal samples (error < p50) should score very low
        if recon_error < self._error_p50:
            # Linear ramp from 0 to 0.15
            anomaly_score = 0.15 * (recon_error / max(self._error_p50, 1e-10))
        elif recon_error < self._error_p95:
            # Linear ramp from 0.15 to 0.5
            frac = (recon_error - self._error_p50) / max(self._error_p95 - self._error_p50, 1e-10)
            anomaly_score = 0.15 + 0.35 * frac
        else:
            # Above p95: sigmoid from 0.5 upward
            anomaly_score = 0.5 + 0.5 * raw

        return float(np.clip(anomaly_score, 0.0, 1.0))

    def partial_fit(self, X: np.ndarray) -> None:
        """Incrementally update with new observations."""
        self._buffer.extend(X.tolist())
        if len(self._buffer) > self._min_samples * 2:
            full_data = np.array(self._buffer[-500:])
            self.fit(full_data)
            self._buffer = self._buffer[-500:]
