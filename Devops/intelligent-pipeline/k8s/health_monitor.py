"""
Kubernetes Health Monitor -- analyses cluster workload health and
produces actionable insights without requiring direct cluster access.

Works in two modes:
  1. Live mode   -- queries Kubernetes API (requires KUBECONFIG)
  2. Offline mode -- analyses raw pod/event JSON passed as input
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class IssueType(str, Enum):
    CRASHLOOP = "CrashLoopBackOff"
    OOMKILL = "OOMKilled"
    PENDING = "Pending"
    EVICTED = "Evicted"
    IMAGE_PULL = "ImagePullBackOff"
    THROTTLED = "Throttled"
    HIGH_RESTART = "HighRestartCount"
    NOT_READY = "NotReady"
    NODE_PRESSURE = "NodePressure"
    PVC_UNBOUND = "PVCUnbound"


@dataclass
class WorkloadIssue:
    issue_type: IssueType
    severity: str
    namespace: str
    workload: str
    pod: str
    container: str = ""
    message: str = ""
    restart_count: int = 0
    detected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    remediation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "issue_type": self.issue_type.value,
            "severity": self.severity,
            "namespace": self.namespace,
            "workload": self.workload,
            "pod": self.pod,
            "container": self.container,
            "message": self.message,
            "restart_count": self.restart_count,
            "detected_at": self.detected_at.isoformat(),
            "remediation": self.remediation,
        }


REMEDIATION_MAP: dict[IssueType, str] = {
    IssueType.CRASHLOOP: (
        "Check container logs: kubectl logs <pod> --previous. "
        "Verify liveness probe config and startup time. "
        "Check for missing environment variables or config maps."
    ),
    IssueType.OOMKILL: (
        "Increase memory limits in resources.limits.memory. "
        "Profile memory usage and optimise application. "
        "Consider adding memory-based HPA trigger."
    ),
    IssueType.PENDING: (
        "Check node capacity: kubectl describe nodes. "
        "Verify PVC is bound: kubectl get pvc. "
        "Check for node selectors or taints blocking scheduling."
    ),
    IssueType.IMAGE_PULL: (
        "Verify image exists and tag is correct. "
        "Check imagePullSecret is configured. "
        "Confirm registry credentials are valid."
    ),
    IssueType.THROTTLED: (
        "Increase CPU limits or requests in resource spec. "
        "Profile CPU usage patterns and optimise hot paths."
    ),
    IssueType.HIGH_RESTART: (
        "Investigate crash cause: kubectl logs <pod> --previous. "
        "Check readiness probe to avoid premature traffic routing."
    ),
    IssueType.NOT_READY: (
        "Check readiness probe configuration and endpoint. "
        "Verify service dependencies are available."
    ),
    IssueType.NODE_PRESSURE: (
        "Check node disk/memory: kubectl describe node <node>. "
        "Consider evicting low-priority pods or adding nodes."
    ),
    IssueType.PVC_UNBOUND: (
        "Verify StorageClass exists and has capacity. "
        "Check PV availability: kubectl get pv."
    ),
    IssueType.EVICTED: (
        "Pod evicted due to node pressure. "
        "Set appropriate resource requests to avoid eviction. "
        "Consider PodDisruptionBudget for critical workloads."
    ),
}


class KubernetesHealthMonitor:
    """
    Analyses raw Kubernetes pod/event data to surface health issues.
    No direct cluster access required -- pass raw kubectl output as JSON.
    """

    def analyze_pods(self, pods: list[dict[str, Any]]) -> list[dict[str, Any]]:
        issues: list[WorkloadIssue] = []
        for pod in pods:
            metadata = pod.get("metadata", {})
            status = pod.get("status", {})
            name = metadata.get("name", "unknown")
            namespace = metadata.get("namespace", "default")
            labels = metadata.get("labels", {})
            workload = labels.get("app") or labels.get("app.kubernetes.io/name", name)

            phase = status.get("phase", "Unknown")

            if phase == "Pending":
                issues.append(WorkloadIssue(
                    issue_type=IssueType.PENDING,
                    severity="HIGH",
                    namespace=namespace, workload=workload, pod=name,
                    message="Pod stuck in Pending state",
                    remediation=REMEDIATION_MAP[IssueType.PENDING],
                ))
                continue

            if status.get("reason") == "Evicted":
                issues.append(WorkloadIssue(
                    issue_type=IssueType.EVICTED,
                    severity="MEDIUM",
                    namespace=namespace, workload=workload, pod=name,
                    message=status.get("message", "Pod was evicted"),
                    remediation=REMEDIATION_MAP[IssueType.EVICTED],
                ))
                continue

            for cs in status.get("containerStatuses", []):
                container = cs.get("name", "")
                restart_count = cs.get("restartCount", 0)
                waiting = cs.get("state", {}).get("waiting", {})
                reason = waiting.get("reason", "")

                if reason == "CrashLoopBackOff":
                    issues.append(WorkloadIssue(
                        issue_type=IssueType.CRASHLOOP,
                        severity="CRITICAL",
                        namespace=namespace, workload=workload,
                        pod=name, container=container,
                        message=waiting.get("message", "Container in CrashLoopBackOff"),
                        restart_count=restart_count,
                        remediation=REMEDIATION_MAP[IssueType.CRASHLOOP],
                    ))

                elif reason in ("ImagePullBackOff", "ErrImagePull"):
                    issues.append(WorkloadIssue(
                        issue_type=IssueType.IMAGE_PULL,
                        severity="HIGH",
                        namespace=namespace, workload=workload,
                        pod=name, container=container,
                        message=waiting.get("message", "Cannot pull image"),
                        remediation=REMEDIATION_MAP[IssueType.IMAGE_PULL],
                    ))

                elif restart_count > 5:
                    issues.append(WorkloadIssue(
                        issue_type=IssueType.HIGH_RESTART,
                        severity="HIGH",
                        namespace=namespace, workload=workload,
                        pod=name, container=container,
                        restart_count=restart_count,
                        message=f"Container restarted {restart_count} times",
                        remediation=REMEDIATION_MAP[IssueType.HIGH_RESTART],
                    ))

                terminated = cs.get("state", {}).get("terminated", {})
                if terminated.get("reason") == "OOMKilled":
                    issues.append(WorkloadIssue(
                        issue_type=IssueType.OOMKILL,
                        severity="CRITICAL",
                        namespace=namespace, workload=workload,
                        pod=name, container=container,
                        message="Container was OOMKilled -- out of memory",
                        remediation=REMEDIATION_MAP[IssueType.OOMKILL],
                    ))

                if not cs.get("ready", True) and phase == "Running":
                    issues.append(WorkloadIssue(
                        issue_type=IssueType.NOT_READY,
                        severity="MEDIUM",
                        namespace=namespace, workload=workload,
                        pod=name, container=container,
                        message="Container is Running but not Ready",
                        remediation=REMEDIATION_MAP[IssueType.NOT_READY],
                    ))

        return [i.to_dict() for i in issues]

    def analyze_resource_utilization(
        self, metrics: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """
        Analyse pod resource metrics (from metrics-server or Prometheus).
        metrics: [{"pod": "...", "cpu_usage_millicores": 800, "cpu_limit_millicores": 1000,
                   "memory_usage_mb": 450, "memory_limit_mb": 512}]
        """
        issues = []
        for m in metrics:
            pod = m.get("pod", "unknown")
            ns = m.get("namespace", "default")
            cpu_usage = m.get("cpu_usage_millicores", 0)
            cpu_limit = m.get("cpu_limit_millicores", 0)
            mem_usage = m.get("memory_usage_mb", 0)
            mem_limit = m.get("memory_limit_mb", 0)

            if cpu_limit > 0:
                cpu_pct = (cpu_usage / cpu_limit) * 100
                if cpu_pct > 90:
                    issues.append({
                        "issue_type": IssueType.THROTTLED.value,
                        "severity": "HIGH",
                        "namespace": ns,
                        "pod": pod,
                        "message": f"CPU at {cpu_pct:.0f}% of limit ({cpu_usage}m/{cpu_limit}m)",
                        "remediation": REMEDIATION_MAP[IssueType.THROTTLED],
                    })
                elif cpu_pct > 75:
                    issues.append({
                        "issue_type": "CPUPressure",
                        "severity": "MEDIUM",
                        "namespace": ns,
                        "pod": pod,
                        "message": f"CPU at {cpu_pct:.0f}% of limit",
                        "remediation": "Consider increasing CPU limit or optimising hot paths",
                    })

            if mem_limit > 0:
                mem_pct = (mem_usage / mem_limit) * 100
                if mem_pct > 90:
                    issues.append({
                        "issue_type": "MemoryPressure",
                        "severity": "CRITICAL",
                        "namespace": ns,
                        "pod": pod,
                        "message": f"Memory at {mem_pct:.0f}% of limit -- OOMKill imminent",
                        "remediation": REMEDIATION_MAP[IssueType.OOMKILL],
                    })

        return issues

    def cluster_health_summary(
        self, pod_issues: list[dict], resource_issues: list[dict]
    ) -> dict[str, Any]:
        all_issues = pod_issues + resource_issues
        by_severity: dict[str, int] = {}
        by_type: dict[str, int] = {}
        for issue in all_issues:
            s = issue.get("severity", "UNKNOWN")
            t = issue.get("issue_type", "Unknown")
            by_severity[s] = by_severity.get(s, 0) + 1
            by_type[t] = by_type.get(t, 0) + 1

        critical = by_severity.get("CRITICAL", 0)
        high = by_severity.get("HIGH", 0)
        if critical > 0:
            status = HealthStatus.CRITICAL
        elif high > 0:
            status = HealthStatus.WARNING
        elif all_issues:
            status = HealthStatus.WARNING
        else:
            status = HealthStatus.HEALTHY

        return {
            "overall_status": status.value,
            "total_issues": len(all_issues),
            "by_severity": by_severity,
            "by_type": by_type,
            "requires_immediate_action": critical > 0,
            "issues": all_issues[:20],
        }
