import json
from django.shortcuts import render, redirect
from django.db import connection
from functools import wraps
from .rbac import ROLE_PERMISSIONS, mask_person_name, mask_phone_number, require_module_access


# -------------------------------------------------------------------
# RBAC Role Definitions & Access Matrix
# -------------------------------------------------------------------
ROLE_CONFIG = {
    'admin': {
        'title': 'Chief Data Officer (Admin)',
        'department': 'Data Governance & Architecture',
        'clearance': 'Level 4 - Full Enterprise Read',
        'allowed_modules': ['dashboard', 'sales', 'customers', 'territories', 'revenue', 'cost', 'rbac_audit', 'reports_library'],
    },
    'sales_mgr': {
        'title': 'Sales & Territory Manager',
        'department': 'Commercial Operations',
        'clearance': 'Level 2 - Commercial Silo',
        'allowed_modules': ['dashboard', 'sales', 'customers', 'territories', 'reports_library'],
    },
    'finance_analyst': {
        'title': 'Financial Risk Analyst',
        'department': 'Finance & Controlling',
        'clearance': 'Level 2 - Financial Silo',
        'allowed_modules': ['dashboard', 'revenue', 'cost', 'reports_library'],
    },
    'viewer': {
        'title': 'General Operations Viewer',
        'department': 'Internal Audit',
        'clearance': 'Level 1 - Summary Only',
        'allowed_modules': ['dashboard', 'reports_library'],
    }
}


def get_user_context(request, active_page=''):
    role_key = request.session.get('user_role', 'admin')
    username = request.session.get('username', 'gov_admin')
    role_info = ROLE_CONFIG.get(role_key, ROLE_CONFIG['admin'])
    return {
        'username': username,
        'user_role': role_key,
        'role_title': role_info['title'],
        'department': role_info['department'],
        'clearance': role_info['clearance'],
        'allowed_modules': role_info['allowed_modules'],
        'active_page': active_page,
    }


def require_module_access(module_name):
    """Decorator enforcing session login and RBAC module permissions."""
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.session.get('is_authenticated'):
                return redirect('login')
            role_key = request.session.get('user_role', 'viewer')
            allowed = ROLE_CONFIG.get(role_key, ROLE_CONFIG['viewer'])['allowed_modules']
            if module_name not in allowed:
                ctx = get_user_context(request, active_page=module_name)
                ctx['denied_module'] = module_name.upper()
                return render(request, 'reports/403.html', ctx, status=403)
            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator


def dictfetchall(cursor):
    """Return all rows from a cursor as a list of dicts (matches friend's template keys)."""
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


# -------------------------------------------------------------------
# Authentication Views
# -------------------------------------------------------------------
def login_view(request):
    if request.method == 'POST':
        username = request.POST.get('username', 'gov_admin').strip() or 'gov_admin'
        role = request.POST.get('role', 'admin')
        if role not in ROLE_CONFIG:
            role = 'admin'
        request.session['is_authenticated'] = True
        request.session['username'] = username
        request.session['user_role'] = role
        return redirect('dashboard')
    return render(request, 'reports/login.html', {'roles': ROLE_CONFIG})


def logout_view(request):
    request.session.flush()
    return redirect('login')


