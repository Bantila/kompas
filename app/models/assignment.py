import uuid

from django.db import models


class ClassAssignment(models.Model):
    """Задание, выданное классу: набор предметов и размер пака.

    Храним не список конкретных задач, а правило подбора — тогда каждому ученику
    достаются задачи по его слабым местам внутри заданных предметов, а не один
    и тот же список, который можно списать у соседа.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school_class = models.ForeignKey(
        "app.SchoolClass", verbose_name="класс", on_delete=models.CASCADE, db_column="class_id", related_name="+"
    )
    teacher = models.ForeignKey("app.User", verbose_name="педагог", on_delete=models.CASCADE, related_name="+")
    title = models.CharField(verbose_name="название", max_length=120)
    subjects = models.JSONField(verbose_name="предметы", default=list, blank=True)
    size = models.IntegerField(verbose_name="задач в паке", default=5)
    difficulty = models.CharField(verbose_name="сложность", max_length=16, null=True, blank=True)
    due_date = models.DateField(verbose_name="срок", null=True, blank=True)
    created_at = models.DateTimeField(verbose_name="выдано", auto_now_add=True, db_index=True)

    class Meta:
        db_table = "class_assignments"
        verbose_name = "задание классу"
        verbose_name_plural = "задания классам"

    def __str__(self) -> str:
        return self.title
