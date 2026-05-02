"""Feature flags — OpenFeature SDK with local YAML provider.

Phase 3C (Task 3.16): replaces env-var boolean checks with OpenFeature calls.
Phase 4 (Task 4.12): provider swaps to Flipt — call sites unchanged.

Usage:
    from analyzer.flags import get_flag, get_string_flag
    if get_flag("enable_reflection"):
        ...
    channels = get_string_flag("notify_channels", default="telegram,email")
"""

from analyzer.flags.provider import get_flag, get_string_flag

__all__ = ["get_flag", "get_string_flag"]
