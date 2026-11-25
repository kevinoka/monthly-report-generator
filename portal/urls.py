from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

admin.site.site_header = "Monthly Report Generator - Admin"
admin.site.site_title = "Monthly Report Generator"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("login/", auth_views.LoginView.as_view(template_name="reports/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("downtime/", include("core.urls")),
    path("", include("reports.urls")),
]

if settings.DEBUG:  # dev only: lets admin show uploaded client logos. Reports are served via views with auth.
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
