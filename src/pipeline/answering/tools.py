"""LangChain tools that let the answerer agent *propose* a data change -- see README's "Agent
actions" and src/pipeline/actions.py (which these simply wrap). Bound to the agent only when
`DeepAgentAnswerer` is built with `enable_actions=True` (src/pipeline/answering/agent.py); off
by default, so the plain Q&A path can't reach these tools at all.

`_current_session_id` is a contextvar, not a tool argument: the chat session id is already known
to the caller (src/pipeline/orchestrator.py), and making the model supply it as a tool argument
would mean trusting an LLM-generated value for something used in the audit trail. The orchestrator
sets it for the duration of one `.ainvoke()` call; any tool invoked during that call reads it
without the model ever seeing or choosing it.
"""

import contextvars

from langchain_core.tools import tool

from src.pipeline import actions

current_session_id: contextvars.ContextVar[str] = contextvars.ContextVar("current_session_id", default="unknown")
proposed_ids: contextvars.ContextVar[list[int]] = contextvars.ContextVar("proposed_ids")


def _record(proposal_id: int) -> None:
    try:
        proposed_ids.get().append(proposal_id)
    except LookupError:
        pass  # no collector set (e.g. a direct unit-test call to the tool) -- fine, just don't track it


@tool
async def propose_vector_chunk_update(chunk_id: str, new_text: str, reason: str) -> str:
    """Propose replacing a vector document chunk's text. This does NOT change anything yet --
    it records a pending proposal that a human must review and approve via the Data Management
    UI (or POST /api/actions/{id}/apply) before the chunk actually changes. Use the chunk id
    shown in a citation (e.g. "expense_policy.md::2"). Always explain the reason clearly, since
    it's shown to the human reviewer verbatim."""
    try:
        proposal = await actions.propose_vector_chunk_update(current_session_id.get(), chunk_id, new_text, reason)
    except actions.ProposalError as e:
        return f"Could not propose this change: {e}"
    _record(proposal.id)
    return (
        f"Proposed change #{proposal.id} recorded for human review; the chunk has NOT been "
        f"changed yet. A human needs to approve it before it takes effect."
    )


@tool
async def propose_graph_property_update(label: str, name: str, property: str, new_value: str, reason: str) -> str:
    """Propose updating one property of a graph node (e.g. a Team's `focus`, a Project's
    `status`). This does NOT change anything yet -- it records a pending proposal that a human
    must review and approve before the node actually changes. `label` must be one of Employee,
    Team, Project, Tool, Document; `name` is the node's name as shown in a citation. Always
    explain the reason clearly, since it's shown to the human reviewer verbatim."""
    try:
        proposal = await actions.propose_graph_property_update(
            current_session_id.get(), label, name, property, new_value, reason
        )
    except actions.ProposalError as e:
        return f"Could not propose this change: {e}"
    _record(proposal.id)
    return (
        f"Proposed change #{proposal.id} recorded for human review; the node has NOT been "
        f"changed yet. A human needs to approve it before it takes effect."
    )


ACTION_TOOLS = [propose_vector_chunk_update, propose_graph_property_update]
