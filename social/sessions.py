"""SessionRegistry (T-06): ids, participant locks, release on end or timeout."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Session:
    """One open session."""

    session_id: str
    participants: list[int]
    kind: str
    t_open: int
    timeout_t: int


@dataclass
class SessionRegistry:
    """No agent is ever in two sessions at once."""

    sessions: dict[str, Session] = field(default_factory=dict)
    _by_agent: dict[int, str] = field(default_factory=dict)
    _seq: int = 0

    def open(self, participants: list[int], kind: str, t: int = 0, timeout: int = 30) -> str | None:
        """Lock all participants and return a session id, or None if anyone is busy."""
        if len(set(participants)) != len(participants) or any(self.busy(p) for p in participants):
            return None
        self._seq += 1
        sid = f"s{t}-{'-'.join(map(str, sorted(participants)))}-{self._seq}"
        self.sessions[sid] = Session(sid, list(participants), kind, t, t + timeout)
        for p in participants:
            self._by_agent[p] = sid
        return sid

    def close(self, session_id: str) -> None:
        """Release the participants (no-op if already closed)."""
        s = self.sessions.pop(session_id, None)
        if s is not None:
            for p in s.participants:
                if self._by_agent.get(p) == session_id:
                    del self._by_agent[p]

    def busy(self, agent_id: int) -> bool:
        """Is this agent in an open session?"""
        return agent_id in self._by_agent

    def expire(self, t: int) -> list[str]:
        """Close sessions past their timeout; returns their ids."""
        old = [sid for sid, s in self.sessions.items() if t >= s.timeout_t]
        for sid in old:
            self.close(sid)
        return old

    def to_dict(self) -> dict:
        """Checkpoint form."""
        return {"seq": self._seq, "sessions": {k: vars(v) for k, v in self.sessions.items()}}

    @classmethod
    def from_dict(cls, d: dict) -> SessionRegistry:
        """Inverse of to_dict."""
        r = cls()
        r._seq = int(d.get("seq", 0))
        for k, v in (d.get("sessions") or {}).items():
            s = Session(**v)
            r.sessions[k] = s
            for p in s.participants:
                r._by_agent[p] = k
        return r
