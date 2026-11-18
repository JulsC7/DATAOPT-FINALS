from functools import wraps
from django.shortcuts import render, redirect

ROLE_PERMISSIONS = {
    'Governance': {
        'label': 'Data Governance',
        'tag': 'GOVERNANCE',
        'initials': 'DG',
        'allowed_modules': ['dashboard', 'reports_library', 'customers', 'rbac_audit'],
        'can_export': True,
    },
    'Administrator': {
        'label': 'System Admin',
        'tag': 'ADMINISTRATOR',
        'initials': 'SA',
        'allowed_modules': ['dashboard', 'reports_library', 'revenue', 'cost', 'sales', 'customers', 'territories', 'rbac_audit'],
        'can_export': True,
    },
    'Manager': {
        'label': 'Exec Manager',
        'tag': 'MANAGER',
        'initials': 'EM',
        'allowed_modules': ['dashboard', 'reports_library', 'revenue', 'cost', 'sales', 'customers', 'territories', 'rbac_audit'],
        'can_export': True,
    },
    'Supervisor': {
        'label': 'Dept Supervisor',
        'tag': 'SUPERVISOR',
        'initials': 'DS',
        'allowed_modules': ['dashboard', 'reports_library', 'sales', 'customers', 'territories', 'rbac_audit'],
        'can_export': True,
    },
    'Optimization': {
        'label': 'Optimization (Sales)',
        'tag': 'OPTIMIZATION',
        'initials': 'OP',
        'allowed_modules': ['sales', 'territories', 'rbac_audit'],
        'can_export': True,
    },
    'Science': {
        'label': 'Science (Rev & Loss)',
        'tag': 'DATA SCIENCE',
        'initials': 'DS',
        'allowed_modules': ['revenue', 'rbac_audit'],
        'can_export': True,
    },
    'Engineering': {
        'label': 'Engineering (Cost)',
        'tag': 'ENGINEERING',
        'initials': 'EN',
        'allowed_modules': ['cost', 'rbac_audit'],
        'can_export': True,
    },
    'Employee': {
        'label': 'Staff Employee',
        'tag': 'EMPLOYEE',
        'initials': 'SE',
        'allowed_modules': ['dashboard', 'customers', 'rbac_audit'],
        'can_export': False,
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
            if not request.session.get('is_authenticated'):
                return redirect('login')
            active_role = request.session.get('active_role', 'Governance')
            policy = ROLE_PERMISSIONS.get(active_role, ROLE_PERMISSIONS['Employee'])
            if module_key not in policy['allowed_modules']:
                logs = request.session.get('audit_logs', [])
                logs.insert(0, {
                    'role': policy['label'],
                    'action': f'GET /{module_key}/',
                    'status': 'DENIED (403)',
                    'detail': f'Role {active_role} blocked from {module_key} module',
                })
                request.session['audit_logs'] = logs[:20]
                return render(request, 'reports/access_denied.html', {
                    'active_role': active_role,
                    'policy': policy,
                    'attempted_module': module_key,
                }, status=403)
            return view_func(request, *args, **kwargs)
        return _wrapped
    return decorator
