"""Handler for token metrics queries."""

from aef_domain.contexts.observability.domain.queries.get_token_metrics import (
    GetTokenMetricsQuery,
)
from aef_domain.contexts.observability.domain.read_models.token_metrics import (
    SessionTokenMetrics,
)
from aef_domain.contexts.observability.slices.token_metrics.projection import (
    TokenMetricsProjection,
)


class TokenMetricsHandler:
    """Handles GetTokenMetricsQuery by querying the projection."""

    def __init__(self, projection: TokenMetricsProjection):
        """Initialize with the token metrics projection.

        Args:
            projection: The TokenMetricsProjection instance to query.
        """
        self._projection = projection

    async def handle(self, query: GetTokenMetricsQuery) -> SessionTokenMetrics:
        """Execute the query and return token metrics.

        Args:
            query: The query parameters.

        Returns:
            SessionTokenMetrics for the requested session.
        """
        metrics = await self._projection.get_metrics(query.session_id)

        # Optionally exclude individual records
        if not query.include_records:
            # Return metrics without records
            metrics = SessionTokenMetrics(
                session_id=metrics.session_id,
                records=(),  # Empty tuple
                total_input_tokens=metrics.total_input_tokens,
                total_output_tokens=metrics.total_output_tokens,
                total_cache_creation_tokens=metrics.total_cache_creation_tokens,
                total_cache_read_tokens=metrics.total_cache_read_tokens,
                total_tokens=metrics.total_tokens,
                message_count=metrics.message_count,
            )

        return metrics
