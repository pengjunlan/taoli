"""Compatibility facade for split arbitrage execution persistence modules."""

from __future__ import annotations

from app.infrastructure.persistence.arbitrage_repo.commands import ArbitrageExecutionRepositoryCommandsMixin
from app.infrastructure.persistence.arbitrage_repo.execution_queries import (
    ArbitrageExecutionRepositoryExecutionQueriesMixin,
)
from app.infrastructure.persistence.arbitrage_repo.order_queries import ArbitrageExecutionRepositoryOrderQueriesMixin
from app.infrastructure.persistence.arbitrage_repo.position_queries import (
    ArbitrageExecutionRepositoryPositionQueriesMixin,
)


class MySQLArbitrageExecutionRepository(
    ArbitrageExecutionRepositoryCommandsMixin,
    ArbitrageExecutionRepositoryExecutionQueriesMixin,
    ArbitrageExecutionRepositoryOrderQueriesMixin,
    ArbitrageExecutionRepositoryPositionQueriesMixin,
):
    """Facade that preserves the original repository API while delegating by concern."""


arbitrage_execution_repository = MySQLArbitrageExecutionRepository()
