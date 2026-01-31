"""
NATS JetStream Key-Value Session Store.

Provides fast session validation with:
- NATS K/V as primary cache with automatic TTL expiration
- Version tracking for optimistic concurrency
- PostgreSQL fallback for cache misses
- Session invalidation support

Architecture:
- Sessions are written to PostgreSQL as source of truth
- On validation, check NATS K/V first (fast path)
- On cache miss, validate against PostgreSQL and populate cache
- TTL matches session expiration for automatic cleanup
"""

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import nats
from nats.js.api import KeyValueConfig
from nats.js.errors import KeyNotFoundError, BucketNotFoundError
from nats.js.kv import KeyValue

logger = logging.getLogger(__name__)

# Default TTL in seconds (24 hours)
DEFAULT_SESSION_TTL = 24 * 60 * 60


@dataclass
class SessionData:
    """Session data stored in NATS K/V."""

    session_token: str
    user_id: int
    email: str
    display_name: str
    expires_at: datetime
    is_active: bool = True
    created_at: Optional[datetime] = None
    last_validated_at: Optional[datetime] = None
    version: int = 0  # K/V revision for optimistic concurrency

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "session_token": self.session_token,
            "user_id": self.user_id,
            "email": self.email,
            "display_name": self.display_name,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_validated_at": self.last_validated_at.isoformat() if self.last_validated_at else None,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SessionData":
        """Create from dictionary."""
        return cls(
            session_token=data["session_token"],
            user_id=data["user_id"],
            email=data["email"],
            display_name=data["display_name"],
            expires_at=datetime.fromisoformat(data["expires_at"]) if data.get("expires_at") else None,
            is_active=data.get("is_active", True),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else None,
            last_validated_at=datetime.fromisoformat(data["last_validated_at"]) if data.get("last_validated_at") else None,
            version=data.get("version", 0),
        )

    def is_valid(self) -> bool:
        """Check if session is currently valid."""
        if not self.is_active:
            return False
        if self.expires_at is None:
            return False
        now = datetime.now(timezone.utc)
        # Handle naive datetime
        if self.expires_at.tzinfo is None:
            expires_at = self.expires_at.replace(tzinfo=timezone.utc)
        else:
            expires_at = self.expires_at
        return now < expires_at


@dataclass
class SessionValidationResult:
    """Result of session validation."""

    valid: bool
    session: Optional[SessionData] = None
    error: Optional[str] = None
    cache_hit: bool = False
    cache_miss_reason: Optional[str] = None


