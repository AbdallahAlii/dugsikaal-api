
import ast
import sys
import os

def verify_rbac_ast():
    file_path = "app/seed_data/rbac/data.py"
    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        return

    with open(file_path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())

    default_roles = []
    role_permission_map = {}

    for node in tree.body:
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        
        for target in targets:
            if isinstance(target, ast.Name):
                if target.id == "DEFAULT_ROLES":
                    # Parse list of dicts
                    if isinstance(node.value, ast.List):
                        for elt in node.value.elts:
                            if isinstance(elt, ast.Dict):
                                role_name = None
                                for key, value in zip(elt.keys, elt.values):
                                    if isinstance(key, ast.Constant) and key.value == "name":
                                        role_name = value.value
                                if role_name:
                                    default_roles.append(role_name)
                
                elif target.id == "ROLE_PERMISSION_MAP":
                        # Parse dict
                        if isinstance(node.value, ast.Dict):
                            for key, value in zip(node.value.keys, node.value.values):
                                if isinstance(key, ast.Constant): # key is string
                                    role_permission_map[key.value] = True # value is list, just need existence

    print(f"Found {len(default_roles)} roles in DEFAULT_ROLES: {default_roles}")
    print(f"Found {len(role_permission_map)} roles in ROLE_PERMISSION_MAP: {list(role_permission_map.keys())}")

    defined_set = set(default_roles)
    mapped_set = set(role_permission_map.keys())

    missing_defs = mapped_set - defined_set
    if missing_defs:
        print(f"[ERROR] Roles in Permission Map but NOT defined in DEFAULT_ROLES: {missing_defs}")
        sys.exit(1)
    
    unused_roles = defined_set - mapped_set
    if unused_roles:
        print(f"[WARNING] Roles defined but have NO permissions: {unused_roles}")
    
    print("[OK] RBAC Data structure verified successfully.")

if __name__ == "__main__":
    verify_rbac_ast()
