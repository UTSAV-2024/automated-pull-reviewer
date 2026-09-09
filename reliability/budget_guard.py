class BudgetGuard:
    """Hard-blocks new LLM calls once the day's spend (read from agent_events,
    the same table the cost dashboard reads) reaches the daily cap. Checked
    before each call, not reconciled after (ADR-004)."""

    def __init__(self, conn, daily_cap_usd: float):
        self.conn = conn
        self.daily_cap_usd = daily_cap_usd

    def spend_today(self) -> float:
        with self.conn.cursor() as cur:
            cur.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM agent_events WHERE created_at >= date_trunc('day', now())")
            return float(cur.fetchone()[0])

    def check(self) -> bool:
        """True if under the daily cap; False (hard-block) once it's reached."""
        return self.spend_today() < self.daily_cap_usd
