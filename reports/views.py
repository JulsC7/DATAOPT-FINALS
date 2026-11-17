from django.shortcuts import render
from django.db import connection


# Helper function to execute raw SQL and return dictionaries
def execute_query(query):
    with connection.cursor() as cursor:
        cursor.execute(query)
        columns = [col[0] for col in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]


# ---------------------------------------------------------
# FUNCTIONING MODULE 1: Sales
# ---------------------------------------------------------
def sales_dashboard(request):
    sales_trends_query = """
                         SELECT YEAR (soh.OrderDate) AS SalesYear, MONTH (soh.OrderDate) AS SalesMonth, SUM (soh.TotalDue) AS TotalSales
                         FROM Sales.SalesOrderHeader soh
                         WHERE soh.Status = 5
                         GROUP BY YEAR (soh.OrderDate), MONTH (soh.OrderDate)
                         ORDER BY SalesYear, SalesMonth \
                         """
    context = {
        'sales_trends': execute_query(sales_trends_query)
    }
    return render(request, 'reports/sales.html', context)


# ---------------------------------------------------------
# FUNCTIONING MODULE 2: Customer Profile
# ---------------------------------------------------------
def customer_profile(request):
    active_customers_query = """
                             SELECT st.Name                      AS TerritoryName, \
                                    st.CountryRegionCode, \
                                    COUNT(DISTINCT c.CustomerID) AS ActiveCustomerCount
                             FROM Sales.Customer c
                                      INNER JOIN Sales.SalesTerritory st ON c.TerritoryID = st.TerritoryID
                                      INNER JOIN Sales.SalesOrderHeader soh ON c.CustomerID = soh.CustomerID
                             WHERE soh.Status = 5
                             GROUP BY st.Name, st.CountryRegionCode
                             ORDER BY ActiveCustomerCount DESC; \
                             """
    context = {
        'active_customers': execute_query(active_customers_query)
    }
    return render(request, 'reports/customers.html', context)


# ---------------------------------------------------------
# PREPARED MODULE 3: Revenue & Loss (Backend ready, frontend pending)
# ---------------------------------------------------------
def revenue_loss(request):
    revenue_query = """
                    SELECT YEAR (soh.OrderDate) AS SalesYear, SUM (sod.LineTotal) AS TotalRevenue, SUM (p.StandardCost * sod.OrderQty) AS TotalEstimateCost, SUM (sod.LineTotal - (p.StandardCost * sod.OrderQty)) AS EstimatedGrossProfit
                    FROM Sales.SalesOrderHeader soh
                        INNER JOIN Sales.SalesOrderDetail sod \
                    ON soh.SalesOrderID = sod.SalesOrderID
                        INNER JOIN Production.Product p ON sod.ProductID = p.ProductID
                    WHERE soh.Status = 5
                    GROUP BY YEAR (soh.OrderDate)
                    ORDER BY SalesYear \
                    """
    raw_data = execute_query(revenue_query)
    return render(request, 'reports/revenue.html', {'data': raw_data})


# ---------------------------------------------------------
# PREPARED MODULE 4: Cost (Backend ready, frontend pending)
# ---------------------------------------------------------
def cost_report(request):
    cost_coverage_query = """
                          SELECT COUNT(*)                                          AS TotalProducts,
                                 SUM(CASE WHEN StandardCost > 0 THEN 1 ELSE 0 END) AS ProductsWithCost,
                                 AVG(StandardCost)                                 AS AvgCost
                          FROM Production.Product \
                          """
    raw_data = execute_query(cost_coverage_query)
    return render(request, 'reports/cost.html', {'data': raw_data})


from django.shortcuts import render

# Create your views here.
