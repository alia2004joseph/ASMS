from django.urls import include, path

urlpatterns = [
    path('', include('class_management.representatives.urls')),
]
