# tests for representatives (scaffold)

import pytest

from class_management.permissions.classes import IsAdminUser


def test_is_admin_user_class_exists():
    assert IsAdminUser is not None

