"""Django admin по адресу /admin.

Вход — через пользователей Django (python manage.py createsuperuser), а не
через аккаунты сервиса: у учеников паролей нет вовсе, а педагогу не нужен
доступ к данным чужих классов.
"""

from __future__ import annotations

from django.contrib import admin

from app.models import (
    BotAccount,
    ClassAssignment,
    Consent,
    Recommendation,
    SchoolClass,
    TaskAttempt,
    TeacherInvite,
    TestResult,
    User,
    UserAchievement,
    UserStats,
)


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("__str__", "role", "school_class", "email", "is_active", "created_at")
    list_filter = ("role", "is_active", "school_class")
    search_fields = ("full_name", "email", "max_user_id")
    # хэш пароля не показываем и не даём перезаписать руками
    exclude = ("hashed_password",)
    readonly_fields = ("id", "created_at")
    raw_id_fields = ("class_ref",)


@admin.register(SchoolClass)
class SchoolClassAdmin(admin.ModelAdmin):
    list_display = ("name", "join_code", "teacher", "created_at")
    search_fields = ("name", "join_code")
    raw_id_fields = ("teacher",)


class RecommendationInline(admin.StackedInline):
    model = Recommendation
    can_delete = False
    readonly_fields = ("model_used", "professions", "ai_response", "created_at")


@admin.register(TestResult)
class TestResultAdmin(admin.ModelAdmin):
    list_display = ("user", "completed_at")
    list_select_related = ("user",)
    date_hierarchy = "completed_at"
    readonly_fields = ("user", "raw_answers", "computed_scores", "integrity", "completed_at")
    inlines = (RecommendationInline,)


@admin.register(Recommendation)
class RecommendationAdmin(admin.ModelAdmin):
    list_display = ("test_result", "model_used", "created_at")
    list_filter = ("model_used",)
    raw_id_fields = ("test_result",)


@admin.register(TaskAttempt)
class TaskAttemptAdmin(admin.ModelAdmin):
    list_display = ("user", "task_id", "subject", "is_correct", "error_type", "answered_at")
    list_filter = ("subject", "is_correct", "error_type")
    list_select_related = ("user",)
    raw_id_fields = ("user",)


@admin.register(Consent)
class ConsentAdmin(admin.ModelAdmin):
    """Журнал согласий — юридическая запись: руками не создаётся, не правится и не удаляется."""

    list_display = ("user", "document_version", "granted_by", "age_at_consent", "granted_at", "revoked_at")
    list_filter = ("document_version", "granted_by")
    list_select_related = ("user",)

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


@admin.register(TeacherInvite)
class TeacherInviteAdmin(admin.ModelAdmin):
    list_display = ("code", "note", "expires_at", "used_at")
    readonly_fields = ("code", "created_by", "used_by", "used_at", "created_at")


@admin.register(ClassAssignment)
class ClassAssignmentAdmin(admin.ModelAdmin):
    list_display = ("title", "school_class", "size", "difficulty", "due_date", "created_at")
    raw_id_fields = ("school_class", "teacher")


@admin.register(BotAccount)
class BotAccountAdmin(admin.ModelAdmin):
    list_display = ("__str__", "user", "link_code", "created_at")
    list_filter = ("platform",)
    raw_id_fields = ("user",)


@admin.register(UserStats)
class UserStatsAdmin(admin.ModelAdmin):
    list_display = ("user", "xp", "streak_days", "best_streak", "last_activity_date")
    raw_id_fields = ("user",)


@admin.register(UserAchievement)
class UserAchievementAdmin(admin.ModelAdmin):
    list_display = ("user", "code", "earned_at")
    list_filter = ("code",)
    raw_id_fields = ("user",)
