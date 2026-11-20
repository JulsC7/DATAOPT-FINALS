from django.contrib import admin
from django.urls import path
from reports import views

urlpatterns = [
    path('admin/', admin.site.urls),

    # Authentication
    path('', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),

    # Main pages
    path('dashboard/', views.dashboard_overview, name='dashboard'),
    path('sales/', views.sales_dashboard, name='sales'),
    path('customers/', views.customer_profile, name='customers'),
    path('revenue/', views.revenue_loss, name='revenue'),
    path('cost/', views.cost_report, name='cost'),

    # Governance
    path('rbac-audit/', views.rbac_audit, name='rbac_audit'),

    # Export reports
    path('export/<str:report_key>/<str:export_type>/', views.export_report, name='export_report'),

    # Optional direct territory page; not shown in sidebar
    path('territories/', views.sales_territories, name='territories'),
]