# tests for permissions skeleton

import pytest

from class_management.permissions.classes import IsClassRepForClassroomOrSubject


def test_permission_class_exists():
    assert IsClassRepForClassroomOrSubject is not None
