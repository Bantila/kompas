"""Django admin по адресу /admin — тема Unfold, оформление в app/admin_ui.py.

Вход — через пользователей Django (python manage.py createsuperuser), а не
через аккаунты сервиса: у учеников паролей нет вовсе, а педагогу не нужен
доступ к данным чужих классов.
"""

from __future__ import annotations

from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group
from django.contrib.auth.models import User as StaffUser
from django.db.models import Count
from django.utils import timezone
from django.utils.html import format_html, format_html_join
from unfold.admin import ModelAdmin
from unfold.decorators import display
from unfold.forms import AdminPasswordChangeForm, UserChangeForm, UserCreationForm

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
from app.services.ai_recommender import FALLBACK_MODEL_NAME
from app.services.error_classifier import ERROR_LABELS
from app.services.gamification import ACHIEVEMENTS, level_of
from app.services.test_scoring import load_questions

ТИПЫ_ГОЛЛАНДА = {
    "realistic": "Практик",
    "investigative": "Исследователь",
    "artistic": "Творец",
    "social": "Помощник",
    "enterprising": "Лидер",
    "conventional": "Организатор",
}
ДОВЕРИЕ = {
    "high": ("Можно доверять", "success"),
    "medium": ("Есть сомнения", "warning"),
    "low": ("Похоже на прокликивание", "danger"),
    "unknown": ("Не проверялось", "info"),
}


def _initials(name: str | None) -> str:
    части = (name or "?").replace(".", " ").split()
    return "".join(часть[0] for часть in части[:2]).upper()


def _bar(value: float, maximum: float) -> str:
    """Полоска для балла — видно, где сильные стороны, без чтения чисел."""
    ширина = max(0, min(100, round(value * 100 / maximum)))
    return format_html(
        '<span style="display:inline-block;width:140px;height:6px;border-radius:99px;'
        'background:var(--color-base-200);vertical-align:middle;margin-right:8px">'
        '<span style="display:block;width:{}%;height:100%;border-radius:99px;'
        'background:var(--color-primary-500)"></span></span>{}',
        ширина,
        value,
    )


# --- доступ к самой админке --------------------------------------------------

admin.site.unregister(StaffUser)
admin.site.unregister(Group)


@admin.register(StaffUser)
class StaffAdmin(BaseUserAdmin, ModelAdmin):
    form = UserChangeForm
    add_form = UserCreationForm
    change_password_form = AdminPasswordChangeForm


@admin.register(Group)
class StaffGroupAdmin(BaseGroupAdmin, ModelAdmin):
    pass


# --- ученики и классы --------------------------------------------------------


@admin.register(User)
class UserAdmin(ModelAdmin):
    list_display = ("person", "role_badge", "school_class", "is_active", "created_at")
    list_filter = ("role", "is_active", "school_class")
    list_filter_submit = True
    search_fields = ("full_name", "email", "max_user_id")
    # хэш пароля не показываем и не даём перезаписать руками
    exclude = ("hashed_password",)
    readonly_fields = ("id", "created_at")
    raw_id_fields = ("class_ref",)

    @display(description="Человек", header=True, ordering="full_name")
    def person(self, obj: User):
        return [obj.full_name or "Без имени", obj.email or obj.max_user_id, _initials(obj.full_name)]

    @display(description="Роль", ordering="role", label={"teacher": "info", "student": "success"})
    def role_badge(self, obj: User):
        return obj.role, obj.get_role_display()


@admin.register(SchoolClass)
class SchoolClassAdmin(ModelAdmin):
    list_display = ("class_card", "join_code_badge", "students", "teacher", "created_at")
    search_fields = ("name", "join_code")
    raw_id_fields = ("teacher",)
    list_select_related = ("teacher",)

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(students_count=Count("students"))

    @display(description="Класс", header=True, ordering="name")
    def class_card(self, obj: SchoolClass):
        return [obj.name, f"педагог: {obj.teacher}", obj.name[:2]]

    @display(description="Код для учеников", label=True)
    def join_code_badge(self, obj: SchoolClass):
        return obj.join_code

    @display(description="Учеников", ordering="students_count")
    def students(self, obj: SchoolClass):
        return obj.students_count


@admin.register(ClassAssignment)
class ClassAssignmentAdmin(ModelAdmin):
    list_display = ("title", "school_class", "subjects_list", "size", "difficulty", "due_date")
    list_filter = ("difficulty",)
    raw_id_fields = ("school_class", "teacher")
    list_select_related = ("school_class",)

    @display(description="Предметы")
    def subjects_list(self, obj: ClassAssignment):
        названия = load_questions()["subject_titles"]
        return ", ".join(названия.get(код, код) for код in obj.subjects or []) or "все"


