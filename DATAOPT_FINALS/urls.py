from django.contrib import admin
from django.urls import path
from reports import views

urlpatterns = [
    path('admin/', admin.site.urls),

    # Authentication & Governance Portal Routes
    path('', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('dashboard/', views.dashboard_overview, name='dashboard'),
    path('rbac-audit/', views.rbac_audit, name='rbac_audit'),
    path('reports-library/', views.reports_library, name='reports_library'),

    # Your Friend's Original 4 Module Routes (Preserved)
    path('sales/', views.sales_dashboard, name='sales'),
    path('customers/', views.customer_profile, name='customers'),
    path('revenue/', views.revenue_loss, name='revenue'),
    path('cost/', views.cost_report, name='cost'),

    # Dedicated Route for Sales Territories
    path('territories/', views.sales_territories, name='territories'),
]