# -------------------------------------------------------------------
# Main Governance Dashboard & RBAC Views
# -------------------------------------------------------------------
@require_module_access('dashboard')
def dashboard_overview(request):
    ctx = get_user_context(request, active_page='dashboard')

    # Fetch quick executive KPI summary from AdventureWorks2019
    kpi = {'total_revenue': 0, 'total_orders': 0, 'active_customers': 0, 'territories': 0}
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT
                    CAST( ISNULL(SUM(TotalDue), 0) AS DECIMAL(18,2) ) AS total_revenue,
                    COUNT(SalesOrderID) AS total_orders,
                    COUNT(DISTINCT CustomerID) AS active_customers,
                    COUNT(DISTINCT TerritoryID) AS territories
                FROM Sales.SalesOrderHeader
            """)
            row = dictfetchall(cursor)
            if row:
                kpi = row[0]
    except Exception as e:
        ctx['db_warning'] = str(e)

    ctx['kpi'] = kpi
    return render(request, 'reports/dashboard.html', ctx)


@require_module_access('rbac_audit')
def rbac_audit(request):
    ctx = get_user_context(request, active_page='rbac_audit')
    ctx['role_matrix'] = ROLE_CONFIG
    return render(request, 'reports/rbac_audit.html', ctx)


@require_module_access('reports_library')
def reports_library(request):
    ctx = get_user_context(request, active_page='reports_library')
    return render(request, 'reports/reports_library.html', ctx)


# -------------------------------------------------------------------
# Friend's 4 Core Reporting Modules (Preserving exact context names)
# -------------------------------------------------------------------
@require_module_access('sales')
def sales_dashboard(request):
    """Module 1: Total Sales Trends (Preserves friend's 'sales_trends' context key)."""
    ctx = get_user_context(request, active_page='sales')
    sales_trends = []
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT
                    YEAR(OrderDate) AS SalesYear,
                    MONTH(OrderDate) AS SalesMonth,
                    CAST(SUM(TotalDue) AS DECIMAL(18, 2)) AS TotalSales
                FROM Sales.SalesOrderHeader
                GROUP BY YEAR(OrderDate), MONTH(OrderDate)
                ORDER BY SalesYear, SalesMonth
            """)
            sales_trends = dictfetchall(cursor)
    except Exception as e:
        ctx['db_warning'] = str(e)

    ctx['sales_trends'] = sales_trends
    ctx['chart_labels'] = json.dumps([f"{r['SalesYear']}-{str(r['SalesMonth']).zfill(2)}" for r in sales_trends])
    ctx['chart_values'] = json.dumps([float(r['TotalSales']) for r in sales_trends])
    return render(request, 'reports/sales.html', ctx)


@require_module_access('customers')
def customer_profile(request):
    """Module 2: Active Customer Distribution (Preserves friend's 'active_customers' context key)."""
    ctx = get_user_context(request, active_page='customers')
    active_customers = []
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT
                    st.Name AS TerritoryName,
                    st.CountryRegionCode,
                    COUNT(DISTINCT c.CustomerID) AS ActiveCustomerCount
                FROM Sales.Customer c
                INNER JOIN Sales.SalesTerritory st ON c.TerritoryID = st.TerritoryID
                INNER JOIN Sales.SalesOrderHeader soh ON c.CustomerID = soh.CustomerID
                GROUP BY st.Name, st.CountryRegionCode
                ORDER BY ActiveCustomerCount DESC
            """)
            active_customers = dictfetchall(cursor)
    except Exception as e:
        ctx['db_warning'] = str(e)

    ctx['active_customers'] = active_customers
    ctx['chart_labels'] = json.dumps([r['TerritoryName'] for r in active_customers])
    ctx['chart_values'] = json.dumps([int(r['ActiveCustomerCount']) for r in active_customers])
    return render(request, 'reports/customers.html', ctx)


@require_module_access('revenue')
def revenue_loss(request):
    """Module 3: Revenue & Discount Impact Analysis."""
    ctx = get_user_context(request, active_page='revenue')
    revenue_data = []
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT TOP 15
                    p.Name AS ProductName,
                    pc.Name AS CategoryName,
                    CAST(SUM(sod.LineTotal) AS DECIMAL(18, 2)) AS NetRevenue,
                    CAST(SUM(sod.UnitPrice * sod.OrderQty * sod.UnitPriceDiscount) AS DECIMAL(18, 2)) AS DiscountLoss
                FROM Sales.SalesOrderDetail sod
                INNER JOIN Production.Product p ON sod.ProductID = p.ProductID
                LEFT JOIN Production.ProductSubcategory psc ON p.ProductSubcategoryID = psc.ProductSubcategoryID
                LEFT JOIN Production.ProductCategory pc ON psc.ProductCategoryID = pc.ProductCategoryID
                GROUP BY p.Name, pc.Name
                HAVING SUM(sod.UnitPriceDiscount) > 0
                ORDER BY DiscountLoss DESC
            """)
            revenue_data = dictfetchall(cursor)
    except Exception as e:
        ctx['db_warning'] = str(e)

    ctx['revenue_data'] = revenue_data
    ctx['chart_labels'] = json.dumps([r['ProductName'][:22] for r in revenue_data])
    ctx['chart_net'] = json.dumps([float(r['NetRevenue']) for r in revenue_data])
    ctx['chart_loss'] = json.dumps([float(r['DiscountLoss']) for r in revenue_data])
    return render(request, 'reports/revenue.html', ctx)


@require_module_access('cost')
def cost_report(request):
    """Module 4: Production & Standard Cost Variance Report."""
    ctx = get_user_context(request, active_page='cost')
    cost_data = []
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT TOP 15
                    p.Name AS ProductName,
                    p.ProductNumber,
                    CAST(p.StandardCost AS DECIMAL(18, 2)) AS StandardCost,
                    CAST(p.ListPrice AS DECIMAL(18, 2)) AS ListPrice,
                    CAST((p.ListPrice - p.StandardCost) AS DECIMAL(18, 2)) AS UnitMargin
                FROM Production.Product p
                WHERE p.StandardCost > 0 AND p.ListPrice > 0
                ORDER BY p.StandardCost DESC
            """)
            cost_data = dictfetchall(cursor)
    except Exception as e:
        ctx['db_warning'] = str(e)

    ctx['cost_data'] = cost_data
    ctx['chart_labels'] = json.dumps([r['ProductName'][:22] for r in cost_data])
    ctx['chart_cost'] = json.dumps([float(r['StandardCost']) for r in cost_data])
    ctx['chart_price'] = json.dumps([float(r['ListPrice']) for r in cost_data])
    return render(request, 'reports/cost.html', ctx)

@require_module_access('sales')
def sales_territories(request):
    """Module: Sales Territories Performance."""
    ctx = get_user_context(request, active_page='territories')
    territory_data = []
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT 
                    st.Name AS TerritoryName,
                    st.CountryRegionCode,
                    st.[Group] AS TerritoryGroup,
                    CAST(ISNULL(SUM(soh.TotalDue), 0) AS DECIMAL(18,2)) AS TotalSales
                FROM Sales.SalesTerritory st
                LEFT JOIN Sales.SalesOrderHeader soh ON st.TerritoryID = soh.TerritoryID
                GROUP BY st.Name, st.CountryRegionCode, st.[Group]
                ORDER BY TotalSales DESC
            """)
            territory_data = dictfetchall(cursor)
    except Exception as e:
        ctx['db_warning'] = str(e)

    ctx['territory_data'] = territory_data
    ctx['chart_labels'] = json.dumps([r['TerritoryName'] for r in territory_data])
    ctx['chart_values'] = json.dumps([float(r['TotalSales']) for r in territory_data])
    return render(request, 'reports/territories.html', ctx)