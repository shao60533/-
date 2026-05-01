"""Structured rendering for the AI analysis 8-tab UI.

The :mod:`schemas` module defines the per-tab Pydantic shapes; the
:mod:`extractor` module turns analyzer reports into those shapes via
the active LLM provider's quick-think model.

Per-user advice (personal sizing / personal entry / personal stop /
personal take-profit weights / personalized reasoning) lives in
``user_analysis_advice`` and MUST NOT appear in any rendering schema —
the schemas are shared research, readable by every tenant.
"""
