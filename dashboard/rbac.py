from functools import wraps
from django.shortcuts import render

ROLE_PERMISSIONS = {
    'Administrator': {
        'allowed_modules': ['customer_profile', 'sales', 'revenue_loss', 'cost'],
        'can_export': True,
        'can_edit_notes': True,
        'can_save_filters': True,
        'can_configure_rbac': True,
    },
    'Manager': {
        'allowed_modules': ['customer_profile', 'sales', 'revenue_loss', 'cost'],
        'can_export': True,
        'can_edit_notes': True,
        'can_save_filters': True,
        'can_configure_rbac': False,
    },
    'Supervisor': {
        'allowed_modules': ['customer_profile', 'sales'],
        'can_export': True,
        'can_edit_notes': True,
        'can_save_filters': True,
        'can_configure_rbac': False,
    },
    'Governance': {
        'allowed_modules': ['customer_profile'],
        'can_export': True,
        'can_edit_notes': True,
        'can_save_filters': True,
        'can_configure_rbac': False,
    },
    'Optimization': {
        'allowed_modules': ['sales'],
        'can_export': True,
        'can_edit_notes': False,
        'can_save_filters': True,
        'can_configure_rbac': False,
    },
    'Science': {
        'allowed_modules': ['revenue_loss'],
        'can_export': True,
        'can_edit_notes': False,
        'can_save_filters': True,
        'can_configure_rbac': False,
    },
    'Engineering': {
        'allowed_modules': ['cost'],
        'can_export': True,
        'can_edit_notes': False,
        'can_save_filters': True,
        'can_configure_rbac': False,
    },
    'Employee': {
        'allowed_modules': ['customer_profile'],
        'can_export': False,
        'can_edit_notes': False,
        'can_save_filters': False,
        'can_configure_rbac': False,
    },
}

def mask_person_name(first_name: str, last_name: str) -> str:
    f = (first_name[0] + '*' * max(len(first_name) - 1, 2)) if first_name else '***'
    l = (last_name[0] + '*' * max(len(last_name) - 1, 3)) if last_name else '****'
    return f"{f} {l}"

def mask_phone_number(phone: str) -> str:
    digits = [c for c in str(phone or '') if c.isdigit()]
    last4 = ''.join(digits[-4:]) if len(digits) >= 4 else '0000'
    return f"***-***-{last4}"

def require_module_access(module_key: str):
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            active_role = request.session.get('active_role', 'Governance')
            policy = ROLE_PERMISSIONS.get(active_role, ROLE_PERMISSIONS['Employee'])
            if module_key not in policy['allowed_modules']:
                return render(request, 'dashboard/access_denied.html', {
                    'active_role': active_role,
                    'attempted_module': module_key,
                    'policy': policy,
                }, status=403)
            return view_func(request, *args, **kwargs)
        return _wrapped
    return decorator