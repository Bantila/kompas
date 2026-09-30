"""Классы: педагог создаёт и смотрит свои, ученик вступает по коду.

Все ручки работают от токена: кто ты — берётся из JWT, а не из тела запроса.
Иначе достаточно было подставить чужой id, чтобы управлять чужим классом.
"""

from __future__ import annotations

import logging
import secrets
import string
import uuid

from django.db.models import Count, Q
from django.http import HttpRequest
from ninja import Router
from ninja.errors import HttpError

from app.models import (
    ClassAssignment,
    SchoolClass,
    TaskAttempt,
    TestResult,
    User,
    UserRole,
    UserStats,
)
from app.routers.auth import jwt_auth
from app.schemas.school_class import (
    AssignmentOut,
    ClassOut,
    CreateAssignmentRequest,
    CreateClassRequest,
    JoinClassRequest,
    JoinClassResponse,
    LeaderboardResponse,
    LeaderboardRow,
)
from app.services.gamification import level_of
from app.services.integrity import summary_line as integrity_note

logger = logging.getLogger(__name__)

router = Router(tags=["classes"], auth=jwt_auth)

# без похожих друг на друга символов (0/O, 1/I/L) — код часто диктуют вслух в классе
JOIN_CODE_ALPHABET = "".join(c for c in string.ascii_uppercase + string.digits if c not in "01OIL")
JOIN_CODE_LENGTH = 6


def _require_teacher(user: User) -> User:
    if user.role != UserRole.teacher:
        raise HttpError(403, "Доступно только педагогу")
    return user


async def _students_count(class_id) -> int:
    return await User.objects.filter(class_ref_id=class_id).acount()


def _class_out(school_class: SchoolClass, students_count: int) -> ClassOut:
    return ClassOut(
        id=school_class.id,
        name=school_class.name,
        join_code=school_class.join_code,
        students_count=students_count,
        created_at=school_class.created_at,
    )


async def _generate_unique_join_code() -> str:
    for _ in range(20):
        code = "".join(secrets.choice(JOIN_CODE_ALPHABET) for _ in range(JOIN_CODE_LENGTH))
        if not await SchoolClass.objects.filter(join_code=code).aexists():
            return code
    raise RuntimeError("Не удалось сгенерировать уникальный код класса")


@router.post("/teacher/classes", response=ClassOut)
async def create_class(request: HttpRequest, payload: CreateClassRequest) -> ClassOut:
    """Создать класс и получить код для учеников.

    Идемпотентно по имени: повторное создание класса с тем же названием
    возвращает существующий, а не плодит дубликаты (двойной клик по кнопке).
    """
    teacher = _require_teacher(request.auth)
    name = payload.name.strip()

    existing = await SchoolClass.objects.filter(teacher=teacher, name__iexact=name).afirst()
    if existing is not None:
        return _class_out(existing, await _students_count(existing.id))

    school_class = await SchoolClass.objects.acreate(
        name=name, teacher=teacher, join_code=await _generate_unique_join_code()
    )
    return _class_out(school_class, 0)


@router.get("/teacher/classes", response=list[ClassOut])
async def list_classes(request: HttpRequest) -> list[ClassOut]:
    """Классы этого педагога с количеством присоединившихся учеников."""
    teacher = _require_teacher(request.auth)
    return [
        _class_out(school_class, school_class.students_count)
        async for school_class in SchoolClass.objects.filter(teacher=teacher)
        .annotate(students_count=Count("students"))
        .order_by("-created_at")
    ]


async def _owned_class(teacher: User, class_id) -> SchoolClass:
    school_class = await SchoolClass.objects.filter(id=class_id, teacher=teacher).afirst()
    if school_class is None:
        raise HttpError(404, "Класс не найден среди ваших классов")
    return school_class


@router.get("/teacher/classes/{class_id}/leaderboard", response=LeaderboardResponse)
async def leaderboard(request: HttpRequest, class_id: uuid.UUID) -> LeaderboardResponse:
    """Рейтинг класса по опыту.

    В отличие от обезличенной сводки здесь видны имена: это рабочий список
    своего класса, педагог и так знает, кто у него учится. Доступ — только
    владельцу класса.
    """
    teacher = _require_teacher(request.auth)
    school_class = await _owned_class(teacher, class_id)

    students = [
        student
        async for student in User.objects.filter(class_ref_id=class_id, role=UserRole.student)
    ]
    ids = [student.id for student in students]

    # Три отдельных агрегата, а не один запрос с двумя JOIN: попытки,
    # перемноженные на прохождения, удваивали число решённых задач у всех,
    # кто прошёл тест дважды.
    stats = {s.user_id: s async for s in UserStats.objects.filter(user_id__in=ids)}
    attempts = {
        row["user_id"]: row
        async for row in TaskAttempt.objects.filter(user_id__in=ids)
        .values("user_id")
        .annotate(solved=Count("id"), correct=Count("id", filter=Q(is_correct=True)))
    }
    tests_done = {
        row["user_id"]
        async for row in TestResult.objects.filter(user_id__in=ids).values("user_id").distinct()
    }

    # Пометка о доверии берётся из последнего прохождения: если ученик
    # прокликал тест, педагог должен видеть это рядом с его цифрами, иначе
    # решения принимаются по числам, за которыми ничего нет.
    заметки: dict[uuid.UUID, str] = {}
    последние: set[uuid.UUID] = set()
    async for user_id, integrity in (
        TestResult.objects.filter(user_id__in=ids)
        .order_by("user_id", "-completed_at")
        .values_list("user_id", "integrity")
    ):
        if user_id in последние:
            continue
        последние.add(user_id)
        note = integrity_note(integrity)
        if note:
            заметки[user_id] = note

    def xp_of(student: User) -> int:
        return stats[student.id].xp if student.id in stats else 0

    students.sort(key=lambda s: (-xp_of(s), s.full_name is None, s.full_name or ""))

    rows = []
    for index, student in enumerate(students, start=1):
        xp = xp_of(student)
        solved = attempts.get(student.id, {}).get("solved", 0)
        correct = attempts.get(student.id, {}).get("correct", 0)
        rows.append(
            LeaderboardRow(
                rank=index,
                student_id=student.id,
                full_name=student.full_name or "Без имени",
                level=level_of(xp),
                xp=xp,
                streak_days=stats[student.id].streak_days if student.id in stats else 0,
                solved=solved,
                correct=correct,
                accuracy=round(correct / solved, 3) if solved else 0.0,
                test_done=student.id in tests_done,
                integrity_note=заметки.get(student.id),
            )
        )

    return LeaderboardResponse(class_id=school_class.id, class_name=school_class.name, rows=rows)


