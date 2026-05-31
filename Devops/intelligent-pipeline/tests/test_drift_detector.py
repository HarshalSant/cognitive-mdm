"""Tests for GitOps drift detector."""

import pytest
from gitops.drift_detector import DriftDetector, DriftType


class TestDriftDetector:
    def test_detects_argocd_out_of_sync(self, drift_detector):
        apps = [{
            "metadata": {"name": "my-app", "namespace": "argocd"},
            "status": {
                "sync": {"status": "OutOfSync"},
                "health": {"status": "Healthy"},
            },
        }]
        events = drift_detector.analyze_argocd_apps(apps)
        assert len(events) > 0
        assert any(e["drift_type"] == DriftType.OUT_OF_SYNC.value for e in events)

    def test_no_drift_for_synced_healthy_app(self, drift_detector):
        apps = [{
            "metadata": {"name": "my-app", "namespace": "argocd"},
            "status": {
                "sync": {"status": "Synced"},
                "health": {"status": "Healthy"},
            },
        }]
        events = drift_detector.analyze_argocd_apps(apps)
        assert len(events) == 0

    def test_detects_degraded_argocd_app(self, drift_detector):
        apps = [{
            "metadata": {"name": "my-app", "namespace": "argocd"},
            "status": {
                "sync": {"status": "Synced"},
                "health": {"status": "Degraded"},
            },
        }]
        events = drift_detector.analyze_argocd_apps(apps)
        assert any(e["drift_type"] == DriftType.DEGRADED.value for e in events)
        assert any(e["severity"] == "CRITICAL" for e in events)

    def test_detects_flux_not_ready(self, drift_detector):
        ks = [{
            "metadata": {"name": "apps", "namespace": "flux-system"},
            "status": {
                "conditions": [{
                    "type": "Ready",
                    "status": "False",
                    "message": "reconciliation failed",
                }]
            },
        }]
        events = drift_detector.analyze_flux_kustomizations(ks)
        assert len(events) > 0
        assert any(e["drift_type"] == DriftType.OUT_OF_SYNC.value for e in events)

    def test_detects_image_drift_in_yaml(self, drift_detector):
        desired = "image: myapp:v1.2.3"
        actual = "image: myapp:v1.2.0"
        events = drift_detector.analyze_manifest_text(desired, actual)
        assert len(events) > 0
        assert any("drift" in e["description"].lower() for e in events)

    def test_no_drift_identical_yaml(self, drift_detector):
        yaml = "image: myapp:v1.2.3\nreplicas: 3"
        events = drift_detector.analyze_manifest_text(yaml, yaml)
        assert len(events) == 0

    def test_detects_replica_drift(self, drift_detector):
        desired = "replicas: 3"
        actual = "replicas: 1"
        events = drift_detector.analyze_manifest_text(desired, actual)
        assert len(events) > 0

    def test_reconciliation_plan_structure(self, drift_detector):
        events = [
            {"severity": "CRITICAL", "resource": "Deployment/api", "description": "critical issue", "auto_reconcilable": False},
            {"severity": "HIGH", "resource": "Service/api", "description": "high issue", "auto_reconcilable": True},
        ]
        plan = drift_detector.get_reconciliation_plan(events)
        assert "total_drift_events" in plan
        assert "reconciliation_steps" in plan
        assert plan["critical"] == 1
        assert plan["auto_reconcilable"] == 1
        assert plan["manual_required"] == 1

    def test_auto_reconcilable_events_get_kubectl_command(self, drift_detector):
        events = [
            {"severity": "MEDIUM", "resource": "Deployment/web", "description": "out of sync", "auto_reconcilable": True},
        ]
        plan = drift_detector.get_reconciliation_plan(events)
        auto_steps = [s for s in plan["reconciliation_steps"] if s["action"] == "AUTO_RECONCILE"]
        assert len(auto_steps) > 0
        assert "kubectl" in auto_steps[0].get("command", "")
