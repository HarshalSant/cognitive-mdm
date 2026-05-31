"""
Event Bus -- normalises webhook payloads from GitHub, GitLab, and Jenkins
into a unified PipelineEvent that all downstream stages consume.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class EventType(str, Enum):
    PUSH = "push"
    PULL_REQUEST = "pull_request"
    BUILD_COMPLETE = "build_complete"
    BUILD_FAILED = "build_failed"
    DEPLOY_REQUEST = "deploy_request"
    DEPLOY_COMPLETE = "deploy_complete"
    DEPLOY_FAILED = "deploy_failed"
    SCHEDULED = "scheduled"
    MANUAL = "manual"


class EventSource(str, Enum):
    GITHUB = "github"
    GITLAB = "gitlab"
    JENKINS = "jenkins"
    INTERNAL = "internal"


@dataclass
class PipelineEvent:
    event_id: str
    event_type: EventType
    source: EventSource
    timestamp: datetime
    repository: str
    branch: str
    commit_sha: str
    author: str = "unknown"
    payload: dict[str, Any] = field(default_factory=dict)
    files_changed: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "source": self.source.value,
            "timestamp": self.timestamp.isoformat(),
            "repository": self.repository,
            "branch": self.branch,
            "commit_sha": self.commit_sha,
            "author": self.author,
            "files_changed": self.files_changed,
            "metadata": self.metadata,
        }

    @property
    def is_production_branch(self) -> bool:
        return self.branch in ("main", "master", "production", "release")

    @property
    def has_infra_changes(self) -> bool:
        infra_exts = {".yaml", ".yml", ".tf", ".json", ".dockerfile", "Dockerfile"}
        return any(
            any(f.endswith(ext) or ext in f for ext in infra_exts)
            for f in self.files_changed
        )

    @property
    def has_dependency_changes(self) -> bool:
        dep_files = {
            "requirements.txt", "package.json", "package-lock.json",
            "Pipfile", "pyproject.toml", "go.mod", "pom.xml", "build.gradle",
        }
        return any(
            any(dep in f for dep in dep_files)
            for f in self.files_changed
        )


class EventBus:
    """
    Normalises raw webhook payloads into PipelineEvents.
    Maintains an in-memory event log (production: persist to Postgres/Kafka).
    """

    def __init__(self) -> None:
        self._events: list[PipelineEvent] = []
        self._handlers: dict[EventType, list] = {}

    def register_handler(self, event_type: EventType, handler) -> None:
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)

    async def emit(self, event: PipelineEvent) -> None:
        self._events.append(event)
        for handler in self._handlers.get(event.event_type, []):
            await handler(event)

    def from_github_push(self, payload: dict[str, Any]) -> PipelineEvent:
        import uuid
        commits = payload.get("commits", [])
        files: list[str] = []
        for c in commits:
            files.extend(c.get("added", []))
            files.extend(c.get("modified", []))
            files.extend(c.get("removed", []))
        return PipelineEvent(
            event_id=str(uuid.uuid4()),
            event_type=EventType.PUSH,
            source=EventSource.GITHUB,
            timestamp=datetime.now(timezone.utc),
            repository=payload.get("repository", {}).get("full_name", "unknown"),
            branch=payload.get("ref", "refs/heads/main").replace("refs/heads/", ""),
            commit_sha=payload.get("after", "")[:8],
            author=payload.get("pusher", {}).get("name", "unknown"),
            payload=payload,
            files_changed=list(set(files)),
        )

    def from_github_pr(self, payload: dict[str, Any]) -> PipelineEvent:
        import uuid
        pr = payload.get("pull_request", {})
        return PipelineEvent(
            event_id=str(uuid.uuid4()),
            event_type=EventType.PULL_REQUEST,
            source=EventSource.GITHUB,
            timestamp=datetime.now(timezone.utc),
            repository=payload.get("repository", {}).get("full_name", "unknown"),
            branch=pr.get("head", {}).get("ref", "unknown"),
            commit_sha=pr.get("head", {}).get("sha", "")[:8],
            author=pr.get("user", {}).get("login", "unknown"),
            payload=payload,
            metadata={
                "pr_number": pr.get("number"),
                "pr_title": pr.get("title"),
                "base_branch": pr.get("base", {}).get("ref", "main"),
                "action": payload.get("action"),
            },
        )

    def from_gitlab_push(self, payload: dict[str, Any]) -> PipelineEvent:
        import uuid
        commits = payload.get("commits", [])
        files: list[str] = []
        for c in commits:
            files.extend(c.get("added", []))
            files.extend(c.get("modified", []))
            files.extend(c.get("removed", []))
        return PipelineEvent(
            event_id=str(uuid.uuid4()),
            event_type=EventType.PUSH,
            source=EventSource.GITLAB,
            timestamp=datetime.now(timezone.utc),
            repository=payload.get("project", {}).get("path_with_namespace", "unknown"),
            branch=payload.get("ref", "refs/heads/main").replace("refs/heads/", ""),
            commit_sha=payload.get("after", "")[:8],
            author=payload.get("user_name", "unknown"),
            payload=payload,
            files_changed=list(set(files)),
        )

    def from_manual(self, repository: str, branch: str, triggered_by: str = "user") -> PipelineEvent:
        import uuid
        return PipelineEvent(
            event_id=str(uuid.uuid4()),
            event_type=EventType.MANUAL,
            source=EventSource.INTERNAL,
            timestamp=datetime.now(timezone.utc),
            repository=repository,
            branch=branch,
            commit_sha="manual",
            author=triggered_by,
        )

    def get_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        return [e.to_dict() for e in self._events[-limit:]]

    def get_stats(self) -> dict[str, Any]:
        by_type: dict[str, int] = {}
        by_source: dict[str, int] = {}
        for e in self._events:
            by_type[e.event_type.value] = by_type.get(e.event_type.value, 0) + 1
            by_source[e.source.value] = by_source.get(e.source.value, 0) + 1
        return {
            "total_events": len(self._events),
            "by_type": by_type,
            "by_source": by_source,
        }
