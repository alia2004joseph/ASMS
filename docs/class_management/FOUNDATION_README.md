# FOUNDATION README for the scaffold

This scaffold adds a minimal class_management package with representative
assignment skeletons, permission class placeholders, and a small notifications
wrapper.

Important constraints:
- This scaffold does NOT modify settings.py or INSTALLED_APPS.
- No migrations are created or applied by this scaffold.
- The model files are provided as a design artifact. Do NOT add the app to
  INSTALLED_APPS or run migrations until you explicitly approve doing so.

Files added:
- class_management/representatives/models.py  (model skeleton)
- class_management/representatives/serializers.py
- class_management/representatives/views.py
- class_management/representatives/urls.py
- class_management/permissions/classes.py
- class_management/notifications/services.py
- class_management/api/urls.py

Testing:
- The scaffold includes minimal test placeholders that import small portions
  of the scaffold and do not perform DB writes. CI should validate linting
  and import-only behavior.

Next steps after review and explicit approval:
1) Add apps to INSTALLED_APPS
2) Create and run migrations
3) Implement serializers, viewsets, and service-layer logic
4) Integrate with frontend routes and build UI components

