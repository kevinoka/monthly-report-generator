from django.urls import path

from . import views

app_name = "reports"
urlpatterns = [
    path("", views.report_list, name="list"),
    path("generate/", views.generate, name="generate"),
    path("<int:pk>/", views.detail, name="detail"),
    path("<int:pk>/download/<str:kind>/", views.download, name="download"),
    path("<int:pk>/regenerate/", views.regenerate, name="regenerate"),
    path("<int:pk>/approve/", views.approve, name="approve"),
    path("<int:pk>/send/", views.send, name="send"),
]
