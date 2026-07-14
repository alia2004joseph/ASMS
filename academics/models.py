from django.db import models


class Classroom(models.Model):
    school = models.ForeignKey(
        "schools.School",
        on_delete=models.CASCADE,
        related_name="classrooms",
    )

    name = models.CharField(max_length=100)
    code = models.CharField(max_length=30)
    level = models.CharField(
        max_length=50,
        blank=True,
        help_text="For example: S1, S4, S5 or Year 1.",
    )

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["school", "name"]

        constraints = [
            models.UniqueConstraint(
                fields=["school", "code"],
                name="unique_classroom_code_per_school",
            )
        ]

    def __str__(self):
        return f"{self.name} — {self.school.name}"