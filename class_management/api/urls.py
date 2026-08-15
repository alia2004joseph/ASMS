"""
API root urls for class_management scaffold.

This file only adds a router placeholder; actual viewsets will be added in
sub-apps once the design is approved and the apps are added to INSTALLED_APPS.
"""

from django.urls import include, path

urlpatterns = [
    path("representatives/", include("class_management.representatives.urls")),
    # Additional routes (materials, groups, attendance, polls, feedback) will be
    # added here when their implementations are approved.
]
