from django.shortcuts import render, redirect
from .rbac import ROLE_PERMISSIONS, require_module_access

def switch_role(request):
    if request.method == 'POST':
        selected_role = request.POST.get('role', 'Governance')
        if selected_role in ROLE_PERMISSIONS:
            request.session['active_role'] = selected_role
    return redirect('dashboard:customer_profile')

@require_module_access('customer_profile')
def customer_profile_dashboard(request):
    active_role = request.session.get('active_role', 'Governance')
    policy = ROLE_PERMISSIONS.get(active_role, ROLE_PERMISSIONS['Governance'])
    return render(request, 'dashboard/customer_profile.html', {
        'active_role': active_role,
        'policy': policy,
    })

@require_module_access('sales')
def sales_dashboard(request):
    return render(request, 'dashboard/customer_profile.html', {
        'active_role': request.session.get('active_role', 'Governance'),
    })

@require_module_access('revenue_loss')
def revenue_loss_dashboard(request):
    return render(request, 'dashboard/customer_profile.html', {
        'active_role': request.session.get('active_role', 'Governance'),
    })

@require_module_access('cost')
def cost_dashboard(request):
    return render(request, 'dashboard/customer_profile.html', {
        'active_role': request.session.get('active_role', 'Governance'),
    })