@admin.register(TeacherInvite)
class TeacherInviteAdmin(ModelAdmin):
    list_display = ("code", "note", "status", "expires_at", "used_at")
    readonly_fields = ("code", "created_by", "used_by", "used_at", "created_at")
    search_fields = ("code", "note")

    @display(
        description="Статус",
        label={"активен": "success", "использован": "info", "истёк": "danger"},
    )
    def status(self, obj: TeacherInvite):
        if obj.used_at:
            return "использован"
        return "истёк" if obj.expires_at <= timezone.now() else "активен"


# --- тест и профессии --------------------------------------------------------


@admin.register(TestResult)
class TestResultAdmin(ModelAdmin):
    list_display = ("student", "trust_badge", "top_profession", "source_badge", "completed_at")
    list_select_related = ("user", "recommendation")
    search_fields = ("user__full_name", "user__max_user_id")
    date_hierarchy = "completed_at"
    readonly_fields = (
        "user", "completed_at", "professions_view", "interests_view", "subjects_view",
        "integrity_view", "raw_answers", "computed_scores", "integrity",
    )
    fieldsets = (
        (None, {"fields": ("user", "completed_at")}),
        ("Подобранные профессии", {"fields": ("professions_view",)}),
        ("Склад по Голланду и предметы", {"fields": ("interests_view", "subjects_view")}),
        ("Можно ли верить ответам", {"fields": ("integrity_view",)}),
        ("Сырые данные", {"fields": ("raw_answers", "computed_scores", "integrity"), "classes": ["collapse"]}),
    )

    # прохождение появляется только из теста: руками его не заводят и не правят,
    # удалить можно — например, по просьбе родителя
    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    @display(description="Ученик", header=True, ordering="user__full_name")
    def student(self, obj: TestResult):
        return [str(obj.user), obj.user.school_class or "без класса", _initials(obj.user.full_name)]

    @display(description="Доверие", label={value[0]: value[1] for value in ДОВЕРИЕ.values()})
    def trust_badge(self, obj: TestResult):
        return ДОВЕРИЕ.get((obj.integrity or {}).get("trust", "unknown"), ДОВЕРИЕ["unknown"])[0]

    def _recommendation(self, obj: TestResult) -> Recommendation | None:
        return getattr(obj, "recommendation", None)

    @display(description="Первая профессия")
    def top_profession(self, obj: TestResult):
        рекомендация = self._recommendation(obj)
        if not рекомендация or not рекомендация.professions:
            return "—"
        return рекомендация.professions[0].get("name", "—")

    @display(description="Подобрал", label={"GigaChat / модель": "success", "Запасной алгоритм": "warning"})
    def source_badge(self, obj: TestResult):
        рекомендация = self._recommendation(obj)
        if not рекомендация:
            return "—"
        return "Запасной алгоритм" if рекомендация.model_used == FALLBACK_MODEL_NAME else "GigaChat / модель"

    @display(description="Профессии")
    def professions_view(self, obj: TestResult):
        рекомендация = self._recommendation(obj)
        if not рекомендация:
            return "Рекомендаций нет"
        return format_html(
            '<ol style="display:flex;flex-direction:column;gap:12px;margin:0;padding-left:18px">{}</ol>',
            format_html_join(
                "",
                '<li><strong>{}</strong> <span style="color:var(--color-base-500)">· {}</span>'
                '<div style="margin-top:2px">{}</div>'
                '<div style="margin-top:2px;color:var(--color-base-500)">Подтянуть: {}</div></li>',
                (
                    (
                        п.get("name", "—"),
                        п.get("category", "—"),
                        п.get("reasoning", ""),
                        ", ".join(п.get("subjects_to_improve") or []) or "—",
                    )
                    for п in рекомендация.professions or []
                ),
            ),
        )

    @display(description="Интересы (1–5)")
    def interests_view(self, obj: TestResult):
        интересы = (obj.computed_scores or {}).get("interests") or {}
        return format_html_join(
            "",
            '<div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">'
            '<span style="width:160px">{}</span>{}</div>',
            (
                (ТИПЫ_ГОЛЛАНДА.get(тип, тип), _bar(значение, 5))
                for тип, значение in sorted(интересы.items(), key=lambda kv: -kv[1])
            ),
        ) or "—"

    @display(description="Знания по предметам (0–5)")
    def subjects_view(self, obj: TestResult):
        названия = load_questions()["subject_titles"]
        предметы = (obj.computed_scores or {}).get("subjects") or {}
        return format_html_join(
            "",
            '<div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">'
            '<span style="width:160px">{}</span>{}</div>',
            (
                (названия.get(код, код), _bar(данные.get("knowledge_score") or 0, 5))
                for код, данные in sorted(
                    предметы.items(), key=lambda kv: -(kv[1].get("knowledge_score") or 0)
                )
                if isinstance(данные, dict)
            ),
        ) or "—"

    @display(description="Проверка ответов")
    def integrity_view(self, obj: TestResult):
        проверка = obj.integrity or {}
        вывод, _ = ДОВЕРИЕ.get(проверка.get("trust", "unknown"), ДОВЕРИЕ["unknown"])
        признаки = проверка.get("flags") or []
        if not признаки:
            return f"{вывод}: подозрительных признаков нет"
        return format_html(
            "<strong>{}</strong><ul style='margin:6px 0 0;padding-left:18px'>{}</ul>",
            вывод,
            format_html_join("", "<li>{}</li>", ((признак.get("detail", ""),) for признак in признаки)),
        )


