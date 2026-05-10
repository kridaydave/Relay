"""Budget enforcement module for token cap validation.

Provides hard token cap enforcement before every agent call.

Exports:
    TokenCounter: Protocol for token counting implementations.
    HardCapEnforcer: Enforces hard token budget cap.

Note:
    TiktokenCounter is not exported here because it requires the tiktoken
    library at runtime. Import it directly from relay.budget.token_counter
    when needed, or install relay[tiktoken].
"""

from relay.budget.enforcer import HardCapEnforcer
from relay.budget.token_counter import TokenCounter

__all__ = ["HardCapEnforcer", "TokenCounter"]