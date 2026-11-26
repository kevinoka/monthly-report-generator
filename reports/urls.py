from django.urls import path

from . import views

app_name = "reports"
urlpatterns = [
    path("", views.report_list, name="list"),
    path("generate/", views.generate, name="generate"),
    path("<int:pk>/", views.detail, name="detail"),
    path("<int:pk>/status/", views.status, name="status"),
    path("status/", views.status_many, name="status_many"),
    path("<int:pk>/download/<str:kind>/", views.download, name="download"),
    path("<int:pk>/regenerate/", views.regenerate, name="regenerate"),
    path("<int:pk>/approve/", views.approve, name="approve"),
    path("<int:pk>/send/", views.send, name="send"),
]
