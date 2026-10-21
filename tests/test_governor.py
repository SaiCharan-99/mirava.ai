"""Governor cost simulation (E-05): $15/day ±10%, priorities respected, slow-down only when P0–P2 exceed."""

import random

from engine.governor import BudgetGovernor

COST = {"P0": 0.017, "P1": 0.0005, "P2": 0.009, "P3": 0.0011, "P4": 0.006, "P5": 0.0013}


def simulate(daily_demand: dict[str, int], real_days: int = 3, seed: int = 1) -> tuple[BudgetGovernor, list[float],
                                                                                         dict[str, list[int]]]:
    """Run the governor against a synthetic demand; returns (gov, spend per real day, asked/allowed by class)."""
    clock = [0.0]
    g = BudgetGovernor(now=lambda: clock[0])
    rng = random.Random(seed)
    spend: dict[int, float] = {}
    tally = {k: [0, 0] for k in COST}
    t = 0
    while clock[0] < real_days * 86400:
        if t % 60 == 0:
            g.on_sim_hour(t)
        hour = (t % 1440) // 60
        if 7 <= hour < 23:
            for pc, n in daily_demand.items():
                if rng.random() < n / (16 * 60):
                    tally[pc][0] += 1
                    cost = COST[pc] * rng.uniform(0.8, 1.2)
                    if g.allow(pc, COST[pc]):
                        tally[pc][1] += 1
                        g.record(cost, pc)
                        spend[int(clock[0] // 86400)] = spend.get(int(clock[0] // 86400), 0.0) + cost
        t += 1
        clock[0] += 2.5 * g.speed_factor          # 1 sim minute = 2.5 real s at 1 sim day / real hour
    return g, [spend.get(d, 0.0) for d in range(real_days)], {k: v for k, v in tally.items()}


def test_spend_on_target_and_priorities() -> None:
    heavy = {"P0": 10, "P1": 440, "P2": 20, "P3": 300, "P4": 120, "P5": 60}
    g, per_day, tally = simulate(heavy)
    for d in per_day:
        assert 13.5 <= d <= 16.5, per_day
    rate = {k: v[1] / max(1, v[0]) for k, v in tally.items()}
    assert rate["P0"] >= 0.99 and rate["P1"] >= rate["P3"] >= rate["P5"]
    assert rate["P2"] >= rate["P4"]
    assert g.step == 0                     # P0–P2 alone fit: no slow-down


def test_slow_down_only_when_high_priority_exceeds() -> None:
    g, per_day, _ = simulate({"P0": 60, "P1": 440, "P2": 40, "P3": 50})
    assert g.step > 0 and g.slowed
    assert all(d <= 16.5 for d in per_day)


def test_light_demand_stays_fast_and_cheap() -> None:
    g, per_day, tally = simulate({"P1": 50, "P4": 10})
    assert g.step == 0 and all(d < 5 for d in per_day)
    assert all(v[0] == v[1] for v in tally.values())


def test_interactive_cap_separate() -> None:
    g = BudgetGovernor(now=lambda: 0.0)
    g.record(14.9, "P0")
    assert g.allow_interactive(1.0)
    g.record(4.5, "interactive")
    assert g.allow_interactive(1.0)                 # cap is $10 now
    g.record(5.0, "interactive")
    assert not g.allow_interactive(1.0)
    assert g.state().spent_today_usd == 14.9


def test_p1_hourly_cap_spreads_thoughts_through_the_day() -> None:
    """A morning burst of notices cannot use the whole day's P1 cap (cloud Day 16: 147 thoughts in one hour)."""
    g = BudgetGovernor(now=lambda: 0.0)
    g.on_sim_hour(7 * 60)
    morning = sum(g.allow("P1", 0.0005) for _ in range(200))
    g.on_sim_hour(12 * 60)
    noon = sum(g.allow("P1", 0.0005) for _ in range(200))
    assert morning == 28 and noon == 28


def test_early_store_inquiries_do_not_starve_social_chats() -> None:
    """Live Day 44: P0 inquiries spent the pace allowance and P4 chats stayed unrendered all day."""
    g = BudgetGovernor(now=lambda: 0.0)
    g.on_sim_hour(8 * 60)
    n = 0
    while g.allow("P0", 0.012):
        g.record(0.012, "P0")
        n += 1
        assert n < 100
    assert g.spent_class["P0"] <= g.sim_day_budget() * 0.55 + 0.012
    g.on_sim_hour(14 * 60)                         # mid-afternoon: chats still get their own paced share
    chats = 0
    while g.allow("P4", 0.006):
        g.record(0.006, "P4")
        chats += 1
        assert chats < 100
    assert chats >= 5
    assert g.spent_class["P4"] <= g.sim_day_budget() * g.cfg["class_money_share"]["P4"] + 0.006


def test_cheap_chats_render_150_plus_per_sim_day() -> None:
    """Spend far below cap: chats are paced by money, not by a tiny count cap (fix-C finding 5)."""
    demand = {"P1": 200, "P2": 40, "P4": 400}
    COST_SAVE = dict(COST)
    COST.update({"P2": 0.003, "P4": 0.0016})               # measured per-chat cost on Flash-Lite
    try:
        g, per_day, tally = simulate(demand, real_days=1)
    finally:
        COST.clear()
        COST.update(COST_SAVE)
    sim_days = 24 / g.speed_factor
    chats = (tally["P2"][1] + tally["P4"][1]) / sim_days
    assert chats >= 150, chats
    assert per_day[0] <= 15 * 1.1


def test_hour_pacing_is_by_money_when_spend_is_low() -> None:
    g = BudgetGovernor(now=lambda: 0.0)
    g.on_sim_hour(7 * 60)                                     # early morning: count pacing would allow only ~20%
    n = sum(g.allow("P4", 0.0) for _ in range(200))
    assert n == 200                                           # nothing spent yet → only money paces
