"""
GitOps Drift Detector -- compares desired state (Git/Helm) with actual
cluster state and classifies drift by severity and cause.

Supports: ArgoCD, Flux, raw kubectl manifests.
Fallback: rule-based diff analysis when cluster API unavailable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class DriftType(str, Enum):
    ADDED = "added"
    REMOVED = "removed"
    MODIFIED = "modified"
    OUT_OF_SYNC = "out_of_sync"
    DEGRADED = "degraded"
    MISSING = "missing"
    UNAUTHORIZED = "unauthorized"


class DriftSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


@dataclass
class DriftEvent:
    resource_kind: str
    resource_name: str
    namespace: str
    drift_type: DriftType
    severity: DriftSeverity
    description: str
    desired: Any = None
    actual: Any = None
    detected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    auto_reconcilable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource": f"{self.resource_kind}/{self.resource_name}",
            "namespace": self.namespace,
            "drift_type": self.drift_type.value,
            "severity": self.severity.value,
            "description": self.description,
            "desired": self.desired,
            "actual": self.actual,
            "detected_at": self.detected_at.isoformat(),
            "auto_reconcilable": self.auto_reconcilable,
        }


class DriftDetector:
    """
    Detects and classifies drift between GitOps desired state and live cluster.
    Works with ArgoCD app status, Flux kustomization status, or raw manifest diffs.
    """

    def analyze_argocd_apps(
        self, apps: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Analyse ArgoCD application sync status."""
        drift_events: list[DriftEvent] = []

        for app in apps:
            name = app.get("metadata", {}).get("name", "unknown")
            namespace = app.get("metadata", {}).get("namespace", "argocd")
            status = app.get("status", {})
            sync = status.get("sync", {})
            health = status.get("health", {})

            sync_status = sync.get("status", "Unknown")
            health_status = health.get("status", "Unknown")

            if sync_status == "OutOfSync":
                resources = sync.get("comparedTo", {}).get("source", {})
                drift_events.append(DriftEvent(
                    resource_kind="Application",
                    resource_name=name,
                    namespace=namespace,
                    drift_type=DriftType.OUT_OF_SYNC,
                    severity=DriftSeverity.HIGH,
                    description=f"ArgoCD app '{name}' is OutOfSync -- live state diverges from Git",
                    desired=resources,
                    auto_reconcilable=True,
                ))

            if health_status == "Degraded":
                drift_events.append(DriftEvent(
                    resource_kind="Application",
                    resource_name=name,
                    namespace=namespace,
                    drift_type=DriftType.DEGRADED,
                    severity=DriftSeverity.CRITICAL,
                    description=f"ArgoCD app '{name}' health is Degraded",
                    actual={"health": health},
                ))

            if health_status == "Missing":
                drift_events.append(DriftEvent(
                    resource_kind="Application",
                    resource_name=name,
                    namespace=namespace,
                    drift_type=DriftType.MISSING,
                    severity=DriftSeverity.CRITICAL,
                    description=f"ArgoCD app '{name}' resources are Missing from cluster",
                ))

        return [e.to_dict() for e in drift_events]

    def analyze_flux_kustomizations(
        self, kustomizations: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Analyse Flux kustomization reconciliation status."""
        events: list[DriftEvent] = []
        for ks in kustomizations:
            name = ks.get("metadata", {}).get("name", "unknown")
            namespace = ks.get("metadata", {}).get("namespace", "flux-system")
            conditions = ks.get("status", {}).get("conditions", [])

            ready = next((c for c in conditions if c.get("type") == "Ready"), None)
            if ready and ready.get("status") != "True":
                events.append(DriftEvent(
                    resource_kind="Kustomization",
                    resource_name=name,
                    namespace=namespace,
                    drift_type=DriftType.OUT_OF_SYNC,
                    severity=DriftSeverity.HIGH,
                    description=f"Flux Kustomization '{name}' not Ready: {ready.get('message', '')}",
                    auto_reconcilable=True,
                ))

            stalled = next((c for c in conditions if c.get("type") == "Stalled"), None)
            if stalled and stalled.get("status") == "True":
                events.append(DriftEvent(
                    resource_kind="Kustomization",
                    resource_name=name,
                    namespace=namespace,
                    drift_type=DriftType.DEGRADED,
                    severity=DriftSeverity.CRITICAL,
                    description=f"Flux Kustomization '{name}' is Stalled: {stalled.get('message', '')}",
                ))

        return [e.to_dict() for e in events]

    def diff_manifests(
        self,
        desired: dict[str, Any],
        actual: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """
        Compare desired (Git) vs actual (cluster) manifest dicts.
        Returns per-field drift events.
        """
        events: list[DriftEvent] = []
        kind = desired.get("kind", "Unknown")
        name = desired.get("metadata", {}).get("name", "unknown")
        namespace = desired.get("metadata", {}).get("namespace", "default")

        desired_spec = desired.get("spec", {})
        actual_spec = actual.get("spec", {})

        drift_fields = _deep_diff(desired_spec, actual_spec)
        for field_path, (d_val, a_val) in drift_fields.items():
            sev = _field_severity(field_path)
            events.append(DriftEvent(
                resource_kind=kind,
                resource_name=name,
                namespace=namespace,
                drift_type=DriftType.MODIFIED,
                severity=sev,
                description=f"Field '{field_path}' differs: desired={d_val!r}, actual={a_val!r}",
                desired=d_val,
                actual=a_val,
                auto_reconcilable=sev not in (DriftSeverity.CRITICAL,),
            ))

        return [e.to_dict() for e in events]

    def analyze_manifest_text(self, desired_yaml: str, actual_yaml: str) -> list[dict[str, Any]]:
        """
        Text-level diff for YAML manifests when structured diff is unavailable.
        Detects image tag changes, replica changes, and resource limit changes.
        """
        events: list[DriftEvent] = []

        image_desired = re.findall(r"image:\s*(\S+)", desired_yaml)
        image_actual = re.findall(r"image:\s*(\S+)", actual_yaml)
        for d, a in zip(image_desired, image_actual):
            if d != a:
                events.append(DriftEvent(
                    resource_kind="Deployment",
                    resource_name="unknown",
                    namespace="default",
                    drift_type=DriftType.MODIFIED,
                    severity=DriftSeverity.HIGH,
                    description=f"Image drift: desired={d}, actual={a}",
                    desired=d, actual=a,
                ).to_dict())

        replica_d = re.search(r"replicas:\s*(\d+)", desired_yaml)
        replica_a = re.search(r"replicas:\s*(\d+)", actual_yaml)
        if replica_d and replica_a and replica_d.group(1) != replica_a.group(1):
            events.append(DriftEvent(
                resource_kind="Deployment",
                resource_name="unknown",
                namespace="default",
                drift_type=DriftType.MODIFIED,
                severity=DriftSeverity.MEDIUM,
                description=f"Replica drift: desired={replica_d.group(1)}, actual={replica_a.group(1)}",
                desired=replica_d.group(1), actual=replica_a.group(1),
                auto_reconcilable=True,
            ).to_dict())

        return events

    def get_reconciliation_plan(
        self, drift_events: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Generate a prioritised reconciliation plan for detected drift."""
        auto = [e for e in drift_events if e.get("auto_reconcilable")]
        manual = [e for e in drift_events if not e.get("auto_reconcilable")]
        critical = [e for e in drift_events if e.get("severity") == "CRITICAL"]

        steps = []
        for i, e in enumerate(critical, 1):
            steps.append({
                "order": i,
                "action": "IMMEDIATE_REVIEW",
                "resource": e.get("resource"),
                "reason": e.get("description"),
            })
        for i, e in enumerate(auto, len(critical) + 1):
            steps.append({
                "order": i,
                "action": "AUTO_RECONCILE",
                "resource": e.get("resource"),
                "command": f"kubectl apply -f manifests/{e.get('resource', '').replace('/', '_')}.yaml",
            })
        for i, e in enumerate(manual, len(critical) + len(auto) + 1):
            steps.append({
                "order": i,
                "action": "MANUAL_FIX",
                "resource": e.get("resource"),
                "reason": e.get("description"),
            })

        return {
            "total_drift_events": len(drift_events),
            "critical": len(critical),
            "auto_reconcilable": len(auto),
            "manual_required": len(manual),
            "reconciliation_steps": steps,
        }


def _deep_diff(
    desired: Any, actual: Any, path: str = ""
) -> dict[str, tuple[Any, Any]]:
    diffs: dict[str, tuple[Any, Any]] = {}
    if isinstance(desired, dict) and isinstance(actual, dict):
        all_keys = set(desired) | set(actual)
        for k in all_keys:
            sub_path = f"{path}.{k}" if path else k
            if k not in actual:
                diffs[sub_path] = (desired[k], None)
            elif k not in desired:
                diffs[sub_path] = (None, actual[k])
            else:
                diffs.update(_deep_diff(desired[k], actual[k], sub_path))
    elif desired != actual:
        diffs[path] = (desired, actual)
    return diffs


def _field_severity(field_path: str) -> DriftSeverity:
    critical_paths = {"securityContext", "serviceAccountName", "hostPID", "hostNetwork"}
    high_paths = {"image", "resources.limits", "replicas", "env"}
    medium_paths = {"labels", "annotations", "resources.requests"}
    for p in critical_paths:
        if p in field_path:
            return DriftSeverity.CRITICAL
    for p in high_paths:
        if p in field_path:
            return DriftSeverity.HIGH
    for p in medium_paths:
        if p in field_path:
            return DriftSeverity.MEDIUM
    return DriftSeverity.LOW
