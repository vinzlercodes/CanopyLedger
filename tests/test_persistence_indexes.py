"""Query-backed index declarations for governed immutable resources."""

from canopyledger.persistence.schema import metadata


def test_metadata_declares_only_the_audited_query_indexes() -> None:
    expected = {
        "pipeline_stage_output": {"ix_pipeline_stage_output_snapshot"},
        "candidate_fact": {"ix_candidate_fact_review_order"},
        "candidate_fact_extraction": {"ix_candidate_fact_extraction_extraction_candidate"},
        "report_model": {"ix_report_model_decision_created"},
    }

    for table_name, index_names in expected.items():
        table = metadata.tables[f"canopyledger.{table_name}"]
        assert index_names.issubset({index.name for index in table.indexes})
