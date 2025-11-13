# app/application_items/import_config.py
from __future__ import annotations
from app.application_data_import.config.base_config import DoctypeConfig, FieldSpec

ITEM_IMPORT_CONFIG = DoctypeConfig(
    doctype="Item",
    fields=[
        FieldSpec(name="name", label="Item Name", value_type="str", required=True),
        FieldSpec(name="item_group", label="Item Group", value_type="str", required=True, is_reference=True, ref_target="ItemGroup"),
        FieldSpec(name="base_uom", label="Base UOM", value_type="str", required=False, is_reference=True, ref_target="UOM"),
        FieldSpec(name="brand", label="Brand", value_type="str", required=False, is_reference=True, ref_target="Brand"),
        FieldSpec(name="sku", label="Item Code (SKU)", value_type="str", required=False),
        FieldSpec(name="item_type", label="Item Type", value_type="str", required=False, allowed=["Stock", "Service"], default="Stock"),
        FieldSpec(name="description", label="Description", value_type="str", required=False),
        FieldSpec(name="is_fixed_asset", label="Is Fixed Asset", value_type="bool", required=False, default=False),
        FieldSpec(name="asset_category", label="Asset Category", value_type="str", required=False, is_reference=True, ref_target="AssetCategory"),
        # UPDATE keys
        FieldSpec(name="update_by_sku", label="Update By SKU", value_type="str", required=False, update_key=True),
        FieldSpec(name="update_by_name", label="Update By Name", value_type="str", required=False, update_key=True),
    ],
    allowed_filetypes=["csv", "excel"],
    update_keys=["update_by_sku", "update_by_name"],
    branch_required=False,
)
