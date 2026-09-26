"""Session analytics (ARCHITECTURE.md section 18.3).

TODO: this is a stub. The real implementation should read the
TimescaleDB continuous aggregates (rho_1s, accuracy_1m) and compute
ITR from cued trials. Until that sink is wired, every field that can
be computed from free conversation is zero and the two metrics that
require cued trials (section 18.4) are null -- never a fabricated
accuracy number.
"""

from __future__ import annotations

from shared.schemas import AnalyticsSummary


class AnalyticsService:
    def summary(self) -> AnalyticsSummary:
        return AnalyticsSummary(
            accuracy_pct=None,
            itr_bits_per_min=None,
            cued_trials=0,
            mean_rho_by_target=[],
            selections_total=0,
            mean_selection_latency_s=0.0,
            drift=0.0,
        )
