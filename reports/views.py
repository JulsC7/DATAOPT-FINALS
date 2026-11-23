import csv
import json

from django.db import connections
from django.http import HttpResponse
from django.shortcuts import render, redirect

from .models import AuditLog, RoleModulePermission, UserAccount
from .rbac import (
    ALL_MANAGEABLE_MODULES,
    Departments,
    Role_Permission,
    get_role_modules,
    get_user_context,
    log_audit_event,
    require_module_access,
    seed_default_role_permissions,
)


DB_ALIAS = 'default'

COUNTRY_NAMES = {
    'AU': 'Australia',
    'CA': 'Canada',
    'DE': 'Germany',
    'FR': 'France',
    'GB': 'United Kingdom',
    'US': 'United States',
}


USER_ACCOUNTS = {
    'admin': {
        'password': '123',
        'role': 'Administrator',
        'department': 'All',
    },
    'manager': {
        'password': '123',
        'role': 'Manager',
        'department': 'All',
    },
    'supervisor': {
        'password': '123',
        'role': 'Supervisor',
        'department': 'Sales',
    },
    'sales_analyst': {
        'password': '123',
        'role': 'Sales Analyst',
        'department': 'Sales',
    },
    'customer_analyst': {
        'password': '123',
        'role': 'Customer Analyst',
        'department': 'Customer',
    },
    'financial_analyst': {
        'password': '123',
        'role': 'Financial Analyst',
        'department': 'Revenue',
    },
    'cost_analyst': {
        'password': '123',
        'role': 'Cost Analyst',
        'department': 'Cost',
    },
}


def seed_default_user_accounts():
    for username, account in USER_ACCOUNTS.items():
        UserAccount.objects.get_or_create(
            username=username,
            defaults={
                'password': account['password'],
                'role': account['role'],
                'department': account['department'],
            }
        )


def get_country_name(country_code):
    return COUNTRY_NAMES.get(country_code, country_code or 'Unknown')


def dictfetchall(cursor):
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def money(value):
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return "0.00"


def number(value):
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "0"


def compact_number(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "0"

    abs_value = abs(value)

    if abs_value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.1f}B"
    if abs_value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if abs_value >= 1_000:
        return f"{value / 1_000:.1f}K"

    return f"{value:.0f}"


def get_selected_filters(request):
    selected_years = [
        year for year in request.GET.getlist('years')
        if year.isdigit()
    ]
    selected_countries = [
        country.strip() for country in request.GET.getlist('countries')
        if country.strip()
    ]
    return selected_years, selected_countries


def get_selected_months(request):
    return [
        month for month in request.GET.getlist('months')
        if month.isdigit() and 1 <= int(month) <= 12
    ]


def get_selected_categories(request):
    return [
        category for category in request.GET.getlist('categories')
        if category.isdigit()
    ]


def get_selected_customer_types(request):
    return [
        customer_type for customer_type in request.GET.getlist('customer_types')
        if customer_type in ('store', 'individual')
    ]


def get_selected_channels(request):
    return [
        channel for channel in request.GET.getlist('channels')
        if channel in ('0', '1')
    ]


def selected_years_label(selected_years):
    return ', '.join(selected_years) if selected_years else 'All Years'


def selected_countries_label(selected_countries):
    if not selected_countries:
        return 'All Countries'

    return ', '.join([
        get_country_name(country)
        for country in selected_countries
    ])


def selected_months_label(selected_months):
    month_names = {
        '1': 'Jan',
        '2': 'Feb',
        '3': 'Mar',
        '4': 'Apr',
        '5': 'May',
        '6': 'Jun',
        '7': 'Jul',
        '8': 'Aug',
        '9': 'Sep',
        '10': 'Oct',
        '11': 'Nov',
        '12': 'Dec',
    }

    if not selected_months:
        return 'All Months'

    return ', '.join([
        month_names.get(month, month)
        for month in selected_months
    ])


def selected_channels_label(selected_channels):
    channel_names = {
        '1': 'Online',
        '0': 'Reseller',
    }

    if not selected_channels:
        return 'All Channels'

    return ', '.join([
        channel_names.get(channel, channel)
        for channel in selected_channels
    ])


def selected_customer_types_label(selected_customer_types):
    type_names = {
        'store': 'Store',
        'individual': 'Individual',
    }

    if not selected_customer_types:
        return 'All Types'

    return ', '.join([
        type_names.get(customer_type, customer_type)
        for customer_type in selected_customer_types
    ])


def selected_categories_label(selected_categories, categories):
    if not selected_categories:
        return 'All Categories'

    category_lookup = {
        str(category['ProductCategoryID']): category['Name']
        for category in categories
    }

    return ', '.join([
        category_lookup.get(category, category)
        for category in selected_categories
    ])


def build_sales_filter_clause(selected_years, selected_countries, order_alias='soh', territory_alias='st'):
    conditions = ["1=1"]
    params = []

    if selected_years:
        placeholders = ", ".join(["%s"] * len(selected_years))
        conditions.append(f"YEAR({order_alias}.OrderDate) IN ({placeholders})")
        params.extend([int(year) for year in selected_years])

    if selected_countries:
        placeholders = ", ".join(["%s"] * len(selected_countries))
        conditions.append(f"{territory_alias}.CountryRegionCode IN ({placeholders})")
        params.extend(selected_countries)

    return " AND ".join(conditions), params


def load_years_and_countries(cursor):
    cursor.execute("""
        SELECT DISTINCT YEAR(OrderDate) AS Yr
        FROM Sales.SalesOrderHeader
        ORDER BY Yr DESC
    """)
    available_years = [row['Yr'] for row in dictfetchall(cursor)]

    cursor.execute("""
        SELECT DISTINCT CountryRegionCode
        FROM Sales.SalesTerritory
        WHERE CountryRegionCode IS NOT NULL
        ORDER BY CountryRegionCode
    """)
    countries = [
        {
            'code': row['CountryRegionCode'],
            'name': get_country_name(row['CountryRegionCode']),
        }
        for row in dictfetchall(cursor)
    ]

    return available_years, countries


def render_csv_response(rows, filename):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}.csv"'

    writer = csv.writer(response)

    if rows:
        writer.writerow(rows[0].keys())
        for row in rows:
            writer.writerow(row.values())
    else:
        writer.writerow(['No data found'])

    return response


