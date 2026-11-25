from django.urls import path

from . import views

app_name = "core"
urlpatterns = [
    path("", views.downtime_list, name="downtime_list"),
    path("new/", views.downtime_create, name="downtime_create"),
    path("<int:pk>/edit/", views.downtime_edit, name="downtime_edit"),
    path("<int:pk>/delete/", views.downtime_delete, name="downtime_delete"),
]
