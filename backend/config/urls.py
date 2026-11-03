"""Root URL configuration.

``/api/`` is the REST API, ``/admin/`` is Django's admin, and every other path
falls through to the single-page React app (when its build is present).
"""
from django.contrib import admin
from django.urls import include, path, re_path

from processor.api.spa import spa_index

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("processor.api.urls")),
    re_path(r"^(?!api/|admin/|static/).*$", spa_index, name="spa"),
]
