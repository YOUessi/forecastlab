"""Quality coverage is a reporting aid, never a provenance or semantic trust gate."""
from app.evidence_quality import build_quality_profile
from app.schemas import (
    Evidence, EvidenceAssessment, EvidenceFinding, FindingCitation, ConflictDetail,
    RejectedFinding, RetrievalLog, RetrievalResult, SourceAlias, utcnow,
)


def make_source(eid, **overrides):
    values = dict(
        id=eid, file_id=eid, title="来源 " + eid,
        retrieved_at=utcnow(), excerpt="直接引文在这里。",
        content_hash="sha-demo", source_type="imported",
        source_group="group-A", content_kind="body",
    )
    values.update(overrides)
    return Evidence(**values)


def test_quality_counts_are_derived_from_sources_logs_and_finding_validation():
    now = utcnow()
    first = make_source(
        "E001", published_at=now, source_kind="primary",
        aliases=[SourceAlias(source_url="https://example.org/origin"),
                 SourceAlias(source_url="https://mirror.example.org/origin")],
        possible_same_source=["E002"],
    )
    second = make_source(
        "E002", source_type="snippet_only", content_kind="snippet",
        content_truncated=True,
    )
    retrieval = RetrievalResult(
        evidence=[first, second], status="partial",
        retrieval_log=[
            RetrievalLog(task_id="R001", query="fact", status="success", result_count=2),
            RetrievalLog(task_id="R002", query="risk", status="failed", error="HTTP 429"),
            RetrievalLog(task_id="R003", query="other", status="empty", result_count=0),
        ],
        exclusions=[{"source": "candidate-3", "reason": "late"}],
    )
    assessment = EvidenceAssessment(
        summary="证据存在限制", findings_validated=True,
        findings=[EvidenceFinding(
            id="F001", claim="直接引文在这里", relation="supports",
            citations=[FindingCitation(
                evidence_id="E001", snapshot_hash="snap", paragraph_id="B000001",
                quote="直接引文在这里", start=0, end=7,
            )],
        )],
        rejected_findings=[RejectedFinding(candidate={}, reason="quote 不存在")],
        conflict_details=[ConflictDetail(
            issue="不同口径", finding_ids=["F001", "F002"], status="unresolved",
        )],
    )
    profile = build_quality_profile(retrieval, assessment)
    assert profile.source_count == 2
    assert profile.source_group_count == 1
    assert profile.body_source_count == 1
    assert profile.snippet_only_count == 1
    assert profile.primary_label_count == 1
    assert profile.unknown_publication_count == 1
    assert profile.truncated_count == 1
    assert profile.suspected_same_source_count == 1
    assert profile.merged_alias_count == 1
    assert (profile.search_success_count, profile.search_empty_count, profile.search_failure_count) == (1, 1, 1)
    assert profile.excluded_count == 1
    assert (profile.validated_finding_count, profile.rejected_finding_count, profile.unresolved_conflict_count) == (1, 1, 1)
    assert any("不是已经核实的独立来源" in warning for warning in profile.warnings)
    assert any("检索任务失败" in warning for warning in profile.warnings)
    assert all("独立来源数量：" not in warning for warning in profile.warnings)


def test_quality_uses_group_ids_not_shared_domain_names():
    a = make_source("E001", source_group="source:A")
    b = make_source("E002", source_group="source:B")
    profile = build_quality_profile(
        RetrievalResult(evidence=[a, b]), EvidenceAssessment(summary="未分析")
    )
    assert profile.source_group_count == 2
    assert profile.validated_finding_count == 0
    assert profile.primary_label_count == 0
    assert all("一个来源组" not in warning for warning in profile.warnings)


def test_empty_and_failed_retrieval_preserves_quality_without_false_claims():
    result = RetrievalResult(
        status="failed",
        retrieval_log=[RetrievalLog(task_id="R001", query="test", status="failed", error="ConnectError")],
    )
    profile = build_quality_profile(result, EvidenceAssessment(summary="取证失败"))
    assert profile.source_count == 0
    assert profile.source_group_count == 0
    assert profile.validated_finding_count == 0
    assert profile.search_failure_count == 1
    assert any("没有可核对的有效来源" in warning for warning in profile.warnings)
    assert any("检索任务失败" in warning for warning in profile.warnings)


def test_historical_exercise_is_not_reported_as_blind_validation():
    evidence = make_source("E001", availability="historical_exercise")
    profile = build_quality_profile(
        RetrievalResult(evidence=[evidence]), EvidenceAssessment(summary="历史资料")
    )
    assert any("严格盲回测" in warning for warning in profile.warnings)