@admin.register(Recommendation)
class RecommendationAdmin(ModelAdmin):
    list_display = ("test_result", "first_profession", "source_badge", "created_at")
    list_filter = ("model_used",)
    list_select_related = ("test_result__user",)
    raw_id_fields = ("test_result",)

    @display(description="Первая профессия")
    def first_profession(self, obj: Recommendation):
        return (obj.professions or [{}])[0].get("name", "—")

    @display(description="Подобрал", label={"модель": "success", "запасной алгоритм": "warning"})
    def source_badge(self, obj: Recommendation):
        return "запасной алгоритм" if obj.model_used == FALLBACK_MODEL_NAME else "модель"


# --- тренажёр ----------------------------------------------------------------


@admin.register(TaskAttempt)
class TaskAttemptAdmin(ModelAdmin):
    list_display = ("user", "task_id", "subject_title", "verdict", "error_label", "answered_at")
    list_filter = ("subject", "is_correct", "error_type")
    list_filter_submit = True
    list_select_related = ("user",)
    raw_id_fields = ("user",)
    date_hierarchy = "answered_at"

    @display(description="Предмет", ordering="subject")
    def subject_title(self, obj: TaskAttempt):
        return load_questions()["subject_titles"].get(obj.subject, obj.subject)

    @display(description="Ответ", ordering="is_correct", label={"верно": "success", "ошибка": "danger"})
    def verdict(self, obj: TaskAttempt):
        return "верно" if obj.is_correct else "ошибка"

    @display(description="Тип ошибки", ordering="error_type")
    def error_label(self, obj: TaskAttempt):
        return "—" if obj.is_correct else ERROR_LABELS.get(obj.error_type, obj.error_type)


@admin.register(UserStats)
class UserStatsAdmin(ModelAdmin):
    list_display = ("user", "level", "xp", "streak_days", "best_streak", "last_activity_date")
    list_select_related = ("user",)
    ordering = ("-xp",)
    raw_id_fields = ("user",)

    @display(description="Уровень", ordering="xp", label=True)
    def level(self, obj: UserStats):
        return f"{level_of(obj.xp)} ур."


@admin.register(UserAchievement)
class UserAchievementAdmin(ModelAdmin):
    list_display = ("user", "achievement", "earned_at")
    list_filter = ("code",)
    list_select_related = ("user",)
    raw_id_fields = ("user",)

    @display(description="Достижение", ordering="code")
    def achievement(self, obj: UserAchievement):
        мета = ACHIEVEMENTS.get(obj.code, {})
        return f"{мета.get('icon', '')} {мета.get('title', obj.code)}".strip()


# --- бот и данные ------------------------------------------------------------


@admin.register(BotAccount)
class BotAccountAdmin(ModelAdmin):
    list_display = ("__str__", "platform_badge", "user", "link_code", "created_at")
    list_filter = ("platform",)
    list_select_related = ("user",)
    raw_id_fields = ("user",)

    @display(description="Платформа", ordering="platform", label={"max": "info", "telegram": "success"})
    def platform_badge(self, obj: BotAccount):
        return obj.platform


@admin.register(Consent)
class ConsentAdmin(ModelAdmin):
    """Журнал согласий — юридическая запись: руками не создаётся, не правится и не удаляется."""

    list_display = ("user", "state", "document_version", "given_by", "age_at_consent", "granted_at", "revoked_at")
    list_filter = ("document_version", "granted_by")
    list_select_related = ("user",)

    @display(description="Состояние", label={"действует": "success", "отозвано": "danger"})
    def state(self, obj: Consent):
        return "отозвано" if obj.revoked_at else "действует"

    @display(description="Кем дано", ordering="granted_by")
    def given_by(self, obj: Consent):
        return {"self": "сам ученик", "parent": "родитель"}.get(obj.granted_by, obj.granted_by)

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False
