from django.urls import path, re_path
from orders import views

urlpatterns = [
    path("api/health", views.health),
    path("api/orders", views.orders),
    path("api/orders/export", views.export),
    path("api/orders/<uuid:order_id>", views.detail),
    path("api/orders/<uuid:order_id>/retry", views.retry),
    path("api/orders/<uuid:order_id>/download", views.download),
    re_path(r"^(?P<path>.*)$", views.frontend),
]
