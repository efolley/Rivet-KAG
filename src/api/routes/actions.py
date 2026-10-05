"""Human review for agent-proposed data changes -- see README's "Agent actions" and
src/pipeline/actions.py. This router is the ONLY way a proposal actually gets applied to
Milvus/Neo4j; the agent itself can only ever create a pending row (src/pipeline/answering/tools.py).
"""

import logging

from fastapi import APIRouter, HTTPException

from src.db import DataEditProposal
from src.pipeline import actions
from src.schemas import ActionProposal

router = APIRouter(prefix="/actions", tags=["actions"])
log = logging.getLogger(__name__)


@router.get("", response_model=list[ActionProposal])
async def list_actions(status: str | None = None) -> list[DataEditProposal]:
    return await actions.list_proposals(status)


@router.post("/{action_id}/apply", response_model=ActionProposal)
async def apply_action(action_id: int) -> DataEditProposal:
    try:
        return await actions.apply_proposal(action_id)
    except actions.ProposalError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/{action_id}/reject", response_model=ActionProposal)
async def reject_action(action_id: int) -> DataEditProposal:
    try:
        return await actions.reject_proposal(action_id)
    except actions.ProposalError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
