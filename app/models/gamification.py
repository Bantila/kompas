import uuid

from django.db import models


class UserStats(models.Model):
    """XP, серия дней и рекорд серии.

    Количество решённых задач намеренно не дублируем — оно считается из
    task_attempts, иначе два источника правды рано или поздно разойдутся.
    Здесь только то, что из истории попыток не восстановить.
    """

    user = models.OneToOneField(
        "app.User", verbose_name="ученик", on_delete=models.CASCADE, primary_key=True, related_name="+"
    )
    xp = models.IntegerField(verbose_name="опыт", default=0)
    streak_days = models.IntegerField(verbose_name="серия дней", default=0)
    best_streak = models.IntegerField(verbose_name="рекорд серии", default=0)
    last_activity_date = models.DateField(verbose_name="последняя активность", null=True, blank=True)
    updated_at = models.DateTimeField(verbose_name="обновлено", auto_now=True)

    class Meta:
        db_table = "user_stats"
        verbose_name = "статистика ученика"
        verbose_name_plural = "статистика учеников"


class UserAchievement(models.Model):
    """Полученное достижение. Код — ключ из ACHIEVEMENTS."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey("app.User", verbose_name="ученик", on_delete=models.CASCADE, related_name="+")
    code = models.CharField(verbose_name="достижение", max_length=32)
    earned_at = models.DateTimeField(verbose_name="получено", auto_now_add=True)

    class Meta:
        db_table = "user_achievements"
        verbose_name = "достижение"
        verbose_name_plural = "достижения"
        constraints = [
            models.UniqueConstraint(fields=["user", "code"], name="uq_user_achievement"),
        ]
