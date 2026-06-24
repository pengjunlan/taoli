"""Compatibility facade for split account persistence modules."""

from __future__ import annotations

from app.infrastructure.persistence.account_repo.accounts import AccountRepositoryAccountsMixin
from app.infrastructure.persistence.account_repo.automation import AccountRepositoryAutomationMixin
from app.infrastructure.persistence.account_repo.common import AccountRepositoryBuildersMixin
from app.infrastructure.persistence.account_repo.transfers import AccountRepositoryTransfersMixin


class MySQLAccountRepository(
    AccountRepositoryAccountsMixin,
    AccountRepositoryTransfersMixin,
    AccountRepositoryAutomationMixin,
    AccountRepositoryBuildersMixin,
):
    """Facade that preserves the original repository API while delegating by concern."""


account_repository = MySQLAccountRepository()