def simplify_audit_action(action, detail=''):
    action = action or ''
    detail_str = str(detail or '')
    detail_lower = detail_str.lower()
    lowered = action.lower()

    if 'login' in lowered:
        return 'Signed in'
    if 'logout' in lowered:
        return 'Signed out'
    if 'export' in lowered:
        return 'Exported report'
    if 'rbac' in lowered or 'created account' in detail_lower or 'updated account' in detail_lower or 'deleted account' in detail_lower or 'updated role page access' in detail_lower:
        return detail_str.strip() or 'Updated RBAC settings'
    if '?' in action:
        return 'Filtered data'
    if action.startswith('GET'):
        return 'Viewed page'
    if action.startswith('POST'):
        return detail_str.strip() or 'Updated settings'

    return 'System activity'


def get_audit_page(action):
    action = action or ''
    lowered = action.lower()

    page_map = {
        'dashboard': 'Dashboard',
        'sales': 'Sales',
        'customers': 'Customers',
        'revenue': 'Revenue & Loss',
        'cost': 'Products',
        'rbac': 'RBAC',
        'audit': 'Audit Logs',
        'settings': 'Settings',
        'export': 'Export Reports',
        'login': 'Login',
        'logout': 'Logout',
    }

    for key, label in page_map.items():
        if key in lowered:
            return label

    return 'Application'


def get_audit_result(status):
    status = status or ''

    if status in ('LOGIN', 'LOGOUT', 'EXPORT'):
        return 200
    if 'DENIED' in status or '403' in status:
        return 403
    if 'ERROR' in status or '500' in status:
        return 500

    return 200


def readable_audit_result(status):
    status = status or ''

    if status in ('LOGIN', 'LOGOUT', 'EXPORT') or '200' in status or 'ALLOWED' in status:
        return 'Completed'
    if 'DENIED' in status or '403' in status:
        return 'Blocked'
    if 'ERROR' in status or '500' in status:
        return 'Failed'

    return 'Recorded'


def get_ordered_user_accounts():
    account_order = [
        'admin',
        'manager',
        'supervisor',
        'financial_analyst',
        'cost_analyst',
        'customer_analyst',
        'sales_analyst',
    ]

    accounts = {
        account.username: account
        for account in UserAccount.objects.exclude(role='Employee')
    }

    ordered_accounts = [
        accounts[username]
        for username in account_order
        if username in accounts
    ]

    remaining_accounts = [
        account
        for username, account in accounts.items()
        if username not in account_order
    ]

    return ordered_accounts + sorted(remaining_accounts, key=lambda account: account.username)


# -------------------------------------------------------------------
# Authentication Views
# -------------------------------------------------------------------
def login_view(request):
    try:
        seed_default_user_accounts()
        seed_default_role_permissions()
    except Exception:
        pass

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '').strip()

        if not username or not password:
            return render(request, 'reports/login.html', {
                'error': 'Please enter both your username and password.',
                'username': username,
            })

        account = UserAccount.objects.filter(username=username).first()

        if not account or account.password != password:
            return render(request, 'reports/login.html', {
                'error': 'Invalid username or password.',
                'username': username,
            })

        role = account.role
        department = account.department

        if role not in Role_Permission:
            role = 'Employee'

        selected_departments = [
            dept.strip()
            for dept in str(department or '').split(',')
            if dept.strip() in Departments
        ]

        if not selected_departments:
            selected_departments = ['Sales']

        department = ','.join(selected_departments)

        request.session.flush()
        request.session['is_authenticated'] = True
        request.session['username'] = username
        request.session['active_role'] = role
        request.session['active_department'] = department

        log_audit_event(
            request,
            role,
            department,
            'POST /login/',
            'LOGIN',
            'User logged in successfully'
        )
        return redirect('dashboard')

    return render(request, 'reports/login.html')


def logout_view(request):
    role = request.session.get('active_role', 'Employee')
    dept = request.session.get('active_department', 'Sales')

    if request.session.get('is_authenticated'):
        log_audit_event(
            request,
            role,
            dept,
            'GET /logout/',
            'LOGOUT',
            'Session ended'
        )

    request.session.flush()
    return redirect('login')


# -------------------------------------------------------------------
# Workspace Settings
# -------------------------------------------------------------------
def settings_view(request):
    if not request.session.get('is_authenticated'):
        return redirect('login')

    ctx = get_user_context(request, active_page='settings')
    saved = False

    if request.method == 'POST':
        theme_mode = request.POST.get('theme_mode', 'light').strip()
        palette = request.POST.get('palette', 'default').strip()
        kpi_format = request.POST.get('kpi_format', 'compact').strip()
        table_density = request.POST.get('table_density', 'comfortable').strip()

        if theme_mode not in ('light', 'dark', 'system'):
            theme_mode = 'light'
        if palette not in ('default', 'high_contrast', 'emerald_teal', 'colorblind_safe'):
            palette = 'default'
        if kpi_format not in ('compact', 'full'):
            kpi_format = 'compact'
        if table_density not in ('comfortable', 'compact'):
            table_density = 'comfortable'

        request.session['pref_theme_mode'] = theme_mode
        request.session['pref_palette'] = palette
        request.session['pref_kpi_format'] = kpi_format
        request.session['pref_table_density'] = table_density

        log_audit_event(
            request,
            ctx['active_role'],
            ctx['active_department'],
            'POST /settings/',
            'ALLOWED (200)',
            f"Updated preferences: theme={theme_mode}, palette={palette}, kpi={kpi_format}, density={table_density}"
        )
        saved = True

    ctx.update({
        'saved': saved,
        'pref_theme_mode': request.session.get('pref_theme_mode', 'light'),
        'pref_palette': request.session.get('pref_palette', 'default'),
        'pref_kpi_format': request.session.get('pref_kpi_format', 'compact'),
        'pref_table_density': request.session.get('pref_table_density', 'comfortable'),
    })

    return render(request, 'reports/settings.html', ctx)


