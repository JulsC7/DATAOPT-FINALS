from functools import wraps
from django.shortcuts import render, redirect
from .models import AuditLog, RoleModulePermission


ALL_MANAGEABLE_MODULES = [
    ('dashboard', 'Dashboard'),
    ('sales', 'Sales'),
    ('territories', 'Territories'),
    ('customers', 'Customers'),
    ('revenue', 'Revenue & Loss'),
    ('cost', 'Products'),
    ('rbac_management', 'RBAC Management'),
    ('audit_logs', 'Audit Logs'),
    ('custom_reports', 'Custom Reports')
]


Departments = {
    'All': {
        'label': 'All Departments',
        'modules': ['sales', 'territories', 'customers', 'revenue', 'cost'],
    },
    'Sales': {
        'label': 'Sales',
        'modules': ['sales', 'territories'],
    },
    'Customer': {
        'label': 'Customer',
        'modules': ['customers'],
    },
    'Revenue': {
        'label': 'Revenue and Loss',
        'modules': ['revenue'],
    },
    'Cost': {
        'label': 'Cost',
        'modules': ['cost'],
    },
}


Role_Permission = {
    'Administrator': {
        'title': 'Administrator',
        'tag': 'ADMINISTRATOR',
        'initials': 'AD',
        'scope': 'all',
        'base_modules': [
            'dashboard',
            'reports_library',
            'sales',
            'territories',
            'customers',
            'revenue',
            'cost',
            'rbac_audit',
            'rbac_management',
            'audit_logs',
            'custom_reports'
        ],
        'can_export': True,
        'can_manage_users': True,
        'can_edit_rbac': True,
        'can_view_rbac': True,
        'can_view_audit': True,
        'can_manage_views': 'all',
        'can_share_views': True,
        'can_manage_notes': 'all',
        'aggregated_only': False,
        'mask_pii': True,
    },
    'Manager': {
        'title': 'Executive Management',
        'tag': 'MANAGER',
        'initials': 'MG',
        'scope': 'all',
        'base_modules': [
            'dashboard',
            'reports_library',
            'sales',
            'territories',
            'customers',
            'revenue',
            'cost',
        ],
        'can_export': True,
        'can_manage_users': False,
        'can_edit_rbac': False,
        'can_view_rbac': False,
        'can_view_audit': False,
        'can_manage_views': 'own',
        'can_share_views': True,
        'can_manage_notes': 'all',
        'aggregated_only': False,
        'mask_pii': True,
    },
    'Supervisor': {
        'title': 'Department Operations Supervisor',
        'tag': 'SUPERVISOR',
        'initials': 'SV',
        'scope': 'department',
        'base_modules': ['dashboard', 'reports_library'],
        'can_export': True,
        'can_manage_users': False,
        'can_edit_rbac': False,
        'can_view_rbac': False,
        'can_view_audit': False,
        'can_manage_views': 'own',
        'can_share_views': False,
        'can_manage_notes': 'own',
        'aggregated_only': False,
        'mask_pii': True,
    },
    'Sales Analyst': {
        'title': 'Sales Department Analyst',
        'tag': 'SALES ANALYST',
        'initials': 'SA',
        'scope': 'restricted',
        'base_modules': ['dashboard', 'reports_library', 'sales'],
        'can_export': False,
        'can_manage_users': False,
        'can_edit_rbac': False,
        'can_view_rbac': False,
        'can_view_audit': False,
        'can_manage_views': False,
        'can_share_views': False,
        'can_manage_notes': False,
        'aggregated_only': True,
        'mask_pii': True,
    },
    'Customer Analyst': {
        'title': 'Marketing & Customer Relations',
        'tag': 'CUSTOMER ANALYST',
        'initials': 'CA',
        'scope': 'restricted',
        'base_modules': ['dashboard', 'reports_library', 'customers'],
        'can_export': False,
        'can_manage_users': False,
        'can_edit_rbac': False,
        'can_view_rbac': False,
        'can_view_audit': False,
        'can_manage_views': False,
        'can_share_views': False,
        'can_manage_notes': False,
        'aggregated_only': True,
        'mask_pii': True,
    },
    'Financial Analyst': {
        'title': 'Finance & Accounting',
        'tag': 'FINANCIAL ANALYST',
        'initials': 'FA',
        'scope': 'restricted',
        'base_modules': ['dashboard', 'reports_library', 'revenue'],
        'can_export': False,
        'can_manage_users': False,
        'can_edit_rbac': False,
        'can_view_rbac': False,
        'can_view_audit': False,
        'can_manage_views': False,
        'can_share_views': False,
        'can_manage_notes': False,
        'aggregated_only': True,
        'mask_pii': True,
    },
    'Cost Analyst': {
        'title': 'Production & Manufacturing',
        'tag': 'COST ANALYST',
        'initials': 'PA',
        'scope': 'restricted',
        'base_modules': ['dashboard', 'reports_library', 'cost'],
        'can_export': False,
        'can_manage_users': False,
        'can_edit_rbac': False,
        'can_view_rbac': False,
        'can_view_audit': False,
        'can_manage_views': False,
        'can_share_views': False,
        'can_manage_notes': False,
        'aggregated_only': True,
        'mask_pii': True,
    },
    'Employee': {
        'title': 'Employee',
        'tag': 'EMPLOYEE',
        'initials': 'EM',
        'scope': 'all_aggregated',
        'base_modules': [
            'dashboard',
            'reports_library',
            'sales',
            'territories',
            'customers',
            'revenue',
            'cost',
        ],
        'can_export': False,
        'can_manage_users': False,
        'can_edit_rbac': False,
        'can_view_rbac': False,
        'can_view_audit': False,
        'can_manage_views': False,
        'can_share_views': False,
        'can_manage_notes': False,
        'aggregated_only': True,
        'mask_pii': True,
    },
}


