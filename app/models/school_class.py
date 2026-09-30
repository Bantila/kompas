import uuid

from django.db import models


class SchoolClass(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(verbose_name="название", max_length=32)
    teacher = models.ForeignKey("app.User", verbose_name="педагог", on_delete=models.CASCADE, related_name="taught_classes")
    # код из 6 символов без похожих друг на друга букв/цифр — ученики вводят вручную
    join_code = models.CharField(verbose_name="код для учеников", max_length=8, unique=True)
    created_at = models.DateTimeField(verbose_name="создан", auto_now_add=True)

    class Meta:
        db_table = "school_classes"
        verbose_name = "класс"
        verbose_name_plural = "классы"

    def __str__(self) -> str:
        return f"{self.name} ({self.join_code})"