# -------------------------------------------------------------------
# Dashboard
# -------------------------------------------------------------------
@require_module_access('dashboard')
def dashboard_overview(request):
    ctx = get_user_context(request, active_page='dashboard')

    selected_years, selected_countries = get_selected_filters(request)
    where_clause, params = build_sales_filter_clause(selected_years, selected_countries)

    kpi = {
        'total_revenue': 0,
        'total_orders': 0,
        'active_customers': 0,
        'countries': 0,
        'avg_order_value': 0,
        'online_orders': 0,
    }
    available_years = []
    countries = []
    revenue_by_country = []
    revenue_by_year = []
    top_territories = []
    is_single_year = len(selected_years) == 1
    single_year_label = selected_years[0] if is_single_year else ''
    year_chart_labels_list = []
    year_chart_values_list = []

    try:
        with connections[DB_ALIAS].cursor() as cursor:
            available_years, countries = load_years_and_countries(cursor)

            cursor.execute(f"""
                SELECT
                    CAST(ISNULL(SUM(soh.TotalDue), 0) AS DECIMAL(18, 2)) AS total_revenue,
                    COUNT(soh.SalesOrderID) AS total_orders,
                    COUNT(DISTINCT soh.CustomerID) AS active_customers,
                    COUNT(DISTINCT st.CountryRegionCode) AS countries,
                    CAST(ISNULL(AVG(soh.TotalDue), 0) AS DECIMAL(18, 2)) AS avg_order_value,
                    SUM(CASE WHEN soh.OnlineOrderFlag = 1 THEN 1 ELSE 0 END) AS online_orders
                FROM Sales.SalesOrderHeader soh
                LEFT JOIN Sales.SalesTerritory st ON soh.TerritoryID = st.TerritoryID
                WHERE {where_clause}
            """, params)
            rows = dictfetchall(cursor)

            if rows:
                kpi = rows[0]

            cursor.execute(f"""
                SELECT
                    st.CountryRegionCode,
                    CAST(ISNULL(SUM(soh.TotalDue), 0) AS DECIMAL(18, 2)) AS TotalRevenue,
                    COUNT(soh.SalesOrderID) AS TotalOrders
                FROM Sales.SalesOrderHeader soh
                LEFT JOIN Sales.SalesTerritory st ON soh.TerritoryID = st.TerritoryID
                WHERE {where_clause}
                GROUP BY st.CountryRegionCode
                ORDER BY TotalRevenue DESC
            """, params)
            revenue_by_country = dictfetchall(cursor)

            for row in revenue_by_country:
                row['CountryName'] = get_country_name(row.get('CountryRegionCode'))
                row['TotalRevenueDisplay'] = money(row.get('TotalRevenue'))
                row['TotalOrdersDisplay'] = number(row.get('TotalOrders'))

            if is_single_year:
                cursor.execute(f"""
                    SELECT
                        MONTH(soh.OrderDate) AS SalesMonth,
                        CAST(ISNULL(SUM(soh.TotalDue), 0) AS DECIMAL(18, 2)) AS TotalRevenue,
                        COUNT(soh.SalesOrderID) AS TotalOrders
                    FROM Sales.SalesOrderHeader soh
                    LEFT JOIN Sales.SalesTerritory st ON soh.TerritoryID = st.TerritoryID
                    WHERE {where_clause}
                    GROUP BY MONTH(soh.OrderDate)
                    ORDER BY SalesMonth
                """, params)
                monthly_rows = dictfetchall(cursor)
                month_labels_map = {
                    1: 'Jan', 2: 'Feb', 3: 'Mar', 4: 'Apr', 5: 'May', 6: 'Jun',
                    7: 'Jul', 8: 'Aug', 9: 'Sep', 10: 'Oct', 11: 'Nov', 12: 'Dec',
                }
                revenue_by_year = monthly_rows
                year_chart_labels_list = [
                    month_labels_map.get(int(row['SalesMonth']), str(row['SalesMonth']))
                    for row in monthly_rows
                ]
                year_chart_values_list = [
                    float(row['TotalRevenue'])
                    for row in monthly_rows
                ]
            else:
                cursor.execute(f"""
                    SELECT
                        YEAR(soh.OrderDate) AS SalesYear,
                        CAST(ISNULL(SUM(soh.TotalDue), 0) AS DECIMAL(18, 2)) AS TotalRevenue,
                        COUNT(soh.SalesOrderID) AS TotalOrders
                    FROM Sales.SalesOrderHeader soh
                    LEFT JOIN Sales.SalesTerritory st ON soh.TerritoryID = st.TerritoryID
                    WHERE {where_clause}
                    GROUP BY YEAR(soh.OrderDate)
                    ORDER BY SalesYear
                """, params)
                revenue_by_year = dictfetchall(cursor)
                year_chart_labels_list = [
                    str(row['SalesYear'])
                    for row in revenue_by_year
                ]
                year_chart_values_list = [
                    float(row['TotalRevenue'])
                    for row in revenue_by_year
                ]

            cursor.execute(f"""
                SELECT TOP 5
                    st.Name AS TerritoryName,
                    st.CountryRegionCode,
                    CAST(ISNULL(SUM(soh.TotalDue), 0) AS DECIMAL(18, 2)) AS TotalRevenue,
                    COUNT(soh.SalesOrderID) AS TotalOrders
                FROM Sales.SalesOrderHeader soh
                LEFT JOIN Sales.SalesTerritory st ON soh.TerritoryID = st.TerritoryID
                WHERE {where_clause}
                GROUP BY st.Name, st.CountryRegionCode
                ORDER BY TotalRevenue DESC
            """, params)
            top_territories = dictfetchall(cursor)

            for row in top_territories:
                row['CountryName'] = get_country_name(row.get('CountryRegionCode'))
                row['TotalRevenueDisplay'] = money(row.get('TotalRevenue'))
                row['TotalOrdersDisplay'] = number(row.get('TotalOrders'))

    except Exception as e:
        ctx['db_warning'] = str(e)

    kpi['total_revenue_display'] = money(kpi.get('total_revenue'))
    kpi['total_orders_display'] = number(kpi.get('total_orders'))
    kpi['active_customers_display'] = number(kpi.get('active_customers'))
    kpi['countries_display'] = number(kpi.get('countries'))
    kpi['avg_order_value_display'] = money(kpi.get('avg_order_value'))
    kpi['online_orders_display'] = number(kpi.get('online_orders'))

    kpi['total_revenue_compact'] = compact_number(kpi.get('total_revenue'))
    kpi['total_orders_compact'] = compact_number(kpi.get('total_orders'))
    kpi['active_customers_compact'] = compact_number(kpi.get('active_customers'))
    kpi['countries_compact'] = compact_number(kpi.get('countries'))
    kpi['avg_order_value_compact'] = compact_number(kpi.get('avg_order_value'))
    kpi['online_orders_compact'] = compact_number(kpi.get('online_orders'))

    ctx.update({
        'kpi': kpi,
        'available_years': available_years,
        'countries': countries,
        'selected_years': selected_years,
        'selected_countries': selected_countries,
        'selected_years_label': selected_years_label(selected_years),
        'selected_countries_label': selected_countries_label(selected_countries),
        'is_single_year': is_single_year,
        'single_year_label': single_year_label,
        'revenue_by_country': revenue_by_country,
        'revenue_by_year': revenue_by_year,
        'top_territories': top_territories,
        'country_chart_labels': json.dumps([
            row.get('CountryName', 'Unknown')
            for row in revenue_by_country
        ]),
        'country_chart_values': json.dumps([
            float(row['TotalRevenue'])
            for row in revenue_by_country
        ]),
        'year_chart_labels': json.dumps(year_chart_labels_list),
        'year_chart_values': json.dumps(year_chart_values_list),
    })

    return render(request, 'reports/dashboard.html', ctx)


