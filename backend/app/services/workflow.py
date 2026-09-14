from sqlalchemy import select

from app.governance_models import WorkflowEvent
from app.repositories import audit


def transition(db, geometry, state, actor, reason, job_id=None, decision_id=None):
    previous = db.scalar(
        select(WorkflowEvent)
        .where(WorkflowEvent.object_id == geometry.object_id)
        .order_by(WorkflowEvent.sequence.desc())
        .limit(1)
    )
    row = WorkflowEvent(
        object_id=geometry.object_id,
        geometry_id=geometry.id,
        before_state=previous.after_state if previous else "UNTRACKED",
        after_state=state,
        reason=reason,
        actor_id=actor,
        validation_job_id=job_id,
        review_decision_id=decision_id,
    )
    db.add(row)
    audit(
        db,
        actor,
        "WORKFLOW_TRANSITION",
        row,
        {
            "object_id": str(geometry.object_id),
            "geometry_id": str(geometry.id),
            "before": row.before_state,
            "after": state,
            "reason": reason,
            "validation_job_id": str(job_id) if job_id else None,
            "decision_id": str(decision_id) if decision_id else None,
            "source_dataset_id": (
                str(geometry.source_dataset_id) if geometry.source_dataset_id else None
            ),
            "legal_effect": "none",
        },
    )
    return row