def seed_default_role_permissions():
    for role_key, policy in Role_Permission.items():
        if role_key == 'Administrator':
            continue
        default_csv = ','.join(policy.get('base_modules', []))
        RoleModulePermission.objects.get_or_create(
            role_name=role_key,
            defaults={'allowed_modules': default_csv}
        )


def get_role_modules(role_key: str) -> list:
    policy = Role_Permission.get(role_key, Role_Permission['Employee'])
    default_modules = list(policy.get('base_modules', []))

    if role_key == 'Administrator':
        return default_modules

    try:
        seed_default_role_permissions()
        perm = RoleModulePermission.objects.filter(role_name=role_key).first()
        if perm is not None:
            modules = list(perm.module_list)
            if 'dashboard' in modules and 'reports_library' not in modules:
                modules.append('reports_library')
            return modules
    except Exception:
        pass

    return default_modules


def parse_departments(dept_key: str) -> list:
    departments = [
        department.strip()
        for department in str(dept_key or '').split(',')
        if department.strip()
    ]

    if not departments:
        return ['Sales']

    valid_departments = [
        department
        for department in departments
        if department in Departments
    ]

    return valid_departments or ['Sales']


def resolve_allowed_modules(role_key: str, dept_key: str) -> list:
    policy = Role_Permission.get(role_key, Role_Permission['Employee'])
    role_modules = get_role_modules(role_key)
    selected_departments = parse_departments(dept_key)

    if role_key == 'Administrator' or 'All' in selected_departments:
        return role_modules

    if policy['scope'] == 'department':
        combined_modules = list(role_modules)
        for department in selected_departments:
            dept_modules = Departments.get(department, Departments['Sales'])['modules']
            for mod in dept_modules:
                if mod in role_modules and mod not in combined_modules:
                    combined_modules.append(mod)
        return combined_modules

    return role_modules


