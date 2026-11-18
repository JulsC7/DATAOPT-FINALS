from django.urls import path
from . import views

app_name = 'dashboard'

urlpatterns = [
    path('', views.customer_profile_dashboard, name='home'),
    path('governance/customer-profile/', views.customer_profile_dashboard, name='customer_profile'),
    path('sales/', views.sales_dashboard, name='sales'),
    path('revenue-loss/', views.revenue_loss_dashboard, name='revenue_loss'),
    path('cost/', views.cost_dashboard, name='cost'),
    path('switch-role/', views.switch_role, name='switch_role'),
]