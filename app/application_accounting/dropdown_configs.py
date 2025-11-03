# app/application_accounting/dropdown_configs.py
from __future__ import annotations

from app.application_doctypes.core_dropdowns.config import DropdownConfig, register_dropdown_configs
from app.application_doctypes.core_lists.config import CacheScope

from app.application_accounting.chart_of_accounts.account_policies import ModeOfPayment, ModeOfPaymentAccount, AccountAccessPolicy
from app.application_accounting.chart_of_accounts.models import Account  # adjust path if different
from app.application_accounting.query_builders.mop_dropdowns import (
    build_modes_of_payment_dropdown,
    build_mop_accounts_dropdown, build_vat_account_dropdown, build_asset_accounts_dropdown,
)

ACCOUNTING_DROPDOWN_CONFIGS = {
    # Pick a Mode of Payment
    "modes_of_payment": DropdownConfig(
        permission_tag="ModeOfPayment",
        query_builder=build_modes_of_payment_dropdown,
        search_fields=[ModeOfPayment.name],
        filter_fields={
            "type": ModeOfPayment.type,
            "enabled": ModeOfPayment.enabled,
        },
        cache_enabled=True,
        cache_ttl=900,  # 15 min
        cache_scope=CacheScope.COMPANY,
        default_limit=50,
        max_limit=200,
        window_when_empty=100,
    ),

    # Dependent dropdown: accounts allowed for a given MoP (requires mop_id or mode_of_payment_id)
    "mop_accounts": DropdownConfig(
        permission_tag="Account",
        query_builder=build_mop_accounts_dropdown,
        search_fields=[Account.name, Account.code],
        # These filter_fields let your dropdown infra pass params through; we read them from `params` anyway.
        filter_fields={
            "mode_of_payment_id": ModeOfPaymentAccount.mode_of_payment_id,
            "mop_id": ModeOfPaymentAccount.mode_of_payment_id,     # alias key supported by builder
            "role": AccountAccessPolicy.role,                      # optional
        },
        cache_enabled=True,
        cache_ttl=600,  # 10 min (policies can change a bit more often)
        cache_scope=CacheScope.COMPANY,
        default_limit=50,
        max_limit=200,
        window_when_empty=50,
    ),
    "vat_account": DropdownConfig(
        permission_tag="Account",
        query_builder=build_vat_account_dropdown,
        search_fields=[Account.name, Account.code],
        # Allow optional overrides via query (if you ever need): ?code=XXXX or ?name=SomeName
        filter_fields={},  # no external filters required; builder enforces company+rules
        cache_enabled=True, cache_ttl=1800, cache_scope=CacheScope.COMPANY,
        default_limit=1, max_limit=5, window_when_empty=1,
    ),
    "asset_accounts": DropdownConfig(
        permission_tag="Account",
        query_builder=build_asset_accounts_dropdown,
        search_fields=[Account.name, Account.code],
        # We pass toggles via params; no strict column binding needed here.
        filter_fields={"parent_account_id": Account.parent_account_id},
        cache_enabled=True, cache_ttl=900, cache_scope=CacheScope.COMPANY,
        default_limit=50, max_limit=200, window_when_empty=100,
    ),
}


def register_accounting_dropdowns() -> None:
    register_dropdown_configs("accounting", ACCOUNTING_DROPDOWN_CONFIGS)
