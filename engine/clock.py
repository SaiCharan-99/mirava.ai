"""World clock (W-05): 1 tick = 1 sim minute; real seconds per tick from the day length and speed."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Clock:
    """Pace of sim time; pause/resume/speed take effect on the next tick."""

    seconds_per_sim_day: float = 3600.0
    speed: float = 1.0
    paused: bool = False
    slowed: bool = False
    budget_factor: float = 1.0      # governor slow-down (1, 1.5, 2, 3)

    @property
    def real_s_per_tick(self) -> float:
        """Wall seconds between ticks."""
        return self.seconds_per_sim_day * self.budget_factor / 1440.0 / max(self.speed, 1e-6)

    @property
    def sim_min_per_real_s(self) -> float:
        """Sim minutes advanced per real second (sent to viewers)."""
        return 0.0 if self.paused else round(1440.0 / (self.seconds_per_sim_day * self.budget_factor) * self.speed, 4)

    def set_speed(self, speed: float) -> None:
        """Change speed (0.05–50)."""
        self.speed = min(50.0, max(0.05, float(speed)))
