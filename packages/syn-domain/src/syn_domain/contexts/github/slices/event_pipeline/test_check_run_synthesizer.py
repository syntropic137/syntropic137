"""Tests for check_run_synthesizer — validates synthesized payloads work with SELF_HEALING_PRESET."""

from __future__ import annotations

from datetime import UTC, datetime

from syn_domain.contexts.github.slices.event_pipeline.check_run_synthesizer import (
    synthesize_check_run_event,
)
from syn_domain.contexts.github.slices.event_pipeline.pending_sha_port import PendingSHA


def _make_pending(
    repository: str = "owner/repo",
    sha: str = "abc123def456",
    pr_number: int = 42,
    branch: str = "feat/my-feature",
    installation_id: str = "inst-1",
) -> PendingSHA:
    return PendingSHA(
        repository=repository,
        sha=sha,
        pr_number=pr_number,
        branch=branch,
        installation_id=installation_id,
        registered_at=datetime.now(UTC),
    )


def _make_raw_check_run(
    check_run_id: int = 789,
    name: str = "lint",
    status: str = "completed",
    conclusion: str = "failure",
    html_url: str = "https://github.com/owner/repo/runs/789",
    output_title: str = "Lint failed",
    output_summary: str = "2 errors found",
) -> dict:
    return {
        "id": check_run_id,
        "name": name,
        "status": status,
        "conclusion": conclusion,
        "html_url": html_url,
        "output": {
            "title": output_title,
            "summary": output_summary,
        },
    }


class TestSynthesizeCheckRunEvent:
    def test_returns_normalized_event_for_failure(self) -> None:
        pending = _make_pending()
        raw = _make_raw_check_run(conclusion="failure")
        event = synthesize_check_run_event(raw, pending)

        assert event is not None
        assert event.event_type == "check_run"
        assert event.action == "completed"
        assert event.repository == "owner/repo"
        assert event.installation_id == "inst-1"
        assert event.source.value == "checks_api"

    def test_returns_normalized_event_for_timed_out(self) -> None:
        raw = _make_raw_check_run(conclusion="timed_out")
        event = synthesize_check_run_event(raw, _make_pending())
        assert event is not None

    def test_returns_none_for_success(self) -> None:
        raw = _make_raw_check_run(conclusion="success")
        assert synthesize_check_run_event(raw, _make_pending()) is None

    def test_returns_none_for_neutral(self) -> None:
        raw = _make_raw_check_run(conclusion="neutral")
        assert synthesize_check_run_event(raw, _make_pending()) is None

    def test_returns_none_for_skipped(self) -> None:
        raw = _make_raw_check_run(conclusion="skipped")
        assert synthesize_check_run_event(raw, _make_pending()) is None

    def test_returns_none_for_incomplete(self) -> None:
        raw = _make_raw_check_run(status="in_progress", conclusion="")
        assert synthesize_check_run_event(raw, _make_pending()) is None

    def test_dedup_key_matches_webhook_format(self) -> None:
        """Dedup key must be identical to what a webhook check_run.completed produces."""
        raw = _make_raw_check_run(check_run_id=789)
        pending = _make_pending(repository="owner/repo")
        event = synthesize_check_run_event(raw, pending)

        assert event is not None
        assert event.dedup_key == "check_run:owner/repo:789:completed"


class TestSelfHealingPresetCompatibility:
    """Verify synthesized payload satisfies SELF_HEALING_PRESET conditions and input mappings."""

    def test_conditions_pass(self) -> None:
        from syn_domain.contexts.github._shared.trigger_presets import SELF_HEALING_PRESET
        from syn_domain.contexts.github.slices.evaluate_webhook.condition_evaluator import (
            evaluate_conditions,
        )

        raw = _make_raw_check_run(conclusion="failure")
        pending = _make_pending(pr_number=42, branch="feat/my-feature")
        event = synthesize_check_run_event(raw, pending)
        assert event is not None

        conditions = SELF_HEALING_PRESET["conditions"]
        assert evaluate_conditions(conditions, event.payload) is True

    def test_input_mappings_extract_correctly(self) -> None:
        from syn_domain.contexts.github._shared.trigger_presets import SELF_HEALING_PRESET
        from syn_domain.contexts.github.slices.evaluate_webhook.condition_evaluator import (
            extract_inputs,
        )

        raw = _make_raw_check_run(
            name="lint",
            html_url="https://github.com/owner/repo/runs/789",
            output_title="Lint failed",
            output_summary="2 errors found",
        )
        pending = _make_pending(
            repository="owner/repo",
            pr_number=42,
            branch="feat/my-feature",
        )
        event = synthesize_check_run_event(raw, pending)
        assert event is not None

        mapping = dict(SELF_HEALING_PRESET["input_mapping"])
        inputs = extract_inputs(event.payload, mapping)

        assert inputs["repository"] == "owner/repo"
        assert inputs["pr_number"] == 42
        assert inputs["branch"] == "feat/my-feature"
        assert inputs["check_name"] == "lint"
        assert inputs["check_output_title"] == "Lint failed"
        assert inputs["check_output_summary"] == "2 errors found"
        assert inputs["check_html_url"] == "https://github.com/owner/repo/runs/789"

    def test_conditions_fail_for_success_conclusion(self) -> None:
        """A successful check run should not produce an event at all."""
        raw = _make_raw_check_run(conclusion="success")
        assert synthesize_check_run_event(raw, _make_pending()) is None
