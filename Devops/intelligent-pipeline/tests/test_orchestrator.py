"""Tests for pipeline orchestrator."""

import pytest
from core.orchestrator import PipelineOrchestrator, PipelineStage, DeployDecision, _decision_from_score
from core.event_bus import EventBus


class TestPipelineOrchestrator:
    def test_creates_run(self, orchestrator):
        run = orchestrator.create_run("evt-001", "myorg/myrepo", "main", "abc123")
        assert run.run_id is not None
        assert run.current_stage == PipelineStage.PENDING

    @pytest.mark.asyncio
    async def test_executes_full_pipeline(self, orchestrator):
        run = orchestrator.create_run("evt-002", "myorg/myrepo", "feature/test", "def456")
        completed = await orchestrator.execute(run, code_content="x = 1")
        assert completed.current_stage == PipelineStage.COMPLETE
        assert len(completed.stage_results) > 0
        assert completed.deploy_decision is not None

    @pytest.mark.asyncio
    async def test_blocks_on_critical_secret(self, orchestrator):
        run = orchestrator.create_run("evt-003", "myorg/myrepo", "main", "ghi789")
        secret_code = 'GITHUB_TOKEN = "ghp_abc123DEF456ghi789JKL012mno345pqr678"'
        completed = await orchestrator.execute(run, code_content=secret_code)
        assert completed.current_stage == PipelineStage.BLOCKED
        assert completed.deploy_decision == DeployDecision.BLOCK

    @pytest.mark.asyncio
    async def test_clean_code_gets_approved(self, orchestrator):
        run = orchestrator.create_run("evt-004", "myorg/myrepo", "feature/clean", "jkl012")
        completed = await orchestrator.execute(run, code_content="x = 1\ny = 2\nresult = x + y")
        assert completed.deploy_decision in (DeployDecision.APPROVE, DeployDecision.CANARY)

    def test_list_runs_returns_results(self, orchestrator):
        orchestrator.create_run("evt-005", "myorg/myrepo", "main", "mno345")
        runs = orchestrator.list_runs()
        assert len(runs) >= 1

    def test_get_run_by_id(self, orchestrator):
        run = orchestrator.create_run("evt-006", "myorg/myrepo", "main", "pqr678")
        fetched = orchestrator.get_run(run.run_id)
        assert fetched is not None
        assert fetched.run_id == run.run_id

    def test_get_run_nonexistent_returns_none(self, orchestrator):
        assert orchestrator.get_run("nonexistent-id") is None

    def test_run_to_dict_has_required_fields(self, orchestrator):
        run = orchestrator.create_run("evt-007", "myorg/myrepo", "main", "stu901")
        d = run.to_dict()
        assert all(k in d for k in ("run_id", "repository", "branch", "current_stage", "risk_score"))

    def test_stats_after_runs(self, orchestrator):
        orchestrator.create_run("evt-008", "myorg/myrepo", "main", "vwx234")
        stats = orchestrator.get_stats()
        assert stats["total_runs"] >= 1


class TestEventBus:
    def test_from_github_push(self, event_bus):
        payload = {
            "ref": "refs/heads/main",
            "after": "abc123456789",
            "pusher": {"name": "developer"},
            "repository": {"full_name": "myorg/myrepo"},
            "commits": [{"added": ["src/app.py"], "modified": [], "removed": []}],
        }
        event = event_bus.from_github_push(payload)
        assert event.branch == "main"
        assert event.repository == "myorg/myrepo"
        assert "src/app.py" in event.files_changed

    def test_from_github_pr(self, event_bus):
        payload = {
            "action": "opened",
            "repository": {"full_name": "myorg/myrepo"},
            "pull_request": {
                "number": 42,
                "title": "Add feature",
                "head": {"ref": "feature/new", "sha": "def456789"},
                "base": {"ref": "main"},
                "user": {"login": "developer"},
            },
        }
        event = event_bus.from_github_pr(payload)
        assert event.branch == "feature/new"
        assert event.metadata["pr_number"] == 42

    def test_production_branch_detection(self, event_bus):
        payload = {
            "ref": "refs/heads/main",
            "after": "abc123",
            "pusher": {"name": "dev"},
            "repository": {"full_name": "org/repo"},
            "commits": [],
        }
        event = event_bus.from_github_push(payload)
        assert event.is_production_branch is True

    def test_feature_branch_not_production(self, event_bus):
        payload = {
            "ref": "refs/heads/feature/test",
            "after": "abc123",
            "pusher": {"name": "dev"},
            "repository": {"full_name": "org/repo"},
            "commits": [],
        }
        event = event_bus.from_github_push(payload)
        assert event.is_production_branch is False

    @pytest.mark.asyncio
    async def test_emit_event(self, event_bus):
        event = event_bus.from_manual("org/repo", "main")
        await event_bus.emit(event)
        recent = event_bus.get_recent()
        assert len(recent) > 0
        assert recent[-1]["repository"] == "org/repo"

    def test_event_stats(self, event_bus):
        stats = event_bus.get_stats()
        assert "total_events" in stats
        assert "by_type" in stats
