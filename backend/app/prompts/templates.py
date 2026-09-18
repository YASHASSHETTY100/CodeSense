"""Versioned Jinja2 prompt templates (spec Section 7). v1."""
from jinja2 import Template

VERSION = "v1"

PROJECT_SUMMARY = Template("""You are a functional application analyst. Given structured facts extracted
from a codebase (modules, endpoints, entities, roles, business rules) — not raw code —
write a business-friendly overview for a PM who has never seen this codebase.
Do not invent capabilities not in the facts. Say so explicitly when unknown.
Output sections: Project Purpose, Technology Stack, Major Modules & Features, User Roles,
Key Functional Workflows, Important Business Rules, Major APIs/Services, Data Model Overview,
External Integrations, Inter-Module Dependencies.
Context: {{ structured_facts_json }}""")

FUNCTIONAL_QA = Template("""You are a Functional Application Expert answering a PM's question about
THIS application. Use only the provided evidence. Never answer from general knowledge —
say "the codebase does not show this" instead of guessing.
For every claim reference evidence (file + symbol/line range). Plain business language.
Question: {{ question }}
Evidence: {{ retrieved_evidence_chunks }}
Respond as JSON: {"answer": "...", "evidence": [{"file": "...", "symbol": "...", "lines": "...", "why_relevant": "..."}]}""")

FLOW_TRACE = Template("""Trace the end-to-end implementation flow for the action, using only the evidence,
in execution order (frontend validation -> API call -> backend validation -> DB change ->
downstream effects -> response). Mark unevidenced hops as "not found in analyzed code".
Action: {{ question }}
Evidence: {{ retrieved_evidence_chunks }}
Respond as JSON: {"steps": [{"stage": "...", "description": "...", "evidence": {...}}], "gaps": ["..."]}""")

ENHANCEMENT = Template("""A PM wants to evaluate an enhancement. Using only evidence about CURRENT
implementation produce: 1) Current behavior 2) Modules involved 3) Frontend changes
4) Backend/API changes 5) DB impact 6) Permission implications 7) Notifications/integrations
8) Downstream effects 9) Needs-dev-validation 10) Complexity Low/Med/High + justification.
Be conservative; list unknowns under dev-validation.
Proposed enhancement: {{ enhancement_request }}
Evidence: {{ retrieved_evidence_chunks }}
Respond as structured JSON with the 10 sections, each with evidence.""")

DOC_GUIDE = Template("""Produce a functional help-guide outline for module "{{ module_name }}".
Use only provided facts. Structure: Overview, Who Can Use This (roles), Key Actions & How
They Work, Business Rules & Validations, Related Modules, Common Questions (3-5), Known
Limitations/Edge Cases (only if evidenced).
Context: {{ module_facts_json }}""")
