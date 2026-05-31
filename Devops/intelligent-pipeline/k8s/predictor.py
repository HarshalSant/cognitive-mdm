"""
Predictive Scaling Engine -- forecasts load spikes and recommends
pre-emptive scaling actions before traffic arrives.

Uses exponential smoothing + time-of-day patterns.
No ML framework required -- pure Python signal processing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any


@dataclass
class ScalingRecommendation:
    workload: str
    namespace: str
    current_replicas: int
    recommended_replicas: int
    confidence: float
    reason: str
    predicted_load_pct: float
    action: str
    urgency: str
    schedule_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "workload": self.workload,
            "namespace": self.namespace,
            "current_replicas": self.current_replicas,
            "recommended_replicas": self.recommended_replicas,
            "confidence": round(self.confidence, 3),
            "reason": self.reason,
            "predicted_load_pct": round(self.predicted_load_pct, 1),
            "action": self.action,
            "urgency": self.urgency,
            "schedule_at": self.schedule_at.isoformat() if self.schedule_at else None,
            "kubectl_command": self._kubectl_cmd(),
        }

    def _kubectl_cmd(self) -> str:
        return (
            f"kubectl scale deployment/{self.workload} "
            f"--replicas={self.recommended_replicas} "
            f"-n {self.namespace}"
        )


class PredictiveScaler:
    """
    Forecasts resource demand using historical metrics and time-based patterns.
    Generates pre-emptive scaling recommendations with lead time.
    """

    def __init__(self, alpha: float = 0.3) -> None:
        self._alpha = alpha

    def predict_and_recommend(
        self,
        workload: str,
        namespace: str,
        current_replicas: int,
        metrics_history: list[dict[str, Any]],
        lookahead_minutes: int = 30,
        scale_up_threshold: float = 0.70,
        scale_down_threshold: float = 0.30,
        min_replicas: int = 1,
        max_replicas: int = 20,
    ) -> ScalingRecommendation | None:
        if len(metrics_history) < 3:
            return None

        cpu_values = [m.get("cpu_utilization", 0.0) for m in metrics_history]
        predicted_cpu = self._exponential_smoothing_forecast(cpu_values, lookahead_minutes)
        mem_values = [m.get("memory_utilization", 0.0) for m in metrics_history]
        predicted_mem = self._exponential_smoothing_forecast(mem_values, lookahead_minutes)

        time_multiplier = self._time_of_day_multiplier(lookahead_minutes)
        predicted_load = max(predicted_cpu, predicted_mem) * time_multiplier
        predicted_load = min(1.0, predicted_load)

        confidence = self._estimate_confidence(cpu_values)

        if predicted_load > scale_up_threshold:
            scale_factor = predicted_load / scale_up_threshold
            recommended = min(max_replicas, math.ceil(current_replicas * scale_factor))
            if recommended <= current_replicas:
                return None
            schedule_at = datetime.now(timezone.utc) + timedelta(
                minutes=max(0, lookahead_minutes - 10)
            )
            return ScalingRecommendation(
                workload=workload,
                namespace=namespace,
                current_replicas=current_replicas,
                recommended_replicas=recommended,
                confidence=confidence,
                reason=(
                    f"Predicted load {predicted_load*100:.0f}% in {lookahead_minutes}m "
                    f"(CPU: {predicted_cpu*100:.0f}%, Mem: {predicted_mem*100:.0f}%)"
                ),
                predicted_load_pct=predicted_load * 100,
                action="SCALE_UP",
                urgency="HIGH" if predicted_load > 0.85 else "MEDIUM",
                schedule_at=schedule_at,
            )

        if predicted_load < scale_down_threshold and current_replicas > min_replicas:
            recommended = max(min_replicas, math.floor(current_replicas * 0.6))
            if recommended >= current_replicas:
                return None
            schedule_at = datetime.now(timezone.utc) + timedelta(minutes=15)
            return ScalingRecommendation(
                workload=workload,
                namespace=namespace,
                current_replicas=current_replicas,
                recommended_replicas=recommended,
                confidence=confidence * 0.8,
                reason=f"Predicted load {predicted_load*100:.0f}% -- over-provisioned",
                predicted_load_pct=predicted_load * 100,
                action="SCALE_DOWN",
                urgency="LOW",
                schedule_at=schedule_at,
            )

        return None

    def _exponential_smoothing_forecast(
        self, values: list[float], steps_ahead: int = 1
    ) -> float:
        if not values:
            return 0.0
        smoothed = values[0]
        for v in values[1:]:
            smoothed = self._alpha * v + (1 - self._alpha) * smoothed
        trend = 0.0
        if len(values) >= 2:
            recent_slope = (values[-1] - values[-3]) / 2 if len(values) >= 3 else (values[-1] - values[-2])
            trend = recent_slope * (steps_ahead / len(values))
        return max(0.0, min(1.0, smoothed + trend))

    def _time_of_day_multiplier(self, minutes_ahead: int) -> float:
        now = datetime.now(timezone.utc)
        future = now + timedelta(minutes=minutes_ahead)
        hour = future.hour
        weekday = future.weekday()
        if weekday >= 5:
            return 0.6
        if 9 <= hour <= 11 or 14 <= hour <= 16:
            return 1.3
        if 12 <= hour <= 13:
            return 1.1
        if hour < 7 or hour >= 22:
            return 0.5
        return 1.0

    def _estimate_confidence(self, values: list[float]) -> float:
        if len(values) < 3:
            return 0.4
        mean = sum(values) / len(values)
        if mean == 0:
            return 0.5
        variance = sum((v - mean) ** 2 for v in values) / len(values)
        cv = math.sqrt(variance) / (mean + 1e-9)
        confidence = max(0.3, min(0.95, 1.0 - cv))
        length_bonus = min(0.1, len(values) * 0.005)
        return confidence + length_bonus

    def analyze_hpa_effectiveness(
        self, hpa_events: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """
        Analyse HPA scaling events to determine if current HPA config is effective.
        """
        scale_ups = [e for e in hpa_events if e.get("type") == "ScaleUp"]
        scale_downs = [e for e in hpa_events if e.get("type") == "ScaleDown"]
        thrash_pairs = 0
        for i in range(len(hpa_events) - 1):
            a = hpa_events[i]
            b = hpa_events[i + 1]
            if a.get("type") != b.get("type"):
                thrash_pairs += 1

        thrash_rate = thrash_pairs / max(1, len(hpa_events))
        recommendations = []
        if thrash_rate > 0.3:
            recommendations.append(
                "HPA is thrashing (scale up/down alternating rapidly). "
                "Increase stabilizationWindowSeconds in HPA spec."
            )
        if len(scale_ups) > len(scale_downs) * 2:
            recommendations.append(
                "Frequent scale-up events -- consider increasing baseline replicas "
                "or reducing targetCPUUtilizationPercentage."
            )

        return {
            "total_events": len(hpa_events),
            "scale_ups": len(scale_ups),
            "scale_downs": len(scale_downs),
            "thrash_rate": round(thrash_rate, 3),
            "recommendations": recommendations,
        }

    def right_size_resources(
        self, metrics_history: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """
        Recommend optimal CPU/memory requests and limits from observed usage.
        """
        if not metrics_history:
            return {}

        cpu_vals = [m.get("cpu_millicores", 0) for m in metrics_history]
        mem_vals = [m.get("memory_mb", 0) for m in metrics_history]

        p50_cpu = _percentile(cpu_vals, 50)
        p95_cpu = _percentile(cpu_vals, 95)
        p99_cpu = _percentile(cpu_vals, 99)
        p50_mem = _percentile(mem_vals, 50)
        p95_mem = _percentile(mem_vals, 95)

        return {
            "cpu": {
                "request_millicores": round(p50_cpu * 1.1),
                "limit_millicores": round(p99_cpu * 1.3),
                "p50": round(p50_cpu),
                "p95": round(p95_cpu),
                "p99": round(p99_cpu),
            },
            "memory": {
                "request_mb": round(p50_mem * 1.1),
                "limit_mb": round(p95_mem * 1.5),
                "p50": round(p50_mem),
                "p95": round(p95_mem),
            },
            "sample_count": len(metrics_history),
            "rationale": (
                "CPU request = p50 * 1.1; limit = p99 * 1.3. "
                "Memory request = p50 * 1.1; limit = p95 * 1.5."
            ),
        }


def _percentile(values: list[float], pct: int) -> float:
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    idx = (pct / 100) * (len(sorted_vals) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = idx - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac
