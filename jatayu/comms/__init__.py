"""Communication Layer — provider-agnostic messaging for JATAYU.

This package provides the abstract interfaces, normalized models, and
routing infrastructure that allow any messaging platform (WhatsApp,
Telegram, Slack, Discord, etc.) to communicate with the Brain through
a single, unified pipeline.

Voice interactions remain INDEPENDENT of this layer and use their own
high-priority execution path.
"""
