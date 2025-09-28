# #
# # # app/application_doctypes/core_lists/service.py
#
# from __future__ import annotations
# from typing import Dict, Any, Optional
# from .repository import list_repository, detail_repository
# from app.security.rbac_effective import AffiliationContext
#
# class ListService:
#     def get_list(
#         self,
#         *,
#         module_name: str,
#         entity_name: str,
#         user_context: AffiliationContext,
#         page: int,
#         per_page: int,
#         sort: str,
#         order: str,
#         search: Optional[str],
#         filters: Optional[Dict[str, Any]],
#     ):
#         return list_repository.get_paginated_list(
#             module_name=module_name,
#             entity_name=entity_name,
#             user_context=user_context,
#             page=page,
#             per_page=per_page,
#             sort=sort,
#             order=order,
#             search=search,
#             filters=filters,
#         )
#
# list_service = ListService()
# # ==============================================================================
# # DETAIL VIEW SERVICE
# # ==============================================================================
# class DetailService:
#     def get_detail(
#         self,
#         *,
#         module_name: str,
#         entity_name: str,
#         by: Optional[str],
#         identifier: str,
#         user_context: AffiliationContext,
#         fresh: bool = False,
#     ):
#         return detail_repository.get_document_detail(
#             module_name=module_name,
#             entity_name=entity_name,
#             by=by,
#             identifier=identifier,
#             user_context=user_context,
#             fresh=fresh,
#         )
#
# detail_service = DetailService()
#
# # app/application_doctypes/core_lists/service.py

from __future__ import annotations
from typing import Dict, Any, Optional
from .repository import list_repository, detail_repository
from app.security.rbac_effective import AffiliationContext

class ListService:
    def get_list(
        self,
        *,
        module_name: str,
        entity_name: str,
        user_context: AffiliationContext,
        page: int,
        per_page: int,
        sort: str,
        order: str,
        search: Optional[str],
        filters: Optional[Dict[str, Any]],
    ):
        return list_repository.get_paginated_list(
            module_name=module_name,
            entity_name=entity_name,
            user_context=user_context,
            page=page,
            per_page=per_page,
            sort=sort,
            order=order,
            search=search,
            filters=filters,
        )

list_service = ListService()
# ==============================================================================
# DETAIL VIEW SERVICE
# ==============================================================================
class DetailService:
    def get_detail(
        self,
        *,
        module_name: str,
        entity_name: str,
        by: Optional[str],
        identifier: str,
        user_context: AffiliationContext,
        fresh: bool = False,
    ):
        return detail_repository.get_document_detail(
            module_name=module_name,
            entity_name=entity_name,
            by=by,
            identifier=identifier,
            user_context=user_context,
            fresh=fresh,
        )

detail_service = DetailService()