"""Tests for Kubernetes health monitor and predictive scaler."""

import pytest
from k8s.health_monitor import KubernetesHealthMonitor, IssueType, HealthStatus
from k8s.predictor import PredictiveScaler


class TestKubernetesHealthMonitor:
    def test_detects_crashloop(self, health_monitor):
        pods = [{
            "metadata": {"name": "api-pod", "namespace": "default", "labels": {"app": "api"}},
            "status": {
                "phase": "Running",
                "containerStatuses": [{
                    "name": "api",
                    "ready": False,
                    "restartCount": 20,
                    "state": {"waiting": {"reason": "CrashLoopBackOff", "message": "exit 1"}},
                }],
            },
        }]
        issues = health_monitor.analyze_pods(pods)
        assert any(i["issue_type"] == IssueType.CRASHLOOP.value for i in issues)
        assert any(i["severity"] == "CRITICAL" for i in issues)

    def test_detects_oomkill(self, health_monitor):
        pods = [{
            "metadata": {"name": "worker-pod", "namespace": "default", "labels": {"app": "worker"}},
            "status": {
                "phase": "Running",
                "containerStatuses": [{
                    "name": "worker",
                    "ready": True,
                    "restartCount": 3,
                    "state": {"terminated": {"reason": "OOMKilled", "exitCode": 137}},
                }],
            },
        }]
        issues = health_monitor.analyze_pods(pods)
        assert any(i["issue_type"] == IssueType.OOMKILL.value for i in issues)

    def test_detects_pending_pod(self, health_monitor):
        pods = [{
            "metadata": {"name": "pending-pod", "namespace": "default", "labels": {}},
            "status": {"phase": "Pending", "containerStatuses": []},
        }]
        issues = health_monitor.analyze_pods(pods)
        assert any(i["issue_type"] == IssueType.PENDING.value for i in issues)
        assert any(i["severity"] == "HIGH" for i in issues)

    def test_detects_image_pull_backoff(self, health_monitor):
        pods = [{
            "metadata": {"name": "bad-image", "namespace": "default", "labels": {}},
            "status": {
                "phase": "Running",
                "containerStatuses": [{
                    "name": "app",
                    "ready": False,
                    "restartCount": 0,
                    "state": {"waiting": {"reason": "ImagePullBackOff"}},
                }],
            },
        }]
        issues = health_monitor.analyze_pods(pods)
        assert any(i["issue_type"] == IssueType.IMAGE_PULL.value for i in issues)

    def test_detects_high_restart_count(self, health_monitor):
        pods = [{
            "metadata": {"name": "flappy-pod", "namespace": "default", "labels": {}},
            "status": {
                "phase": "Running",
                "containerStatuses": [{
                    "name": "app",
                    "ready": True,
                    "restartCount": 10,
                    "state": {"running": {}},
                }],
            },
        }]
        issues = health_monitor.analyze_pods(pods)
        assert any(i["issue_type"] == IssueType.HIGH_RESTART.value for i in issues)

    def test_healthy_pod_no_issues(self, health_monitor):
        pods = [{
            "metadata": {"name": "healthy-pod", "namespace": "default", "labels": {"app": "web"}},
            "status": {
                "phase": "Running",
                "containerStatuses": [{
                    "name": "web",
                    "ready": True,
                    "restartCount": 0,
                    "state": {"running": {}},
                }],
            },
        }]
        issues = health_monitor.analyze_pods(pods)
        assert len(issues) == 0

    def test_all_issues_have_remediation(self, health_monitor):
        pods = [{
            "metadata": {"name": "bad-pod", "namespace": "default", "labels": {}},
            "status": {
                "phase": "Running",
                "containerStatuses": [{
                    "name": "app",
                    "ready": False,
                    "restartCount": 0,
                    "state": {"waiting": {"reason": "CrashLoopBackOff"}},
                }],
            },
        }]
        issues = health_monitor.analyze_pods(pods)
        assert all(i.get("remediation") for i in issues)

    def test_resource_pressure_cpu(self, health_monitor):
        metrics = [{
            "pod": "hot-pod",
            "namespace": "default",
            "cpu_usage_millicores": 950,
            "cpu_limit_millicores": 1000,
            "memory_usage_mb": 200,
            "memory_limit_mb": 512,
        }]
        issues = health_monitor.analyze_resource_utilization(metrics)
        assert len(issues) > 0

    def test_cluster_summary_critical_status(self, health_monitor):
        pod_issues = [{"severity": "CRITICAL", "issue_type": "CrashLoopBackOff"}]
        summary = health_monitor.cluster_health_summary(pod_issues, [])
        assert summary["overall_status"] == HealthStatus.CRITICAL.value
        assert summary["requires_immediate_action"] is True

    def test_cluster_summary_healthy(self, health_monitor):
        summary = health_monitor.cluster_health_summary([], [])
        assert summary["overall_status"] == HealthStatus.HEALTHY.value


class TestPredictiveScaler:
    def test_recommends_scale_up_on_rising_load(self, predictor, metrics_trending_up):
        rec = predictor.predict_and_recommend(
            "api", "default", 2, metrics_trending_up, lookahead_minutes=30
        )
        assert rec is not None
        assert rec.action == "SCALE_UP"
        assert rec.recommended_replicas > 2

    def test_recommends_scale_down_on_low_load(self, predictor, metrics_stable_low):
        rec = predictor.predict_and_recommend(
            "api", "default", 10, metrics_stable_low, lookahead_minutes=30,
            scale_down_threshold=0.40,
        )
        assert rec is None or rec.action == "SCALE_DOWN"

    def test_no_recommendation_stable_mid_load(self, predictor):
        metrics = [{"cpu_utilization": 0.5, "memory_utilization": 0.5}] * 6
        rec = predictor.predict_and_recommend("api", "default", 3, metrics)
        assert rec is None or rec.recommended_replicas == rec.current_replicas

    def test_insufficient_history_returns_none(self, predictor):
        rec = predictor.predict_and_recommend("api", "default", 2, [{"cpu_utilization": 0.8}])
        assert rec is None

    def test_kubectl_command_in_recommendation(self, predictor, metrics_trending_up):
        rec = predictor.predict_and_recommend("api", "default", 2, metrics_trending_up)
        if rec:
            cmd = rec.to_dict().get("kubectl_command", "")
            assert "kubectl scale" in cmd
            assert "api" in cmd

    def test_right_size_resources(self, predictor):
        metrics = [{"cpu_millicores": m, "memory_mb": m * 2} for m in range(100, 600, 50)]
        result = predictor.right_size_resources(metrics)
        assert "cpu" in result
        assert "memory" in result
        assert result["cpu"]["request_millicores"] > 0
        assert result["memory"]["limit_mb"] >= result["memory"]["request_mb"]

    def test_respects_max_replicas(self, predictor, metrics_trending_up):
        rec = predictor.predict_and_recommend(
            "api", "default", 18, metrics_trending_up,
            max_replicas=20,
        )
        if rec:
            assert rec.recommended_replicas <= 20
