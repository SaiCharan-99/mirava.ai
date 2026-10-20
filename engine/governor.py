"""Budget governor (E-05): priority classes P0–P5, per-class caps, actual spend, stepwise slow-down."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from population.config import load

CLASSES = ("P0", "P1", "P2", "P3", "P4", "P5")
HIGH = ("P0", "P1", "P2")
SIM_HOURS_PER_DAY = 24


@dataclass
class GovernorState:
    """INTERFACES §3."""

    spent_today_usd: float
    cap_usd: float
    caps: dict[str, int]
    used: dict[str, int]
    speed_factor: float
    sim_day_budget_usd: float = 0.0
    spent_sim_day_usd: float = 0.0
    rendered: int = 0
    unrendered: int = 0


@dataclass
class BudgetGovernor:
    """Decides which background model work is rendered; never stops the world, only slows or simplifies it."""

    cfg: dict[str, Any] = field(default_factory=lambda: load("budget"))
    now: Callable[[], float] = time.time
    sim_days_per_real_hour: float = 1.0      # base pace (1 sim day = 1 real hour)
    step: int = 0
    spent_today: float = 0.0
    real_day: int = -1
    interactive_today: float = 0.0
    sim_day: int = -1
    spent_sim_day: float = 0.0
    high_sim_day: float = 0.0
    used: dict[str, int] = field(default_factory=lambda: dict.fromkeys(CLASSES, 0))
    used_hour: dict[str, int] = field(default_factory=lambda: dict.fromkeys(CLASSES, 0))
    spent_class: dict[str, float] = field(default_factory=lambda: dict.fromkeys(CLASSES, 0.0))
    hour_frac: float = 0.0
    rendered: int = 0
    unrendered: int = 0

    # ------------------------------------------------------------------ pacing
    @property
    def speed_factor(self) -> float:
        """Real-time multiplier per sim day (1, 1.5, 2, 3)."""
        return float(self.cfg["slow_steps"][self.step])

    @property
    def slowed(self) -> bool:
        """True when time runs slower to save budget."""
        return self.step > 0

    def sim_day_budget(self, step: int | None = None) -> float:
        """Money one sim day may use: daily cap ÷ sim days per real day at this speed."""
        f = float(self.cfg["slow_steps"][self.step if step is None else step])
        return float(self.cfg["daily_cap_usd"]) * f / (24 * self.sim_days_per_real_hour)

    def _roll_real_day(self) -> None:
        d = int(self.now() // 86400)
        if d != self.real_day:
            self.real_day, self.spent_today, self.interactive_today = d, 0.0, 0.0

    # ------------------------------------------------------------------ decisions
    def allow(self, priority_class: str, est_cost_usd: float) -> bool:
        """May this background call run rendered now?"""
        self._roll_real_day()
        pc = priority_class if priority_class in CLASSES else "P5"
        budget = self.sim_day_budget()
        cap = int(self.cfg["class_caps"][pc])
        if pc not in HIGH:                         # spread lower classes through the sim day
            cap = min(cap, max(1, int(cap * (self.hour_frac + float(self.cfg["pace_slack"])))))
        hour_cap = self.cfg.get("hourly_caps", {}).get(pc)
        share = budget * float(self.cfg.get("class_money_share", {}).get(pc, 1.0))
        ok = (self.used[pc] < cap and (hour_cap is None or self.used_hour[pc] < int(hour_cap))
              and (pc == "P0" or self.spent_sim_day + est_cost_usd <= budget * float(self.cfg["reserve"][pc]))
              and self.spent_class[pc] + est_cost_usd <= share
              and self.spent_today + est_cost_usd <= float(self.cfg["daily_cap_usd"]) * (1.1 if pc == "P0" else 1.0))
        if ok and pc not in HIGH:                  # spread a lower class through the day against its own spend
            ok = self.spent_class[pc] + est_cost_usd <= share * (self.hour_frac + float(self.cfg["pace_slack"]))
        if ok:
            self.used[pc] += 1
            self.used_hour[pc] += 1
            self.rendered += 1
        else:
            self.unrendered += 1
        return ok

    def allow_interactive(self, est_cost_usd: float) -> bool:
        """Separate cap for user-driven work (Insights, Studio)."""
        self._roll_real_day()
        return self.interactive_today + est_cost_usd <= float(self.cfg["interactive_cap_usd"])

    def record(self, cost_usd: float, priority_class: str) -> None:
        """Book actual spend from usage accounting."""
        self._roll_real_day()
        if priority_class == "interactive":
            self.interactive_today += cost_usd
            return
        self.spent_today += cost_usd
        self.spent_sim_day += cost_usd
        if priority_class in self.spent_class:
            self.spent_class[priority_class] += cost_usd
        if priority_class in HIGH:
            self.high_sim_day += cost_usd

    def on_sim_hour(self, t: int) -> GovernorState:
        """Hourly: resets per-hour counts, a new sim day resets class counts; slows or speeds time from projected P0–P2 spend."""
        day, hour = t // 1440, (t % 1440) // 60
        if day != self.sim_day:
            if self.sim_day >= 0:
                self._adjust_speed(self.high_sim_day)
            self.sim_day, self.spent_sim_day, self.high_sim_day = day, 0.0, 0.0
            self.used = dict.fromkeys(CLASSES, 0)
            self.spent_class = dict.fromkeys(CLASSES, 0.0)
        self.hour_frac = (hour + 1) / SIM_HOURS_PER_DAY
        self.used_hour = dict.fromkeys(CLASSES, 0)
        if hour >= 6:
            projected = self.high_sim_day / self.hour_frac
            if projected > self.sim_day_budget() * float(self.cfg["slow_down_ratio"]):
                self._adjust_speed(projected)
        return self.state()

    def _adjust_speed(self, high_spend: float) -> None:
        steps = len(self.cfg["slow_steps"])
        if high_spend > self.sim_day_budget() * float(self.cfg["slow_down_ratio"]) and self.step < steps - 1:
            self.step += 1
        elif self.step > 0 and high_spend < self.sim_day_budget(self.step - 1) * float(self.cfg["speed_up_ratio"]):
            self.step -= 1

    # ------------------------------------------------------------------ views
    def state(self) -> GovernorState:
        """Snapshot for `budget` events, /live and checkpoints."""
        return GovernorState(spent_today_usd=round(self.spent_today, 4), cap_usd=float(self.cfg["daily_cap_usd"]),
                             caps={k: int(v) for k, v in self.cfg["class_caps"].items()}, used=dict(self.used),
                             speed_factor=self.speed_factor, sim_day_budget_usd=round(self.sim_day_budget(), 4),
                             spent_sim_day_usd=round(self.spent_sim_day, 4), rendered=self.rendered,
                             unrendered=self.unrendered)

    def to_dict(self) -> dict[str, Any]:
        """Checkpoint form."""
        keys = ("step", "spent_today", "real_day", "interactive_today", "sim_day", "spent_sim_day", "high_sim_day",
                "used", "spent_class", "hour_frac", "rendered", "unrendered")
        return {k: getattr(self, k) for k in keys}

    def load(self, d: dict[str, Any]) -> None:
        """Restore from to_dict."""
        for k, v in d.items():
            if hasattr(self, k):
                setattr(self, k, dict(v) if isinstance(v, dict) else v)
