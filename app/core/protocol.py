"""Versioned client/server protocol constants.

The station API is versioned explicitly. Clients MUST send
``X-Api-Version`` on every request; unknown versions are rejected
with HTTP 400 so that incompatible clients fail loudly instead of
being mis-interpreted by a newer server.
"""

from __future__ import annotations

PROTOCOL_VERSION = 1
SUPPORTED_PROTOCOL_VERSIONS = (1,)

HEADER_API_VERSION = "X-Api-Version"

# A station is considered stale (offline) when its last heartbeat
# is older than this many seconds (default configurable).
DEFAULT_HEARTBEAT_TIMEOUT = 30

# Pending station commands older than this are never delivered.
COMMAND_TTL_SECONDS = 300