# -------------------------------------------------------------------
# Governance: RBAC Management
# -------------------------------------------------------------------
@require_module_access('rbac_management')
def rbac_management(request):
    ctx = get_user_context(request, active_page='rbac_management')

    try:
        seed_default_user_accounts()
        seed_default_role_permissions()
    except Exception as e:
        ctx['db_warning'] = f'User account or role permission table is not ready yet. Run migrations. Details: {e}'

    if request.method == 'POST':
        if not ctx['can_edit_rbac']:
            return HttpResponse('RBAC edit denied for this role.', status=403)

        action_type = request.POST.get('action_type', '').strip()
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '').strip()
        role = request.POST.get('role', '').strip()

        selected_departments = [
            department.strip()
            for department in request.POST.getlist('departments')
            if department.strip() in Departments
        ]

        if 'All' in selected_departments:
            selected_departments = ['All']

        if not selected_departments:
            selected_departments = ['Sales']

        department_value = ','.join(selected_departments)

        try:
            if action_type == 'create':
                if username and password and role in Role_Permission:
                    UserAccount.objects.create(
                        username=username,
                        password=password,
                        role=role,
                        department=department_value,
                    )
                    log_audit_event(
                        request,
                        request.session.get('active_role', 'Employee'),
                        request.session.get('active_department', 'Sales'),
                        'POST /rbac/',
                        'ALLOWED (200)',
                        f"Created account '{username}' with role '{role}' and department(s) '{department_value}'"
                    )

            elif action_type == 'update':
                account = UserAccount.objects.filter(username=username).first()

                if account and role in Role_Permission:
                    old_role = account.role
                    old_dept = account.department
                    old_password = account.password

                    changes = []
                    if old_role != role:
                        changes.append(f"role '{old_role}' -> '{role}'")
                    if old_dept != department_value:
                        changes.append(f"department '{old_dept}' -> '{department_value}'")
                    if password and password != old_password:
                        changes.append("changed password")

                    account.role = role
                    account.department = department_value
                    if password:
                        account.password = password

                    account.save(update_fields=['role', 'department', 'password'])

                    detail_msg = (
                        f"Updated account '{username}' ({', '.join(changes)})"
                        if changes
                        else f"Updated account '{username}' (no field changes)"
                    )

                    log_audit_event(
                        request,
                        request.session.get('active_role', 'Employee'),
                        request.session.get('active_department', 'Sales'),
                        'POST /rbac/',
                        'ALLOWED (200)',
                        detail_msg
                    )

            elif action_type == 'delete':
                account = UserAccount.objects.filter(username=username).first()

                if account and username != 'admin':
                    deleted_role = account.role
                    account.delete()
                    log_audit_event(
                        request,
                        request.session.get('active_role', 'Employee'),
                        request.session.get('active_department', 'Sales'),
                        'POST /rbac/',
                        'ALLOWED (200)',
                        f"Deleted account '{username}' (was role '{deleted_role}')"
                    )

            elif action_type == 'update_role_modules':
                target_role = request.POST.get('role_name', '').strip()
                valid_module_keys = [m[0] for m in ALL_MANAGEABLE_MODULES]
                selected_modules = [
                    mod.strip()
                    for mod in request.POST.getlist('modules')
                    if mod.strip() in valid_module_keys
                ]

                if target_role in Role_Permission and target_role != 'Administrator':
                    if 'dashboard' not in selected_modules:
                        selected_modules.insert(0, 'dashboard')
                    if 'reports_library' not in selected_modules:
                        selected_modules.append('reports_library')

                    modules_csv = ','.join(selected_modules)
                    perm_obj, _ = RoleModulePermission.objects.get_or_create(role_name=target_role)
                    old_modules_csv = perm_obj.allowed_modules
                    perm_obj.allowed_modules = modules_csv
                    perm_obj.save(update_fields=['allowed_modules'])

                    log_audit_event(
                        request,
                        request.session.get('active_role', 'Employee'),
                        request.session.get('active_department', 'Sales'),
                        'POST /rbac/',
                        'ALLOWED (200)',
                        f"Updated role page access for '{target_role}': '{old_modules_csv}' -> '{modules_csv}'"
                    )

        except Exception as e:
            ctx['db_warning'] = f'Unable to save RBAC assignment: {e}'

        return redirect('rbac_management')

    try:
        user_accounts = get_ordered_user_accounts()
    except Exception as e:
        user_accounts = []
        ctx['db_warning'] = f'Unable to load user accounts. Run migrations. Details: {e}'

    role_matrix = {}
    for key, value in Role_Permission.items():
        if key == 'Employee':
            continue
        entry = dict(value)
        entry['effective_modules'] = get_role_modules(key)
        role_matrix[key] = entry

    ctx['role_matrix'] = role_matrix
    ctx['departments'] = Departments
    ctx['user_accounts'] = user_accounts
    ctx['manageable_modules'] = ALL_MANAGEABLE_MODULES

    return render(request, 'reports/rbac.html', ctx)


# -------------------------------------------------------------------
# Governance: Audit Logs
# -------------------------------------------------------------------
@require_module_access('audit_logs')
def audit_logs_view(request):
    ctx = get_user_context(request, active_page='audit_logs')

    audit_logs = []

    try:
        audit_logs = list(AuditLog.objects.all()[:100]) if ctx['can_view_audit'] else []

        for log in audit_logs:
            log.simple_action = simplify_audit_action(log.action, log.detail)
            log.page_name = get_audit_page(log.action)
            log.result_code = get_audit_result(log.status)
            log.result_label = readable_audit_result(log.status)

    except Exception as e:
        ctx['db_warning'] = f'Unable to load audit logs: {e}'

    ctx['audit_logs'] = audit_logs

    return render(request, 'reports/audit_logs.html', ctx)


def reports_library(request):
    return redirect('dashboard')


