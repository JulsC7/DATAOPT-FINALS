from django.contrib import admin
from django.shortcuts import render, redirect

# -------------------------------------------------------------------
# Authentication Views
# -------------------------------------------------------------------
def login_view(request):
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '').strip()

        if not username or not password:
            return render(request, 'reports/login.html', {
                'error': 'Please enter both your username and password.',
                'username': username,
            })

        role = 'Employee'
        department = 'Sales'

        request.session['is_authenticated'] = True
        request.session['username'] = username
        request.session['active_role'] = role
        request.session['active_department'] = department

        log_audit_event(
            request, role, department,
            'POST /login/', 'LOGIN',
            'User logged in successfully'
        )
        return redirect('dashboard')

    return render(request, 'reports/login.html')
