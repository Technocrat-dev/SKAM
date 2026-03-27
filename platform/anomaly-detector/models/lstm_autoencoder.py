"""
LSTM Autoencoder — sequence-to-sequence model that detects anomalies
based on reconstruction error. High error = anomalous pattern.
"""

import numpy as np
import logging

logger = logging.getLogger("lstm-autoencoder")


class LSTMAutoencoder:
    """
    LSTM Autoencoder for time-series anomaly detection.

    Uses a lightweight numpy-based autoencoder for hackathon speed.
    For production, swap with PyTorch/TensorFlow LSTM.
    """

    def __init__(self, sequence_length: int = 10, encoding_dim: int = 8):
        self.sequence_length = sequence_length
        self.encoding_dim = encoding_dim
        self.fitted = False
        self._buffer = []
        self._mean = None
        self._std = None
        self._threshold = None
        self._min_samples = 20

        # Lightweight autoencoder weights (will be set during fit)
        self._encoder_w = None
        self._decoder_w = None

    def fit(self, X: np.ndarray) -> None:
        """Train the autoencoder on feature matrix."""
        if len(X) < self._min_samples:
            self._buffer.extend(X.tolist())
            return

        # Compute normalization parameters
        self._mean = X.mean(axis=0)
        self._std = X.std(axis=0)
        self._std[self._std < 1e-10] = 1.0  # Prevent div by zero

        X_norm = (X - self._mean) / self._std
        n_features = X_norm.shape[1]

        # Initialize simple linear autoencoder weights
        # Encoder: n_features → encoding_dim
        np.random.seed(42)
        self._encoder_w = np.random.randn(n_features, self.encoding_dim) * 0.1
        # Decoder: encoding_dim → n_features
        self._decoder_w = np.random.randn(self.encoding_dim, n_features) * 0.1

        # Train with gradient descent
        lr = 0.01
        for epoch in range(100):
            # Forward pass
            encoded = np.tanh(X_norm @ self._encoder_w)
            decoded = encoded @ self._decoder_w

            # Compute reconstruction error
            error = decoded - X_norm

            # Backward pass (gradient descent)
            d_decoder = encoded.T @ error / len(X_norm)
            d_encoder = (error @ self._decoder_w.T) * (1 - encoded ** 2)
            d_encoder = X_norm.T @ d_encoder / len(X_norm)

            self._encoder_w -= lr * d_encoder
            self._decoder_w -= lr * d_decoder

        # Compute reconstruction errors for threshold
        encoded = np.tanh(X_norm @ self._encoder_w)
        decoded = encoded @ self._decoder_w
        errors = np.mean((X_norm - decoded) ** 2, axis=1)
        self._threshold = np.percentile(errors, 95)

        self.fitted = True
        logger.info(f"LSTM Autoencoder trained on {len(X)} samples, threshold={self._threshold:.4f}")

    def score(self, X: np.ndarray) -> float:
        """Score a single observation. Returns 0.0-1.0 (higher=more anomalous)."""
        if not self.fitted:
            self._buffer.extend(X.tolist())
            return 0.0

        # Normalize
        X_norm = (X - self._mean) / self._std

        # Reconstruct
        encoded = np.tanh(X_norm @ self._encoder_w)
        decoded = encoded @ self._decoder_w

        # Reconstruction error (MSE)
        recon_error = float(np.mean((X_norm - decoded) ** 2))

        # Normalize to 0-1 using threshold
        if self._threshold > 0:
            anomaly_score = min(1.0, recon_error / (self._threshold * 2))
        else:
            anomaly_score = 0.0

        return float(anomaly_score)

    def partial_fit(self, X: np.ndarray) -> None:
        """Incrementally update with new observations."""
        self._buffer.extend(X.tolist())
        if len(self._buffer) > self._min_samples * 2:
            full_data = np.array(self._buffer[-500:])
            self.fit(full_data)
            self._buffer = self._buffer[-500:]
