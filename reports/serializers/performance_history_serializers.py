"""
Production serializers for performance history and academic risk responses.
"""

from __future__ import annotations

from decimal import Decimal
from rest_framework import serializers


class PerformanceHistoryPointSerializer(serializers.Serializer):
    term_id = serializers.IntegerField(min_value=1)
    gpa = serializers.DecimalField(
        max_digits=5,
        decimal_places=3,
        allow_null=True,
        required=False,
    )
    aggregate = serializers.DecimalField(
        max_digits=6,
        decimal_places=2,
        allow_null=True,
        required=False,
    )
    class_position = serializers.IntegerField(
        min_value=1,
        allow_null=True,
        required=False,
    )
    class_average = serializers.DecimalField(
        max_digits=6,
        decimal_places=2,
        allow_null=True,
        required=False,
    )
    school_average = serializers.DecimalField(
        max_digits=6,
        decimal_places=2,
        allow_null=True,
        required=False,
    )

    def validate(self, attrs):
        gpa = attrs.get("gpa")
        if gpa is not None:
            if gpa < Decimal("0.000"):
                raise serializers.ValidationError(
                    {"gpa": "GPA cannot be negative."}
                )

        aggregate = attrs.get("aggregate")
        if aggregate is not None and aggregate < Decimal("0.00"):
            raise serializers.ValidationError(
                {"aggregate": "Aggregate cannot be negative."}
            )

        class_avg = attrs.get("class_average")
        school_avg = attrs.get("school_average")

        if class_avg is not None and class_avg < Decimal("0.00"):
            raise serializers.ValidationError(
                {"class_average": "Class average cannot be negative."}
            )

        if school_avg is not None and school_avg < Decimal("0.00"):
            raise serializers.ValidationError(
                {"school_average": "School average cannot be negative."}
            )

        return attrs


class AcademicRiskResponseSerializer(serializers.Serializer):
    at_risk = serializers.BooleanField()
    factors = serializers.ListField(
        child=serializers.CharField(
            trim_whitespace=True,
            max_length=255,
        ),
        allow_empty=True,
    )

    def validate_factors(self, value):
        cleaned = []
        seen = set()

        for factor in value:
            text = factor.strip()
            if not text:
                raise serializers.ValidationError(
                    "Risk factors cannot be blank."
                )
            if text not in seen:
                cleaned.append(text)
                seen.add(text)

        return cleaned