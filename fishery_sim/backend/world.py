# world.py
import math


class Lake:
    def __init__(self, config):
        self.stock = config["lake_initial"]
        self.max_stock = config["lake_max"]
        self.regen_rate = config["regeneration_rate"]
        self.history = [self.stock]

    def apply_harvests(self, harvests: dict) -> dict:
        """
        harvests: { agent_name: amount }
        Returns: { agent_name: actual_amount } (capped if lake too low)
        """
        total_requested = sum(harvests.values())
        actual = {}

        if total_requested <= self.stock:
            actual = harvests.copy()
            self.stock -= total_requested
        else:
            # Proportional rationing if over-extraction
            ratio = self.stock / total_requested if total_requested > 0 else 0
            for name, amount in harvests.items():
                actual[name] = round(amount * ratio, 1)
            self.stock = 0

        # Regeneration
        regen = self.stock * self.regen_rate
        self.stock = min(self.stock + regen, self.max_stock)
        self.stock = round(self.stock, 1)
        self.history.append(self.stock)

        return actual

    def get_status(self) -> str:
        pct = (self.stock / self.max_stock) * 100
        if pct > 70:
            return "healthy"
        if pct > 40:
            return "declining"
        if pct > 20:
            return "critical"
        return "near collapse"

    def previous_stock(self) -> float:
        if len(self.history) >= 2:
            return self.history[-2]
        return self.history[0]
