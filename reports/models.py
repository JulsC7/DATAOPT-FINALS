from django.db import models


class AuditLog(models.Model):
    timestamp = models.DateTimeField(auto_now_add=True)
    username = models.CharField(max_length=100)
    role = models.CharField(max_length=50)
    department = models.CharField(max_length=100)
    action = models.CharField(max_length=200)
    status = models.CharField(max_length=30)
    detail = models.TextField(blank=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"[{self.timestamp:%Y-%m-%d %H:%M:%S}] {self.username} - {self.status}"


class UserAccount(models.Model):
    username = models.CharField(max_length=100, unique=True)
    password = models.CharField(max_length=100)
    role = models.CharField(max_length=50)
    department = models.CharField(max_length=100)

    class Meta:
        ordering = ['username']

    @property
    def department_list(self):
        return [
            department.strip()
            for department in self.department.split(',')
            if department.strip()
        ]

    @property
    def department_display(self):
        return ', '.join(self.department_list)

    def __str__(self):
        return f"{self.username} - {self.role}"


class RoleModulePermission(models.Model):
    role_name = models.CharField(max_length=50, unique=True)
    allowed_modules = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['role_name']

    @property
    def module_list(self):
        return [
            module.strip()
            for module in str(self.allowed_modules or '').split(',')
            if module.strip()
        ]

    def __str__(self):
        return f"{self.role_name}: {self.allowed_modules}"

from django.db import models


class CustomReport(models.Model):
    title = models.CharField(max_length=150)
    created_by = models.CharField(max_length=100)
    selected_widgets = models.TextField(default='kpi_summary,chart_country,chart_trend')
    filters_json = models.TextField(default='{}')
    analyst_notes = models.TextField(blank=True, default='')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def widget_list(self):
        return [w.strip() for w in self.selected_widgets.split(',') if w.strip()]
  