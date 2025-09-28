# # app/application_doctypes/core_dropdowns/service.py
# from __future__ import annotations
# from typing import Any, Dict, Mapping, Optional
# from app.security.rbac_effective import AffiliationContext
# from .repository import dropdown_repository
#
# class DropdownService:
#     def get_options(
#         self,
#         *,
#         module_name: str,
#         name: str,
#         user_context: AffiliationContext,
#         q: Optional[str],
#         limit: int,
#         offset: int,
#         params: Mapping[str, Any],
#         fresh: bool = False,
#         sort: Optional[str] = None,
#         order: Optional[str] = None,
#     ):
#         return dropdown_repository.get_options(
#             module_name=module_name,
#             name=name,
#             user_context=user_context,
#             q=q,
#             limit=limit,
#             offset=offset,
#             params=params,
#             fresh=fresh,
#             sort=sort,
#             order=order,
#         )
#
# dropdown_service = DropdownService()
from __future__ import annotations
from typing import Any, Dict, Mapping, Optional
from app.security.rbac_effective import AffiliationContext
from .repository import dropdown_repository

class DropdownService:
    def get_options(
        self,
        *,
        module_name: str,
        name: str,
        user_context: AffiliationContext,
        q: Optional[str],
        limit: int,
        offset: int,
        params: Mapping[str, Any],
        fresh: bool = False,
        sort: Optional[str] = None,
        order: Optional[str] = None,
    ):
        return dropdown_repository.get_options(
            module_name=module_name,
            name=name,
            user_context=user_context,
            q=q,
            limit=limit,
            offset=offset,
            params=params,
            fresh=fresh,
            sort=sort,
            order=order,
        )

dropdown_service = DropdownService()