# -------------------------------------------------------------------
# Sales
# -------------------------------------------------------------------
@require_module_access('sales')
def sales_dashboard(request):
    ctx = get_user_context(request, active_page='sales')

    selected_years, selected_countries = get_selected_filters(request)
    selected_months = get_selected_months(request)
    selected_channels = get_selected_channels(request)

    where_clause, params = build_sales_filter_clause(selected_years, selected_countries)

    # Special filters for territory (excludes countries by passing an empty list)
    territory_where, territory_params = build_sales_filter_clause(selected_years, [])

    if selected_months:
        month_placeholders = ", ".join(["%s"] * len(selected_months))
        month_sql = f" AND MONTH(soh.OrderDate) IN ({month_placeholders})"

        where_clause += month_sql
        territory_where += month_sql

        month_ints = [int(month) for month in selected_months]
        params.extend(month_ints)
        territory_params.extend(month_ints)

    if selected_channels:
        channel_placeholders = ", ".join(["%s"] * len(selected_channels))
        channel_sql = f" AND soh.OnlineOrderFlag IN ({channel_placeholders})"

        where_clause += channel_sql
        territory_where += channel_sql

        channel_ints = [int(channel) for channel in selected_channels]
        params.extend(channel_ints)
        territory_params.extend(channel_ints)

    sales_trends = []
    territory_data = []
    sales_customer_directory = []
    country_performance = []
    year_comparison = []
    available_years = []
    countries = []

    month_options = [
        {'value': '1', 'label': 'January'},
        {'value': '2', 'label': 'February'},
        {'value': '3', 'label': 'March'},
        {'value': '4', 'label': 'April'},
        {'value': '5', 'label': 'May'},
        {'value': '6', 'label': 'June'},
        {'value': '7', 'label': 'July'},
        {'value': '8', 'label': 'August'},
        {'value': '9', 'label': 'September'},
        {'value': '10', 'label': 'October'},
        {'value': '11', 'label': 'November'},
        {'value': '12', 'label': 'December'},
    ]

    try:
        with connections[DB_ALIAS].cursor() as cursor:
            available_years, countries = load_years_and_countries(cursor)

            cursor.execute(f"""
                SELECT
                    YEAR(soh.OrderDate) AS SalesYear,
                    MONTH(soh.OrderDate) AS SalesMonth,
                    COUNT(soh.SalesOrderID) AS OrderCount,
                    CAST(SUM(soh.TotalDue) AS DECIMAL(18, 2)) AS TotalSales
                FROM Sales.SalesOrderHeader soh
                LEFT JOIN Sales.SalesTerritory st ON soh.TerritoryID = st.TerritoryID
                WHERE {where_clause}
                GROUP BY YEAR(soh.OrderDate), MONTH(soh.OrderDate)
                ORDER BY SalesYear, SalesMonth
            """, params)
            sales_trends = dictfetchall(cursor)

            for row in sales_trends:
                row['TotalSalesDisplay'] = money(row.get('TotalSales'))
                row['OrderCountDisplay'] = number(row.get('OrderCount'))

            cursor.execute(f"""
                SELECT
                    st.Name AS TerritoryName,
                    st.CountryRegionCode,
                    st.[Group] AS TerritoryGroup,
                    CAST(ISNULL(SUM(soh.TotalDue), 0) AS DECIMAL(18, 2)) AS TotalSales
                FROM Sales.SalesTerritory st
                LEFT JOIN Sales.SalesOrderHeader soh ON st.TerritoryID = soh.TerritoryID
                WHERE {territory_where}
                GROUP BY st.Name, st.CountryRegionCode, st.[Group]
                ORDER BY TotalSales DESC
            """, territory_params)
            territory_data = dictfetchall(cursor)

            for row in territory_data:
                row['CountryName'] = get_country_name(row.get('CountryRegionCode'))
                row['TotalSalesDisplay'] = money(row.get('TotalSales'))

            cursor.execute(f"""
                SELECT
                    st.CountryRegionCode,
                    CAST(ISNULL(SUM(soh.TotalDue), 0) AS DECIMAL(18, 2)) AS TotalSales,
                    COUNT(soh.SalesOrderID) AS TotalOrders
                FROM Sales.SalesOrderHeader soh
                LEFT JOIN Sales.SalesTerritory st ON soh.TerritoryID = st.TerritoryID
                WHERE {where_clause}
                GROUP BY st.CountryRegionCode
                ORDER BY TotalSales DESC
            """, params)
            country_performance = dictfetchall(cursor)

            for row in country_performance:
                row['CountryName'] = get_country_name(row.get('CountryRegionCode'))
                row['TotalSalesDisplay'] = money(row.get('TotalSales'))
                row['TotalOrdersDisplay'] = number(row.get('TotalOrders'))

            cursor.execute(f"""
                SELECT
                    YEAR(soh.OrderDate) AS SalesYear,
                    CAST(ISNULL(SUM(soh.TotalDue), 0) AS DECIMAL(18, 2)) AS TotalSales
                FROM Sales.SalesOrderHeader soh
                LEFT JOIN Sales.SalesTerritory st ON soh.TerritoryID = st.TerritoryID
                WHERE {where_clause}
                GROUP BY YEAR(soh.OrderDate)
                ORDER BY SalesYear
            """, params)
            year_comparison = dictfetchall(cursor)

            cursor.execute(f"""
                SELECT TOP 25
                    c.CustomerID,
                    st.Name AS TerritoryName,
                    COUNT(soh.SalesOrderID) AS TotalOrders,
                    CAST(SUM(soh.TotalDue) AS DECIMAL(18, 2)) AS LifetimeSpend
                FROM Sales.Customer c
                INNER JOIN Sales.SalesTerritory st ON c.TerritoryID = st.TerritoryID
                INNER JOIN Sales.SalesOrderHeader soh ON c.CustomerID = soh.CustomerID
                WHERE {where_clause}
                GROUP BY c.CustomerID, st.Name
                ORDER BY LifetimeSpend DESC
            """, params)
            sales_customer_directory = dictfetchall(cursor)

            for row in sales_customer_directory:
                row['TotalOrdersDisplay'] = number(row.get('TotalOrders'))
                row['LifetimeSpendDisplay'] = money(row.get('LifetimeSpend'))

    except Exception as e:
        ctx['db_warning'] = str(e)

    ctx.update({
        'sales_trends': sales_trends,
        'territory_data': territory_data,
        'sales_customer_directory': sales_customer_directory,
        'country_performance': country_performance,
        'year_comparison': year_comparison,
        'available_years': available_years,
        'countries': countries,
        'month_options': month_options,
        'selected_years': selected_years,
        'selected_countries': selected_countries,
        'selected_months': selected_months,
        'selected_channels': selected_channels,
        'selected_years_label': selected_years_label(selected_years),
        'selected_countries_label': selected_countries_label(selected_countries),
        'selected_months_label': selected_months_label(selected_months),
        'selected_channels_label': selected_channels_label(selected_channels),
        'chart_labels': json.dumps([
            f"{row['SalesYear']}-{str(row['SalesMonth']).zfill(2)}"
            for row in sales_trends
        ]),
        'chart_values': json.dumps([
            float(row['TotalSales'])
            for row in sales_trends
        ]),
        'territory_chart_labels': json.dumps([
            row['TerritoryName']
            for row in territory_data
        ]),
        'territory_chart_values': json.dumps([
            float(row['TotalSales'])
            for row in territory_data
        ]),
        'country_chart_labels': json.dumps([
            row['CountryName']
            for row in country_performance
        ]),
        'country_chart_values': json.dumps([
            float(row['TotalSales'])
            for row in country_performance
        ]),
        'year_compare_labels': json.dumps([
            str(row['SalesYear'])
            for row in year_comparison
        ]),
        'year_compare_values': json.dumps([
            float(row['TotalSales'])
            for row in year_comparison
        ]),
    })

    return render(request, 'reports/sales.html', ctx)