def get_user_context(request, active_page=''):
    role_key = request.session.get('active_role', 'Employee')
    if role_key not in Role_Permission:
        role_key = 'Employee'

    dept_key = request.session.get('active_department', 'Sales')
    selected_departments = parse_departments(dept_key)

    policy = Role_Permission[role_key]
    allowed_modules = resolve_allowed_modules(role_key, dept_key)
    can_view_rbac = policy['can_view_rbac'] or ('rbac_management' in allowed_modules)
    can_view_audit = policy['can_view_audit'] or ('audit_logs' in allowed_modules)

    department_labels = [
        Departments[department]['label']
        for department in selected_departments
        if department in Departments
    ]

    department_label = ', '.join(department_labels) if department_labels else 'Sales'

    display_role = (
        f"{department_label} {policy['title']}"
        if policy['scope'] == 'department'
        else policy['title']
    )

    return {
        'username': request.session.get('username', 'aw_user'),
        'active_role': role_key,
        'active_department': dept_key,
        'active_departments': selected_departments,
        'department_label': department_label,
        'role_title': display_role,
        'tag': policy['tag'],
        'initials': policy['initials'],
        'allowed_modules': allowed_modules,
        'policy': policy,
        'can_export': policy['can_export'],
        'can_view_audit': can_view_audit,
        'can_view_rbac': can_view_rbac,
        'can_edit_rbac': policy['can_edit_rbac'],
        'can_manage_views': policy.get('can_manage_views', False),
        'can_share_views': policy.get('can_share_views', False),
        'can_manage_notes': policy.get('can_manage_notes', False),
        'aggregated_only': policy['aggregated_only'],
        'active_page': active_page,
    }


def log_audit_event(request, role_key, dept_key, action, status, detail):
    try:
        AuditLog.objects.create(
            username=request.session.get('username', 'anonymous'),
            role=role_key,
            department=dept_key,
            action=action,
            status=status,
            detail=detail,
        )
    except Exception:
        pass


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

            role_key = request.session.get('active_role', 'Employee')
            dept_key = request.session.get('active_department', 'Sales')
            policy = Role_Permission.get(role_key, Role_Permission['Employee'])
            allowed = resolve_allowed_modules(role_key, dept_key)
            can_view_rbac = policy['can_view_rbac'] or ('rbac_management' in allowed)
            can_view_audit = policy['can_view_audit'] or ('audit_logs' in allowed)

            if module_key in ('rbac_audit', 'rbac_management', 'audit_logs'):
                if module_key == 'rbac_management' and not can_view_rbac and not policy['can_edit_rbac']:
                    log_audit_event(
                        request,
                        role_key,
                        dept_key,
                        f"GET {request.path}",
                        "DENIED (403)",
                        "Unauthorized RBAC access"
                    )
                    ctx = get_user_context(request, active_page=module_key)
                    ctx['denied_module'] = "RBAC MANAGEMENT"
                    return render(request, 'reports/access_denied.html', ctx, status=403)

                if module_key == 'audit_logs' and not can_view_audit:
                    log_audit_event(
                        request,
                        role_key,
                        dept_key,
                        f"GET {request.path}",
                        "DENIED (403)",
                        "Unauthorized audit log access"
                    )
                    ctx = get_user_context(request, active_page=module_key)
                    ctx['denied_module'] = "AUDIT LOGS"
                    return render(request, 'reports/access_denied.html', ctx, status=403)

            if module_key not in allowed:
                log_audit_event(
                    request,
                    role_key,
                    dept_key,
                    f"GET {request.path}",
                    "DENIED (403)",
                    f"{role_key} ({dept_key}) blocked from '{module_key}' module"
                )
                ctx = get_user_context(request, active_page=module_key)
                ctx['denied_module'] = module_key.upper()
                return render(request, 'reports/access_denied.html', ctx, status=403)

            log_audit_event(
                request,
                role_key,
                dept_key,
                f"GET {request.path}",
                "ALLOWED (200)",
                f"Accessed '{module_key}' module"
            )
            return view_func(request, *args, **kwargs)

        return _wrapped

    return decorator