import uuid

from django.db import models


class UserRole(models.TextChoices):
    student = "student", "ученик"
    teacher = "teacher", "педагог"


class User(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    max_user_id = models.CharField(verbose_name="id в мессенджере", max_length=128, unique=True)
    role = models.CharField(verbose_name="роль", max_length=16, choices=UserRole.choices, default=UserRole.student)
    full_name = models.CharField(verbose_name="имя", max_length=255, null=True, blank=True)
    # email/пароль есть только у зарегистрированных: гость проходит тест анонимно,
    # у него max_user_id есть, а учётной записи — нет
    email = models.CharField(verbose_name="почта", max_length=255, unique=True, null=True, blank=True)
    hashed_password = models.CharField(max_length=255, null=True, blank=True)
    grade = models.IntegerField(verbose_name="класс (номер)", null=True, blank=True)
    is_active = models.BooleanField(verbose_name="активен", default=True)
    # денормализованное имя класса (например "7Б") — заполняется при join по коду,
    # источник истины — class_ref/SchoolClass, это поле только для быстрых выборок
    school_class = models.CharField(verbose_name="класс", max_length=16, null=True, blank=True, db_index=True)
    # класс, в который вступил этот пользователь как ученик
    class_ref = models.ForeignKey(
        "app.SchoolClass", verbose_name="класс (запись)", on_delete=models.SET_NULL, null=True, blank=True,
        db_column="class_id", related_name="students",
    )
    created_at = models.DateTimeField(verbose_name="создан", auto_now_add=True)

    class Meta:
        db_table = "users"
        verbose_name = "аккаунт сервиса"
        verbose_name_plural = "ученики и педагоги"

    def __str__(self) -> str:
        return self.full_name or self.email or self.max_user_id