# -------------------------------------------------------------------
# Customers
# -------------------------------------------------------------------
@require_module_access('customers')
def customer_profile(request):
    ctx = get_user_context(request, active_page='customers')

    selected_years, selected_countries = get_selected_filters(request)
    selected_customer_types = get_selected_customer_types(request)

    where_clause, params = build_sales_filter_clause(selected_years, selected_countries)

    if selected_customer_types and len(selected_customer_types) == 1:
        if selected_customer_types[0] == 'store':
            where_clause += " AND c.StoreID IS NOT NULL"
        elif selected_customer_types[0] == 'individual':
            where_clause += " AND c.StoreID IS NULL"

    active_customers = []
    customer_directory = []
    available_years = []
    countries = []

    can_view_customer_details = ctx['active_role'] in (
        'Administrator',
        'Manager',
        'Customer Analyst',
    )

    try:
        with connections[DB_ALIAS].cursor() as cursor:
            available_years, countries = load_years_and_countries(cursor)

            cursor.execute(f"""
                SELECT
                    st.Name AS TerritoryName,
                    st.CountryRegionCode,
                    COUNT(DISTINCT c.CustomerID) AS ActiveCustomerCount
                FROM Sales.Customer c
                INNER JOIN Sales.SalesTerritory st ON c.TerritoryID = st.TerritoryID
                INNER JOIN Sales.SalesOrderHeader soh ON c.CustomerID = soh.CustomerID
                WHERE {where_clause}
                GROUP BY st.Name, st.CountryRegionCode
                ORDER BY ActiveCustomerCount DESC
            """, params)
            active_customers = dictfetchall(cursor)

            for row in active_customers:
                row['CountryName'] = get_country_name(row.get('CountryRegionCode'))
                row['ActiveCustomerCountDisplay'] = number(row.get('ActiveCustomerCount'))

            if can_view_customer_details:
                cursor.execute(f"""
                    SELECT TOP 25
                        c.CustomerID,
                        st.Name AS TerritoryName,
                        p.FirstName,
                        p.LastName,
                        pp.PhoneNumber
                    FROM Sales.Customer c
                    INNER JOIN Sales.SalesTerritory st ON c.TerritoryID = st.TerritoryID
                    INNER JOIN Sales.SalesOrderHeader soh ON c.CustomerID = soh.CustomerID
                    LEFT JOIN Person.Person p ON c.PersonID = p.BusinessEntityID
                    LEFT JOIN Person.PersonPhone pp ON p.BusinessEntityID = pp.BusinessEntityID
                    WHERE {where_clause}
                    GROUP BY c.CustomerID, st.Name, p.FirstName, p.LastName, pp.PhoneNumber
                    ORDER BY c.CustomerID
                """, params)
                customer_directory = dictfetchall(cursor)

                for row in customer_directory:
                    first_name = row.get('FirstName') or ''
                    last_name = row.get('LastName') or ''
                    row['DisplayName'] = f"{first_name} {last_name}".strip() or 'Unknown'
                    row['DisplayPhone'] = row.get('PhoneNumber') or 'N/A'

    except Exception as e:
        ctx['db_warning'] = str(e)

    ctx.update({
        'active_customers': active_customers,
        'customer_directory': customer_directory,
        'available_years': available_years,
        'countries': countries,
        'selected_years': selected_years,
        'selected_countries': selected_countries,
        'selected_customer_types': selected_customer_types,
        'selected_years_label': selected_years_label(selected_years),
        'selected_countries_label': selected_countries_label(selected_countries),
        'selected_customer_types_label': selected_customer_types_label(selected_customer_types),
        'can_view_customer_details': can_view_customer_details,
        'chart_labels': json.dumps([row['TerritoryName'] for row in active_customers]),
        'chart_values': json.dumps([int(row['ActiveCustomerCount']) for row in active_customers]),
    })

    return render(request, 'reports/customers.html', ctx)


# -------------------------------------------------------------------
# Revenue
# -------------------------------------------------------------------
@require_module_access('revenue')
def revenue_loss(request):
    ctx = get_user_context(request, active_page='revenue')

    selected_years, selected_countries = get_selected_filters(request)
    selected_categories = get_selected_categories(request)
    top_n_raw = request.GET.get('top_n', '15').strip()
    top_n = int(top_n_raw) if top_n_raw in ('10', '15', '25', '50') else 15

    where_clause, filter_params = build_sales_filter_clause(selected_years, selected_countries)

    params = [top_n] + filter_params

    if selected_categories:
        placeholders = ", ".join(["%s"] * len(selected_categories))
        where_clause += f" AND pc.ProductCategoryID IN ({placeholders})"
        params.extend([int(category) for category in selected_categories])

    revenue_data = []
    categories = []
    available_years = []
    countries = []

    try:
        with connections[DB_ALIAS].cursor() as cursor:
            available_years, countries = load_years_and_countries(cursor)

            cursor.execute("SELECT ProductCategoryID, Name FROM Production.ProductCategory ORDER BY Name")
            categories = dictfetchall(cursor)

            cursor.execute(f"""
                SELECT TOP (%s)
                    p.Name AS ProductName,
                    ISNULL(pc.Name, 'Uncategorized') AS CategoryName,
                    CAST(SUM(sod.LineTotal) AS DECIMAL(18, 2)) AS NetRevenue,
                    CAST(SUM(sod.UnitPrice * sod.OrderQty * sod.UnitPriceDiscount) AS DECIMAL(18, 2)) AS DiscountLoss
                FROM Sales.SalesOrderDetail sod
                INNER JOIN Sales.SalesOrderHeader soh ON sod.SalesOrderID = soh.SalesOrderID
                LEFT JOIN Sales.SalesTerritory st ON soh.TerritoryID = st.TerritoryID
                INNER JOIN Production.Product p ON sod.ProductID = p.ProductID
                LEFT JOIN Production.ProductSubcategory psc ON p.ProductSubcategoryID = psc.ProductSubcategoryID
                LEFT JOIN Production.ProductCategory pc ON psc.ProductCategoryID = pc.ProductCategoryID
                WHERE {where_clause}
                GROUP BY p.Name, pc.Name
                HAVING SUM(sod.UnitPriceDiscount) > 0
                ORDER BY DiscountLoss DESC
            """, params)
            revenue_data = dictfetchall(cursor)

            for row in revenue_data:
                row['NetRevenueDisplay'] = money(row.get('NetRevenue'))
                row['DiscountLossDisplay'] = money(row.get('DiscountLoss'))

    except Exception as e:
        ctx['db_warning'] = str(e)

    selected_categories_display = selected_categories_label(selected_categories, categories)

    ctx.update({
        'revenue_data': revenue_data,
        'categories': categories,
        'available_years': available_years,
        'countries': countries,
        'selected_years': selected_years,
        'selected_countries': selected_countries,
        'selected_categories': selected_categories,
        'selected_years_label': selected_years_label(selected_years),
        'selected_countries_label': selected_countries_label(selected_countries),
        'selected_categories_label': selected_categories_display,
        'top_n': str(top_n),
        'chart_labels': json.dumps([row['ProductName'][:22] for row in revenue_data]),
        'chart_net': json.dumps([float(row['NetRevenue']) for row in revenue_data]),
        'chart_loss': json.dumps([float(row['DiscountLoss']) for row in revenue_data]),
    })

    return render(request, 'reports/revenue.html', ctx)


