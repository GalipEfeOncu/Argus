from app.workers.context import (
    AgentSnapshot,
    ArtifactReference,
    AssignmentContext,
    AssignmentContextBuilder,
    ContextLimits,
    TimelineContextItem,
)


def test_context_is_ordered_bounded_and_metadata_contains_no_selected_content(caplog) -> None:
    builder = AssignmentContextBuilder(
        ContextLimits(max_recent_events=1, max_unresolved_instructions=1, max_artifacts=1, max_characters=600)
    )
    caplog.set_level("INFO", logger="app.workers.context")
    result = builder.build(
        agent=AgentSnapshot(
            agent_id="builder-1",
            role="builder",
            system_prompt="Make the smallest safe change.",
            enabled_skills=("repo",),
            tool_allowlist=("read_file",),
            model_id="model-1",
        ),
        goal="Fix the failing test.",
        assignment=AssignmentContext(
            assignment_id="assignment-1",
            acceptance_criteria="The focused test passes.",
            parent_message="Investigate the regression.",
        ),
        recent_events=(
            TimelineContextItem("event-1", "human_instruction", "Never delete user data.", unresolved=True),
            TimelineContextItem("event-2", "message", "Earlier result that is now less relevant."),
            TimelineContextItem("event-3", "message", "Latest relevant result with sk-abcdefghijklmno."),
        ),
        summary="The earlier implementation changed the event reducer.",
        artifacts=(
            ArtifactReference("artifact-1", "diff", "abc123", "src/reducer.ts"),
            ArtifactReference("artifact-2", "log", "def456"),
        ),
        project_identity="argus",
        workspace_policy="isolated worktree",
    )

    assert "Goal: Fix the failing test." in result.user_prompt
    assert "Agent snapshot: role builder; enabled skills repo; tool allowlist read_file" in result.user_prompt
    assert "Never delete user data." in result.user_prompt
    assert "[REDACTED]" in result.user_prompt
    assert result.metadata.selected_event_ids == ("event-1", "event-3")
    assert result.metadata.selected_artifact_ids == ("artifact-1",)
    assert "recent_events" in result.metadata.truncated_sections
    assert "artifact_references" in result.metadata.truncated_sections
    assert "sk-" not in repr(result.metadata)
    assert "Never delete" not in repr(result.metadata)
    assert "Never delete" not in caplog.text
    assert "sk-" not in caplog.text
    assert "selectedEventIds" in caplog.text


def test_context_character_ceiling_is_enforced() -> None:
    result = AssignmentContextBuilder(ContextLimits(max_characters=80)).build(
        agent=AgentSnapshot("agent-1", "reviewer", "Review safely."),
        goal="x" * 200,
        assignment=AssignmentContext("assignment-1", "y" * 200),
    )

    assert len(result.system_prompt) + len(result.user_prompt) <= 80
    assert "character_budget" in result.metadata.truncated_sections


def test_system_prompt_is_redacted_and_included_in_the_total_context_ceiling() -> None:
    result = AssignmentContextBuilder(ContextLimits(max_characters=30)).build(
        agent=AgentSnapshot("agent-1", "reviewer", "Secret sk-abcdefghijklmno must not leave the runtime."),
        goal="Review.",
        assignment=AssignmentContext("assignment-1", "Report findings."),
    )

    assert len(result.system_prompt) + len(result.user_prompt) <= 30
    assert "sk-" not in result.system_prompt
    assert "system_prompt" in result.metadata.truncated_sections
