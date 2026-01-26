from __future__ import annotations
from typing import List, Optional
from pydantic import BaseModel

class DocFieldOut(BaseModel):
    fieldname: str
    label: Optional[str]
    fieldtype: str
    options: Optional[str] = None
    default: Optional[str] = None
    reqd: bool
    read_only: bool
    hidden: bool
    in_list_view: bool
    in_filter: bool
    in_quick_entry: bool
    idx: int
    description: Optional[str] = None

class DocPermissionOut(BaseModel):
    role: str
    level: int
    can_read: bool
    can_write: bool
    can_create: bool
    can_delete: bool
    can_submit: bool
    can_cancel: bool
    can_amend: bool

class DocLinkOut(BaseModel):
    parent_doctype: str
    link_doctype: str
    link_fieldname: Optional[str]
    group_label: Optional[str]

class DoctypeMetaOut(BaseModel):
    name: str
    label: str
    module: str
    table_name: str
    icon: Optional[str]
    is_child: bool
    is_single: bool
    is_tree: bool
    is_submittable: bool
    track_changes: bool
    track_seen: bool
    track_views: bool
    quick_entry: bool
    description: Optional[str]

    fields: List[DocFieldOut]
    permissions: List[DocPermissionOut]
    links: List[DocLinkOut] = []
class ListViewFieldUpdateIn(BaseModel):
    """
    Single field update for list view.

    - fieldname: existing fieldname in DocField
    - in_list_view: show/hide in list
    - idx: order of the column
    - in_filter / in_quick_entry are optional extras (future use)
    """
    fieldname: str
    in_list_view: Optional[bool] = None
    idx: Optional[int] = None
    in_filter: Optional[bool] = None
    in_quick_entry: Optional[bool] = None


class ListViewUpdateIn(BaseModel):
    """
    Payload for PATCH /api/meta/doctype/<name>/listview

    - company_id: which company this config applies to
      (if omitted, we will use ctx.company_id)
    - fields: list of field updates
    """
    company_id: Optional[int] = None
    fields: List[ListViewFieldUpdateIn]