"""JATAYU Pipeline — pre-LLM intelligence layer.

This package contains the services that run BEFORE the LLM is called,
transforming raw user input into a prepared, bounded, filtered context.

Pipeline order:
    IntentClassifier → TaskExtractor → BrainState → ContextBuilder
    → Planner → IntentRouter → ModelRouter
    → Brain._call_model_raw()
    → ResponseBuilder → EventLog

Every service in this package:
- Reads from BrainState (never from another service)
- Writes only to BrainState or its own owned store
- Never calls the LLM
- Emits events via EventLog

See JATAYU_Brain_Contract_v1.md for the full service contracts.
"""
