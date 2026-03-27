# ML Pipeline Validation Benchmark

Generated: 2026-03-28 02:27:01

## Methodology

| | Approach A (Baseline) | Approach B (Proposed) |
|---|---|---|
| **Name** | Pure Synthetic | Real-Data-Derived Synthetic |
| **Training Data** | Random Gaussian (arbitrary μ/σ) | Multivariate Gaussian fitted to real TrainTicket Prometheus KPIs |
| **Correlations** | None (independent features) | Preserved (real cross-feature covariance) |
| **Calibration** | Not calibrated to any real system | Calibrated to real microservice behavior |

**Ground truth**: Real labeled observations from TrainTicket experiment
`ts-auth-mongo_MongoDB_4.4.15_2022-07-27` (34 timesteps × 7 services,
anomaly window at rows 21-25 on api-gateway and product-service).

---

## Aggregate Results

| Metric | Approach A (Pure Synthetic) | Approach B (Real-Derived) | Winner |
|--------|---------------------------|--------------------------|--------|
| Precision | 0.0420 | 0.2211 | **B** |
| Recall | 0.2857 | 0.2857 | Tie |
| F1 Score | 0.0733 | 0.2489 | **B** |
| Accuracy | 0.0420 | 0.9202 | **B** |
| AUC-ROC | 0.5640 | 0.6389 | **B** |
| Avg Precision (AUC-PR) | 0.0744 | 0.2648 | **B** |
| Score Separation | 0.0000 | 0.2180 | **B** |
| Mean Normal Score | 1.0000 | 0.2515 | **B** |
| Mean Anomaly Score | 0.2857 | 0.2857 | Tie |

**Overall Winner: Approach B (Real-Data-Derived Synthetic)**
(Approach A wins 0/7 metrics, Approach B wins 7/7 metrics)

---

## Threshold Sensitivity (Averaged Across Services)

| Threshold | A: Precision | A: Recall | A: F1 | B: Precision | B: Recall | B: F1 |
|-----------|-------------|----------|-------|-------------|----------|-------|
| t=0.5 | 0.0420 | 0.2857 | 0.0733 | 0.1508 | 0.2857 | 0.1973 |
| t=0.6 | 0.0420 | 0.2857 | 0.0733 | 0.1687 | 0.2857 | 0.2119 |
| t=0.7 | 0.0420 | 0.2857 | 0.0733 | 0.2211 | 0.2857 | 0.2489 |
| t=0.8 | 0.0420 | 0.2857 | 0.0733 | 0.2211 | 0.2857 | 0.2489 |

---

## Per-Service Breakdown

### api-gateway

Test data: 34 samples (5 anomalies)

| Metric | Approach A | Approach B |
|--------|-----------|-----------|
| AUC-ROC | 0.7241 | 0.9862 |
| Avg Precision | 0.2604 | 0.9267 |
| F1 (t=0.7) | 0.2564 | 0.8333 |
| Score Sep. | 0.0000 | 0.7507 |
| Train time | 503.5ms | 758.1ms |

### user-service

Test data: 34 samples (0 anomalies)

| Metric | Approach A | Approach B |
|--------|-----------|-----------|
| AUC-ROC | 0.5000 | 0.5000 |
| Avg Precision | 0.0000 | 0.0000 |
| F1 (t=0.7) | 0.0000 | 0.0000 |
| Score Sep. | 0.0000 | 0.0000 |
| Train time | 485.9ms | 789.9ms |

### product-service

Test data: 34 samples (5 anomalies)

| Metric | Approach A | Approach B |
|--------|-----------|-----------|
| AUC-ROC | 0.7241 | 0.9862 |
| Avg Precision | 0.2604 | 0.9267 |
| F1 (t=0.7) | 0.2564 | 0.9091 |
| Score Sep. | 0.0000 | 0.7755 |
| Train time | 515.2ms | 890.3ms |

### order-service

Test data: 34 samples (0 anomalies)

| Metric | Approach A | Approach B |
|--------|-----------|-----------|
| AUC-ROC | 0.5000 | 0.5000 |
| Avg Precision | 0.0000 | 0.0000 |
| F1 (t=0.7) | 0.0000 | 0.0000 |
| Score Sep. | 0.0000 | 0.0000 |
| Train time | 518.6ms | 825.6ms |

### cart-service

Test data: 34 samples (0 anomalies)

| Metric | Approach A | Approach B |
|--------|-----------|-----------|
| AUC-ROC | 0.5000 | 0.5000 |
| Avg Precision | 0.0000 | 0.0000 |
| F1 (t=0.7) | 0.0000 | 0.0000 |
| Score Sep. | 0.0000 | 0.0000 |
| Train time | 513.4ms | 911.0ms |

### payment-service

Test data: 34 samples (0 anomalies)

| Metric | Approach A | Approach B |
|--------|-----------|-----------|
| AUC-ROC | 0.5000 | 0.5000 |
| Avg Precision | 0.0000 | 0.0000 |
| F1 (t=0.7) | 0.0000 | 0.0000 |
| Score Sep. | 0.0000 | 0.0000 |
| Train time | 480.7ms | 775.3ms |

### notification-service

Test data: 34 samples (0 anomalies)

| Metric | Approach A | Approach B |
|--------|-----------|-----------|
| AUC-ROC | 0.5000 | 0.5000 |
| Avg Precision | 0.0000 | 0.0000 |
| F1 (t=0.7) | 0.0000 | 0.0000 |
| Score Sep. | 0.0000 | 0.0000 |
| Train time | 529.4ms | 738.9ms |

---

## Analysis

**Approach B (Real-Data-Derived Synthetic) is the recommended approach.**

Key advantages:
- Training data mirrors real microservice resource consumption patterns
- Cross-feature correlations (e.g., CPU↔latency, error_rate↔restart_count) are preserved
- The model's learned 'normal baseline' is calibrated to actual Prometheus metric ranges
- Better score separation between normal and anomalous samples reduces false positives

### Why Real-Data-Derived Synthetic Training Matters

1. **Distribution alignment**: The model sees data during training that
   follows the same statistical distributions it will encounter in production
2. **Feature correlation preservation**: Real systems have correlated metrics
   (e.g., high CPU usage correlates with high latency). Pure synthetic data
   with independent features can't capture this.
3. **Threshold calibration**: Anomaly thresholds (0.7) are meaningful when
   the model's reconstruction error scale matches real-world baselines
4. **Generalization**: Models trained on real distributions generalize
   better to unseen anomaly patterns than models trained on arbitrary ranges