def _assignment_fields(assignment: ClassAssignment) -> dict:
    return {
        "id": assignment.id,
        "title": assignment.title,
        "subjects": list(assignment.subjects or []),
        "size": assignment.size,
        "difficulty": assignment.difficulty,
        "due_date": assignment.due_date,
        "created_at": assignment.created_at,
    }


@router.post("/teacher/classes/{class_id}/assignments", response=AssignmentOut)
async def create_assignment(
    request: HttpRequest, class_id: uuid.UUID, payload: CreateAssignmentRequest
) -> AssignmentOut:
    """Выдать классу задание — набор предметов и размер пака."""
    teacher = _require_teacher(request.auth)
    await _owned_class(teacher, class_id)

    assignment = await ClassAssignment.objects.acreate(
        school_class_id=class_id,
        teacher=teacher,
        title=payload.title.strip(),
        subjects=payload.subjects,
        size=payload.size,
        difficulty=payload.difficulty,
        due_date=payload.due_date,
    )
    return AssignmentOut(**_assignment_fields(assignment), completed_by=0, students_total=0)


@router.get("/teacher/classes/{class_id}/assignments", response=list[AssignmentOut])
async def list_assignments(request: HttpRequest, class_id: uuid.UUID) -> list[AssignmentOut]:
    """Задания класса и сколько учеников за них уже брались."""
    teacher = _require_teacher(request.auth)
    await _owned_class(teacher, class_id)

    students_total = await _students_count(class_id)
    result = []
    async for assignment in ClassAssignment.objects.filter(school_class_id=class_id).order_by(
        "-created_at"
    ):
        # «взялся за задание» = решал задачи по его предметам после выдачи
        attempts = TaskAttempt.objects.filter(
            user__class_ref_id=class_id, answered_at__gte=assignment.created_at
        )
        if assignment.subjects:
            attempts = attempts.filter(subject__in=assignment.subjects)
        completed_by = await attempts.values("user_id").distinct().acount()
        result.append(
            AssignmentOut(
                **_assignment_fields(assignment),
                completed_by=completed_by,
                students_total=students_total,
            )
        )
    return result


@router.delete("/teacher/assignments/{assignment_id}")
async def delete_assignment(request: HttpRequest, assignment_id: uuid.UUID) -> dict[str, str]:
    teacher = _require_teacher(request.auth)
    deleted, _ = await ClassAssignment.objects.filter(id=assignment_id, teacher=teacher).adelete()
    if not deleted:
        raise HttpError(404, "Задание не найдено")
    return {"status": "deleted"}


@router.get("/classes/my-assignments", response=list[AssignmentOut])
async def my_assignments(request: HttpRequest) -> list[AssignmentOut]:
    """Задания класса — для ученика."""
    user = request.auth
    if user.class_ref_id is None:
        return []
    return [
        AssignmentOut(**_assignment_fields(a))
        async for a in ClassAssignment.objects.filter(school_class_id=user.class_ref_id).order_by(
            "-created_at"
        )[:20]
    ]


@router.post("/classes/join", response=JoinClassResponse)
async def join_class(request: HttpRequest, payload: JoinClassRequest) -> JoinClassResponse:
    """Ученик вступает в класс по коду, полученному от педагога."""
    user = request.auth
    code = payload.join_code.strip().upper()
    school_class = await SchoolClass.objects.filter(join_code=code).afirst()
    if school_class is None:
        raise HttpError(404, "Код класса не найден — проверьте, что ввели верно")
    if user.role != UserRole.student:
        raise HttpError(409, "В класс вступают ученики, а не педагоги")

    user.class_ref_id = school_class.id
    user.school_class = school_class.name
    await user.asave(update_fields=["class_ref", "school_class"])
    return JoinClassResponse(class_id=school_class.id, class_name=school_class.name)
