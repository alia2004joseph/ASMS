"""
URL routes for representatives scaffold.
"""
from django.urls import path
from . import views

urlpatterns = [
    path("assign/", views.AssignRepresentativeView.as_view(), name="rep-assign"),
    path("", views.ListRepresentativesView.as_view(), name="rep-list"),
]
