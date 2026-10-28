from typing import Annotated, Literal
from uuid import UUID
from pydantic import Field, model_validator
from app.schemas import Schema, UTCStamp, ImportBatch

Text = Annotated[str,Field(min_length=1,max_length=12000)]
Evidence = Annotated[list[Text],Field(max_length=100)]


class NextExperiment(Schema):
    keep: Text
    change: Text
    why: Text
    primary_metric: Text
    success_signal: Text
    measurement_plan: Text
    decision_after_test: Text


class AnalysisCreate(Schema):
    agent_run_id: UUID
    analysis_snapshot_at: UTCStamp
    data_cutoff_at: UTCStamp
    agent_version: Annotated[str,Field(min_length=1,max_length=200)]
    performance_verdict: Text
    data_quality: Text
    diagnosis: Text
    hypothesis_status: Literal['SUPPORTED','PARTIALLY_SUPPORTED','NOT_SUPPORTED','INCONCLUSIVE']
    confidence: Literal['LOW','MEDIUM','HIGH']
    supporting_evidence: Evidence
    contrary_evidence: Evidence
    missing_data: Evidence
    competing_explanations: Evidence
    learning: Text
    next_experiment: NextExperiment
    scenarist_learning_brief: Text
    visual_learning_brief: Text
    snapshot_ids: list[UUID] = Field(min_length=1,max_length=1000)
    retention_snapshot_ids: list[UUID] = Field(default_factory=list,max_length=1000)

    @model_validator(mode='after')
    def dates(self):
        if self.data_cutoff_at>self.analysis_snapshot_at:
            raise ValueError('Cutoff must not exceed analysis time')
        if len(set(self.snapshot_ids))!=len(self.snapshot_ids) or len(set(self.retention_snapshot_ids))!=len(self.retention_snapshot_ids):
            raise ValueError('Duplicate evidence references')
        return self


class AgentObservationImport(Schema):
    agent_run_id: UUID
    batch: ImportBatch