# -------------------------------------------------------------------
# Cost / Products
# -------------------------------------------------------------------
@require_module_access('cost')
def cost_report(request):
    ctx = get_user_context(request, active_page='cost')

    selected_years, selected_countries = get_selected_filters(request)
    selected_categories = get_selected_categories(request)
    search_query = request.GET.get('search', '').strip()
    min_margin_raw = request.GET.get('min_margin', '').strip()

    where_clause, params = build_sales_filter_clause(selected_years, selected_countries)

    cost_data = []
    accessory_data = []
    categories = []
    available_years = []
    countries = []

    try:
        with connections[DB_ALIAS].cursor() as cursor:
            available_years, countries = load_years_and_countries(cursor)

            cursor.execute("SELECT ProductCategoryID, Name FROM Production.ProductCategory ORDER BY Name")
            categories = dictfetchall(cursor)

            product_conditions = [
                "p.StandardCost > 0",
                "p.ListPrice > 0",
            ]
            product_params = []

            if selected_categories:
                placeholders = ", ".join(["%s"] * len(selected_categories))
                product_conditions.append(f"pc.ProductCategoryID IN ({placeholders})")
                product_params.extend([int(category) for category in selected_categories])

            if search_query:
                product_conditions.append("(p.Name LIKE %s OR p.ProductNumber LIKE %s)")
                product_params.extend([f"%{search_query}%", f"%{search_query}%"])

            if min_margin_raw.isdigit():
                product_conditions.append("(p.ListPrice - p.StandardCost) >= %s")
                product_params.append(float(min_margin_raw))

            product_where_clause = " AND ".join(product_conditions)

            cursor.execute(f"""
                SELECT
                    p.Name AS ProductName,
                    p.ProductNumber,
                    ISNULL(pc.Name, 'Uncategorized') AS CategoryName,
                    CAST(p.StandardCost AS DECIMAL(18, 2)) AS StandardCost,
                    CAST(p.ListPrice AS DECIMAL(18, 2)) AS ListPrice,
                    CAST((p.ListPrice - p.StandardCost) AS DECIMAL(18, 2)) AS UnitMargin
                FROM Production.Product p
                LEFT JOIN Production.ProductSubcategory psc ON p.ProductSubcategoryID = psc.ProductSubcategoryID
                LEFT JOIN Production.ProductCategory pc ON psc.ProductCategoryID = pc.ProductCategoryID
                WHERE {product_where_clause}
                ORDER BY p.Name
            """, product_params)
            cost_data = dictfetchall(cursor)

            for row in cost_data:
                row['StandardCostDisplay'] = money(row.get('StandardCost'))
                row['ListPriceDisplay'] = money(row.get('ListPrice'))
                row['UnitMarginDisplay'] = money(row.get('UnitMargin'))

                # --- START NEW CODE ---
                accessory_where_clause = where_clause
                accessory_params = list(params)  # Create a copy of the base params

                if selected_categories:
                    cat_placeholders = ", ".join(["%s"] * len(selected_categories))
                    accessory_where_clause += f" AND pc.ProductCategoryID IN ({cat_placeholders})"
                    accessory_params.extend([int(cat) for cat in selected_categories])
                # --- END NEW CODE ---

            cursor.execute(f"""
                SELECT
                    ISNULL(pc.Name, 'Uncategorized') AS CategoryName,
                    CAST(SUM(sod.LineTotal) AS DECIMAL(18, 2)) AS TotalRevenue,
                    COUNT(DISTINCT p.ProductID) AS ProductCount
                FROM Sales.SalesOrderDetail sod
                INNER JOIN Sales.SalesOrderHeader soh ON sod.SalesOrderID = soh.SalesOrderID
                LEFT JOIN Sales.SalesTerritory st ON soh.TerritoryID = st.TerritoryID
                INNER JOIN Production.Product p ON sod.ProductID = p.ProductID
                LEFT JOIN Production.ProductSubcategory psc ON p.ProductSubcategoryID = psc.ProductSubcategoryID
                LEFT JOIN Production.ProductCategory pc ON psc.ProductCategoryID = pc.ProductCategoryID
                WHERE {accessory_where_clause}
                GROUP BY pc.Name
                ORDER BY TotalRevenue DESC
            """, accessory_params)
            accessory_data = dictfetchall(cursor)

    except Exception as e:
        ctx['db_warning'] = str(e)

    selected_categories_display = selected_categories_label(selected_categories, categories)

    ctx.update({
        'cost_data': cost_data,
        'accessory_data': accessory_data,
        'categories': categories,
        'available_years': available_years,
        'countries': countries,
        'selected_years': selected_years,
        'selected_countries': selected_countries,
        'selected_categories': selected_categories,
        'selected_years_label': selected_years_label(selected_years),
        'selected_countries_label': selected_countries_label(selected_countries),
        'selected_categories_label': selected_categories_display,
        'search_query': search_query,
        'min_margin': min_margin_raw,
        'chart_labels': json.dumps([row['ProductName'][:22] for row in cost_data[:25]]),
        'chart_cost': json.dumps([float(row['StandardCost']) for row in cost_data[:25]]),
        'chart_price': json.dumps([float(row['ListPrice']) for row in cost_data[:25]]),
        'chart_margin': json.dumps([float(row['UnitMargin']) for row in cost_data[:25]]),
        'accessory_chart_labels': json.dumps([row['CategoryName'] for row in accessory_data]),
        'accessory_chart_values': json.dumps([float(row['TotalRevenue']) for row in accessory_data]),
        'category_count_chart_values': json.dumps([int(row['ProductCount']) for row in accessory_data]),
    })

    return render(request, 'reports/cost.html', ctx)