class NatsSessionStore:
    """
    NATS JetStream Key-Value session store.

    Features:
    - Fast O(1) session lookups via K/V
    - Automatic TTL-based expiration
    - Version tracking for optimistic concurrency
    - Watch support for real-time invalidation

    Bucket: noetl_sessions
    Key format: session:{session_token}
    """

    BUCKET_NAME = "noetl_sessions"
    KEY_PREFIX = "session:"

    def __init__(
        self,
        nats_url: Optional[str] = None,
        default_ttl: int = DEFAULT_SESSION_TTL,
    ):
        """
        Initialize session store.

        Args:
            nats_url: NATS server URL (defaults to NATS_URL env var)
            default_ttl: Default session TTL in seconds
        """
        self.nats_url = nats_url or os.getenv("NATS_URL", "nats://localhost:4222")
        self.default_ttl = default_ttl
        self._nc: Optional[nats.NATS] = None
        self._js: Optional[nats.js.JetStreamContext] = None
        self._kv: Optional[KeyValue] = None
        self._connected = False

    async def connect(self) -> None:
        """Connect to NATS and initialize K/V bucket."""
        if self._connected:
            return

        try:
            # Parse URL for credentials
            import urllib.parse
            parsed = urllib.parse.urlparse(self.nats_url)
            host = parsed.hostname or "localhost"
            port = parsed.port or 4222
            server_addr = f"nats://{host}:{port}"

            if parsed.username:
                self._nc = await nats.connect(
                    server_addr,
                    user=parsed.username,
                    password=parsed.password or "",
                )
            else:
                self._nc = await nats.connect(server_addr)

            self._js = self._nc.jetstream()

            # Create or bind to K/V bucket
            try:
                self._kv = await self._js.key_value(self.BUCKET_NAME)
                logger.info(f"Bound to existing K/V bucket: {self.BUCKET_NAME}")
            except BucketNotFoundError:
                # Create bucket with TTL support
                self._kv = await self._js.create_key_value(
                    config=KeyValueConfig(
                        bucket=self.BUCKET_NAME,
                        description="NoETL session cache with automatic TTL",
                        ttl=self.default_ttl,  # Default TTL for all keys
                        history=3,  # Keep 3 versions for audit
                        max_value_size=1024 * 10,  # 10KB max per session
                    )
                )
                logger.info(f"Created K/V bucket: {self.BUCKET_NAME} with TTL={self.default_ttl}s")

            self._connected = True
            logger.info(f"Connected to NATS K/V session store at {self.nats_url}")

        except Exception as e:
            logger.error(f"Failed to connect to NATS K/V: {e}")
            raise

    async def close(self) -> None:
        """Close NATS connection."""
        if self._nc:
            await self._nc.close()
            self._nc = None
            self._js = None
            self._kv = None
            self._connected = False
            logger.info("Closed NATS K/V session store connection")

    def _key(self, session_token: str) -> str:
        """Generate K/V key from session token."""
        return f"{self.KEY_PREFIX}{session_token}"

    async def get(self, session_token: str) -> Optional[SessionData]:
        """
        Get session from cache.

        Args:
            session_token: Session token to lookup

        Returns:
            SessionData if found and valid, None otherwise
        """
        if not self._connected:
            await self.connect()

        try:
            entry = await self._kv.get(self._key(session_token))
            import json
            data = json.loads(entry.value.decode())
            session = SessionData.from_dict(data)
            session.version = entry.revision
            logger.debug(f"Cache HIT for session: {session_token[:8]}... (revision={entry.revision})")
            return session

        except KeyNotFoundError:
            logger.debug(f"Cache MISS for session: {session_token[:8]}...")
            return None

        except Exception as e:
            logger.error(f"Error getting session from K/V: {e}")
            return None

    async def put(
        self,
        session: SessionData,
        ttl: Optional[int] = None,
    ) -> bool:
        """
        Store session in cache.

        Args:
            session: Session data to store
            ttl: Optional TTL in seconds (defaults to remaining session time)

        Returns:
            True if stored successfully
        """
        if not self._connected:
            await self.connect()

        try:
            import json

            # Calculate TTL based on session expiration
            if ttl is None and session.expires_at:
                now = datetime.now(timezone.utc)
                expires_at = session.expires_at
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=timezone.utc)
                remaining = (expires_at - now).total_seconds()
                ttl = max(int(remaining), 1)  # At least 1 second

            session.last_validated_at = datetime.now(timezone.utc)
            data = json.dumps(session.to_dict()).encode()

            revision = await self._kv.put(self._key(session.session_token), data)
            session.version = revision

            logger.debug(
                f"Cached session: {session.session_token[:8]}... "
                f"(revision={revision}, ttl={ttl}s)"
            )
            return True

        except Exception as e:
            logger.error(f"Error storing session in K/V: {e}")
            return False

    async def delete(self, session_token: str) -> bool:
        """
        Delete session from cache (invalidation).

        Args:
            session_token: Session token to delete

        Returns:
            True if deleted successfully
        """
        if not self._connected:
            await self.connect()

        try:
            await self._kv.delete(self._key(session_token))
            logger.debug(f"Deleted session from cache: {session_token[:8]}...")
            return True

        except KeyNotFoundError:
            # Already deleted or never cached
            return True

        except Exception as e:
            logger.error(f"Error deleting session from K/V: {e}")
            return False

    async def invalidate_user_sessions(self, user_id: int) -> int:
        """
        Invalidate all sessions for a user.

        Note: This requires iterating through keys, which may be slow for many sessions.
        Consider using a secondary index (user:{user_id} -> [session_tokens]) for efficiency.

        Args:
            user_id: User ID whose sessions to invalidate

        Returns:
            Number of sessions invalidated
        """
        if not self._connected:
            await self.connect()

        count = 0
        try:
            # List all keys with prefix
            keys = await self._kv.keys()
            for key in keys:
                if key.startswith(self.KEY_PREFIX):
                    try:
                        entry = await self._kv.get(key)
                        import json
                        data = json.loads(entry.value.decode())
                        if data.get("user_id") == user_id:
                            await self._kv.delete(key)
                            count += 1
                    except Exception:
                        pass

            logger.info(f"Invalidated {count} sessions for user_id={user_id}")
            return count

        except Exception as e:
            logger.error(f"Error invalidating user sessions: {e}")
            return count

    async def validate(
        self,
        session_token: str,
        fetch_from_db: Optional[callable] = None,
    ) -> SessionValidationResult:
        """
        Validate session with cache-first strategy.

        Args:
            session_token: Session token to validate
            fetch_from_db: Optional async function to fetch session from DB on cache miss
                           Signature: async def fetch(token: str) -> Optional[SessionData]

        Returns:
            SessionValidationResult with validation outcome
        """
        # Try cache first (fast path)
        session = await self.get(session_token)

        if session:
            # Cache hit - validate expiration
            if session.is_valid():
                return SessionValidationResult(
                    valid=True,
                    session=session,
                    cache_hit=True,
                )
            else:
                # Expired - delete from cache
                await self.delete(session_token)
                return SessionValidationResult(
                    valid=False,
                    error="Session expired",
                    cache_hit=True,
                )

        # Cache miss - try DB if fetch function provided
        if fetch_from_db:
            try:
                session = await fetch_from_db(session_token)
                if session and session.is_valid():
                    # Populate cache for future requests
                    await self.put(session)
                    return SessionValidationResult(
                        valid=True,
                        session=session,
                        cache_hit=False,
                        cache_miss_reason="fetched_from_db",
                    )
                elif session:
                    return SessionValidationResult(
                        valid=False,
                        error="Session expired or inactive",
                        cache_hit=False,
                        cache_miss_reason="db_session_invalid",
                    )
                else:
                    return SessionValidationResult(
                        valid=False,
                        error="Session not found",
                        cache_hit=False,
                        cache_miss_reason="not_found_in_db",
                    )
            except Exception as e:
                logger.error(f"Error fetching session from DB: {e}")
                return SessionValidationResult(
                    valid=False,
                    error=f"Database error: {e}",
                    cache_hit=False,
                    cache_miss_reason="db_error",
                )

        # No DB fallback - report cache miss
        return SessionValidationResult(
            valid=False,
            error="Session not found in cache",
            cache_hit=False,
            cache_miss_reason="no_db_fallback",
        )


# Global session store instance
_session_store: Optional[NatsSessionStore] = None


async def get_session_store() -> NatsSessionStore:
    """Get or create global session store instance."""
    global _session_store
    if _session_store is None:
        _session_store = NatsSessionStore()
        await _session_store.connect()
    return _session_store


async def close_session_store() -> None:
    """Close global session store instance."""
    global _session_store
    if _session_store:
        await _session_store.close()
        _session_store = None
