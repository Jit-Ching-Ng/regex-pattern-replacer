from django.urls import include, path
from rest_framework.routers import DefaultRouter

from processor.api.views import DatasetViewSet, health

router = DefaultRouter(trailing_slash=True)
router.include_root_view = False
router.register("datasets", DatasetViewSet, basename="dataset")

urlpatterns = [
    path("health/", health, name="health"),
    path("", include(router.urls)),
]
