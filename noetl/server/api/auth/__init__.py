"""Server-side auth helpers for the noetl FastAPI app.

This package owns the auth enforcement that lives *inside* the noetl
server itself — independent of any optional gateway in front of it. The
gateway, when present, is treated as a perimeter optimisation; the
source of truth for "is this caller allowed to dispatch this playbook?"
is here so deployments without a gateway (local kind, private GKE)
inherit the same authorisation rules.

The check itself runs against the same ``auth.sessions`` and
``auth.playbook_permissions`` tables the existing
``api_integration/auth0/check_playbook_access`` playbook reads, so
permissions granted via the GUI / playbook flow continue to work
without modification.
"""

from .check_access import (
    AccessDecision,
    EnforcementMode,
    AuthEnforcementSettings,
    check_playbook_access,
    load_enforcement_settings,
    extract_session_token,
)

__all__ = [
    "AccessDecision",
    "EnforcementMode",
    "AuthEnforcementSettings",
    "check_playbook_access",
    "load_enforcement_settings",
    "extract_session_token",
]
