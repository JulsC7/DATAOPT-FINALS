import csv
import json

from django.db import connections
from django.http import HttpResponse
from django.shortcuts import render, redirect

from .models import AuditLog, UserAccount
from .rbac import (
    Departments,
    Role_Permission,
    get_user_context,
    log_audit_event,
    require_module_access,
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

def get_country_name(country_code):
    return COUNTRY_NAMES.get(country_code, country_code or 'Unknown')

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


def simplify_audit_action(action):
    action = action or ''
    lowered = action.lower()

    if 'login' in lowered:
        return 'Signed in'
    if 'logout' in lowered:
        return 'Signed out'
    if 'export' in lowered:
        return 'Exported report'
    if '?' in action:
        return 'Filtered data'
    if action.startswith('GET'):
        return 'Viewed page'
    if action.startswith('POST'):
        return 'Updated settings'

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
        'rbac': 'RBAC & Audit Logs',
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


# -------------------------------------------------------------------
# Authentication Views
# -------------------------------------------------------------------
def login_view(request):
    try:
        seed_default_user_accounts()
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

    ctx.update({
        'kpi': kpi,
        'available_years': available_years,
        'countries': countries,
        'selected_years': selected_years,
        'selected_countries': selected_countries,
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
        'year_chart_labels': json.dumps([
            str(row['SalesYear'])
            for row in revenue_by_year
        ]),
        'year_chart_values': json.dumps([
            float(row['TotalRevenue'])
            for row in revenue_by_year
        ]),
    })

    return render(request, 'reports/dashboard.html', ctx)


# -------------------------------------------------------------------
# Governance
# -------------------------------------------------------------------
@require_module_access('rbac_audit')
def rbac_audit(request):
    ctx = get_user_context(request, active_page='rbac_audit')

    try:
        seed_default_user_accounts()
    except Exception as e:
        ctx['db_warning'] = f'User account table is not ready yet. Run migrations. Details: {e}'

    if request.method == 'POST':
        if not ctx['can_edit_rbac']:
            return HttpResponse('RBAC edit denied for this role.', status=403)

        username = request.POST.get('username', '').strip()
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
            account = UserAccount.objects.filter(username=username).first()

            if account and role in Role_Permission:
                account.role = role
                account.department = department_value
                account.save(update_fields=['role', 'department'])

                log_audit_event(
                    request,
                    request.session.get('active_role', 'Employee'),
                    request.session.get('active_department', 'Sales'),
                    'POST /rbac-audit/',
                    'ALLOWED (200)',
                    f'Updated RBAC profile for {username}'
                )

        except Exception as e:
            ctx['db_warning'] = f'Unable to update RBAC assignment: {e}'

        return redirect('rbac_audit')

    audit_logs = []
    user_accounts = []

    try:
        audit_logs = AuditLog.objects.all()[:50] if ctx['can_view_audit'] else []

        for log in audit_logs:
            log.simple_action = simplify_audit_action(log.action)
            log.page_name = get_audit_page(log.action)
            log.result_code = get_audit_result(log.status)

    except Exception as e:
        ctx['db_warning'] = f'Unable to load audit logs: {e}'

    try:
        user_accounts = get_ordered_user_accounts()
    except Exception as e:
        ctx['db_warning'] = f'Unable to load user accounts. Run migrations. Details: {e}'

    ctx['role_matrix'] = {
        key: value
        for key, value in Role_Permission.items()
        if key != 'Employee'
    }
    ctx['departments'] = Departments
    ctx['audit_logs'] = audit_logs
    ctx['user_accounts'] = user_accounts

    return render(request, 'reports/rbac_audit.html', ctx)

# -------------------------------------------------------------------
# Sales
# -------------------------------------------------------------------
@require_module_access('sales')
def sales_dashboard(request):
    ctx = get_user_context(request, active_page='sales')

    selected_years, selected_countries = get_selected_filters(request)
    selected_channels = get_selected_channels(request)

    where_clause, params = build_sales_filter_clause(selected_years, selected_countries)

    if selected_channels:
        channel_placeholders = ", ".join(["%s"] * len(selected_channels))
        where_clause += f" AND soh.OnlineOrderFlag IN ({channel_placeholders})"
        params.extend([int(channel) for channel in selected_channels])

    sales_trends = []
    territory_data = []
    sales_customer_directory = []
    available_years = []
    countries = []

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
                WHERE {where_clause}
                GROUP BY st.Name, st.CountryRegionCode, st.[Group]
                ORDER BY TotalSales DESC
            """, params)
            territory_data = dictfetchall(cursor)

            for row in territory_data:
                row['CountryName'] = get_country_name(row.get('CountryRegionCode'))
                row['TotalSalesDisplay'] = money(row.get('TotalSales'))

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
        'available_years': available_years,
        'countries': countries,
        'selected_years': selected_years,
        'selected_countries': selected_countries,
        'selected_channel': selected_channels,
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
        category_placeholders = ", ".join(["%s"] * len(selected_categories))
        where_clause += f" AND pc.ProductCategoryID IN ({category_placeholders})"
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

    ctx.update({
        'revenue_data': revenue_data,
        'categories': categories,
        'available_years': available_years,
        'countries': countries,
        'selected_years': selected_years,
        'selected_countries': selected_countries,
        'selected_categories': selected_categories,
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

    conditions = [
        where_clause,
        "p.StandardCost > 0",
        "p.ListPrice > 0",
    ]

    if selected_categories:
        category_placeholders = ", ".join(["%s"] * len(selected_categories))
        conditions.append(f"pc.ProductCategoryID IN ({category_placeholders})")
        params.extend([int(category) for category in selected_categories])

    if search_query:
        conditions.append("(p.Name LIKE %s OR p.ProductNumber LIKE %s)")
        params.extend([f"%{search_query}%", f"%{search_query}%"])

    if min_margin_raw.isdigit():
        conditions.append("(p.ListPrice - p.StandardCost) >= %s")
        params.append(float(min_margin_raw))

    final_where_clause = " AND ".join(conditions)

    cost_data = []
    categories = []
    available_years = []
    countries = []

    try:
        with connections[DB_ALIAS].cursor() as cursor:
            available_years, countries = load_years_and_countries(cursor)

            cursor.execute("SELECT ProductCategoryID, Name FROM Production.ProductCategory ORDER BY Name")
            categories = dictfetchall(cursor)

            cursor.execute(f"""
                SELECT TOP 25
                    p.Name AS ProductName,
                    p.ProductNumber,
                    ISNULL(pc.Name, 'Uncategorized') AS CategoryName,
                    CAST(p.StandardCost AS DECIMAL(18, 2)) AS StandardCost,
                    CAST(p.ListPrice AS DECIMAL(18, 2)) AS ListPrice,
                    CAST((p.ListPrice - p.StandardCost) AS DECIMAL(18, 2)) AS UnitMargin
                FROM Sales.SalesOrderDetail sod
                INNER JOIN Sales.SalesOrderHeader soh ON sod.SalesOrderID = soh.SalesOrderID
                LEFT JOIN Sales.SalesTerritory st ON soh.TerritoryID = st.TerritoryID
                INNER JOIN Production.Product p ON sod.ProductID = p.ProductID
                LEFT JOIN Production.ProductSubcategory psc ON p.ProductSubcategoryID = psc.ProductSubcategoryID
                LEFT JOIN Production.ProductCategory pc ON psc.ProductCategoryID = pc.ProductCategoryID
                WHERE {final_where_clause}
                GROUP BY p.Name, p.ProductNumber, pc.Name, p.StandardCost, p.ListPrice
                ORDER BY p.StandardCost DESC
            """, params)
            cost_data = dictfetchall(cursor)

            for row in cost_data:
                row['StandardCostDisplay'] = money(row.get('StandardCost'))
                row['ListPriceDisplay'] = money(row.get('ListPrice'))
                row['UnitMarginDisplay'] = money(row.get('UnitMargin'))

    except Exception as e:
        ctx['db_warning'] = str(e)

    ctx.update({
        'cost_data': cost_data,
        'categories': categories,
        'available_years': available_years,
        'countries': countries,
        'selected_years': selected_years,
        'selected_countries': selected_countries,
        'selected_categories': selected_categories,
        'search_query': search_query,
        'min_margin': min_margin_raw,
        'chart_labels': json.dumps([row['ProductName'][:22] for row in cost_data]),
        'chart_cost': json.dumps([float(row['StandardCost']) for row in cost_data]),
        'chart_price': json.dumps([float(row['ListPrice']) for row in cost_data]),
        'chart_margin': json.dumps([float(row['UnitMargin']) for row in cost_data]),
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
                    SELECT TOP 25
                        p.Name AS ProductName,
                        p.ProductNumber,
                        CAST(p.StandardCost AS DECIMAL(18, 2)) AS StandardCost,
                        CAST(p.ListPrice AS DECIMAL(18, 2)) AS ListPrice,
                        CAST((p.ListPrice - p.StandardCost) AS DECIMAL(18, 2)) AS UnitMargin
                    FROM Production.Product p
                    WHERE p.StandardCost > 0 AND p.ListPrice > 0
                    ORDER BY p.StandardCost DESC
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