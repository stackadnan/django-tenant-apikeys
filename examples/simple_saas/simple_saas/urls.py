from django.contrib import admin
from django.urls import path
from organizations.views import WhoAmIView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/whoami/", WhoAmIView.as_view(), name="whoami"),
]