# -------------------------------------------------------------------
# Territories
# -------------------------------------------------------------------
@require_module_access('territories')
def sales_territories(request):
    ctx = get_user_context(request, active_page='territories')

    selected_years, selected_countries = get_selected_filters(request)
    where_clause, params = build_sales_filter_clause(selected_years, selected_countries)

    territory_data = []
    available_years = []
    countries = []

    try:
        with connections[DB_ALIAS].cursor() as cursor:
            available_years, countries = load_years_and_countries(cursor)

            cursor.execute(f"""
                SELECT
                    st.Name AS TerritoryName,
                    st.CountryRegionCode,
                    st.[Group] AS TerritoryGroup,
                    CAST(ISNULL(SUM(soh.TotalDue), 0) AS DECIMAL(18, 2)) AS TotalSales
                FROM Sales.SalesTerritory st
                LEFT JOIN Sales.SalesOrderHeader soh ON st.TerritoryID = soh.TerritoryID
                WHERE {where_clause}
                GROUP BY st.Name, st.CountryRegionCode, st.[Group]
                ORDER BY TotalSales DESC
            """, params)
            territory_data = dictfetchall(cursor)

    except Exception as e:
        ctx['db_warning'] = str(e)

    ctx.update({
        'territory_data': territory_data,
        'available_years': available_years,
        'countries': countries,
        'selected_years': selected_years,
        'selected_countries': selected_countries,
        'chart_labels': json.dumps([row['TerritoryName'] for row in territory_data]),
        'chart_values': json.dumps([float(row['TotalSales']) for row in territory_data]),
    })

    return render(request, 'reports/territories.html', ctx)


# -------------------------------------------------------------------
# Export
# -------------------------------------------------------------------
@require_module_access('dashboard')
def export_report(request, report_key, export_type):
    ctx = get_user_context(request)

    if not ctx['can_export']:
        return HttpResponse('Export denied for this role.', status=403)

    rows = []
    filename = f'{report_key}_report'

    try:
        with connections[DB_ALIAS].cursor() as cursor:
            if report_key == 'dashboard':
                cursor.execute("""
                    SELECT
                        st.CountryRegionCode AS Country,
                        COUNT(soh.SalesOrderID) AS TotalOrders,
                        CAST(ISNULL(SUM(soh.TotalDue), 0) AS DECIMAL(18, 2)) AS TotalRevenue
                    FROM Sales.SalesOrderHeader soh
                    LEFT JOIN Sales.SalesTerritory st ON soh.TerritoryID = st.TerritoryID
                    GROUP BY st.CountryRegionCode
                    ORDER BY TotalRevenue DESC
                """)
                rows = dictfetchall(cursor)
                for row in rows:
                    row['Country'] = get_country_name(row.get('Country'))

            elif report_key == 'sales':
                cursor.execute("""
                    SELECT
                        YEAR(OrderDate) AS SalesYear,
                        MONTH(OrderDate) AS SalesMonth,
                        COUNT(SalesOrderID) AS TotalOrders,
                        CAST(SUM(TotalDue) AS DECIMAL(18, 2)) AS TotalSales
                    FROM Sales.SalesOrderHeader
                    GROUP BY YEAR(OrderDate), MONTH(OrderDate)
                    ORDER BY SalesYear, SalesMonth
                """)
                rows = dictfetchall(cursor)

            elif report_key == 'customers':
                cursor.execute("""
                    SELECT
                        st.Name AS TerritoryName,
                        st.CountryRegionCode,
                        COUNT(DISTINCT c.CustomerID) AS ActiveCustomers
                    FROM Sales.Customer c
                    INNER JOIN Sales.SalesTerritory st ON c.TerritoryID = st.TerritoryID
                    GROUP BY st.Name, st.CountryRegionCode
                    ORDER BY ActiveCustomers DESC
                """)
                rows = dictfetchall(cursor)

            elif report_key == 'revenue':
                cursor.execute("""
                    SELECT TOP 25
                        p.Name AS ProductName,
                        ISNULL(pc.Name, 'Uncategorized') AS CategoryName,
                        CAST(SUM(sod.LineTotal) AS DECIMAL(18, 2)) AS NetRevenue,
                        CAST(SUM(sod.UnitPrice * sod.OrderQty * sod.UnitPriceDiscount) AS DECIMAL(18, 2)) AS DiscountLoss
                    FROM Sales.SalesOrderDetail sod
                    INNER JOIN Sales.SalesOrderHeader soh ON sod.SalesOrderID = soh.SalesOrderID
                    INNER JOIN Production.Product p ON sod.ProductID = p.ProductID
                    LEFT JOIN Production.ProductSubcategory psc ON p.ProductSubcategoryID = psc.ProductSubcategoryID
                    LEFT JOIN Production.ProductCategory pc ON psc.ProductCategoryID = pc.ProductCategoryID
                    GROUP BY p.Name, pc.Name
                    HAVING SUM(sod.UnitPriceDiscount) > 0
                    ORDER BY DiscountLoss DESC
                """)
                rows = dictfetchall(cursor)

            elif report_key == 'cost':
                cursor.execute("""
                    SELECT
                        p.Name AS ProductName,
                        p.ProductNumber,
                        CAST(p.StandardCost AS DECIMAL(18, 2)) AS StandardCost,
                        CAST(p.ListPrice AS DECIMAL(18, 2)) AS ListPrice,
                        CAST((p.ListPrice - p.StandardCost) AS DECIMAL(18, 2)) AS UnitMargin
                    FROM Production.Product p
                    WHERE p.StandardCost > 0 AND p.ListPrice > 0
                    ORDER BY p.Name
                """)
                rows = dictfetchall(cursor)

            else:
                return HttpResponse('Invalid report.', status=400)

    except Exception as e:
        return HttpResponse(f'Export failed: {e}', status=500)

    log_audit_event(
        request,
        request.session.get('active_role', 'Employee'),
        request.session.get('active_department', 'Sales'),
        f'GET /export/{report_key}/{export_type}/',
        'EXPORT',
        f'Exported {report_key} as {export_type.upper()}'
    )

    if export_type == 'csv':
        return render_csv_response(rows, filename)

    if export_type == 'pdf':
        return render(request, 'reports/export_pdf.html', {
            'report_key': report_key.title(),
            'rows': rows,
        })

    return HttpResponse('Invalid export type.', status=400)