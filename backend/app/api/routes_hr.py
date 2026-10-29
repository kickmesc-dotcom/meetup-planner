"""REST API HR-ядра для сотрудника (мини-апп и бот).

Все ручки требуют валидный Telegram `initData` (`CurrentUser`) и работают от
имени HR-профиля (`EmployeeDep`). Никаких «передай свой id» — идентичность и
права берутся из подписанных данных и БД.

Ответы персонализированы, поэтому клиент должен слать их без кеша
(`Cache-Control: private, no-store` ставит фронт; на API это не влияет).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

import structlog
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, EmployeeDep, SessionDep
from app.services import translate as translate_service
from app.db.hr_models import (
    EXPERIENCES,
    ONBOARDING_DONE,
    ONBOARDING_EXPERIENCE,
    ONBOARDING_TRAINING,
    TASK_DONE,
    TEMPLATE_KINDS,
    TEMPLATE_SHIFT,
    ChecklistItem,
    Department,
    Employee,
    FeedbackQuestion,
    Task,
    TaskAssignment,
    TaskPhoto,
    UsefulLink,
)
from app.db.models import User
from app.schemas.hr_achievements import AchievementsOut
from app.schemas.hr_achievements import to_out as _achievements_out
from app.schemas.hr_kpi import MyKpiOut, to_my_out
from app.services import (
    hr_access,
    hr_achievements,
    hr_checklists,
    hr_departments,
    hr_digest,
    hr_feed,
    hr_feedback,
    hr_kpi,
    hr_kudos,
    hr_links,
    hr_media,
    hr_notify,
    hr_people,
    hr_profile,
    hr_tasks,
    hr_training,
    hr_training_plan,
    org_setup,
    orgs,
    weekdays,
)

log = structlog.get_logger()

router = APIRouter(tags=["hr"])


# --------------------------------------------------------------------------
# Схемы
# --------------------------------------------------------------------------


class EmployeeOut(BaseModel):
    id: int
    user_id: int
    display_name: str
    # Пусто у тех, кто зашёл по почте: у аккаунта без Telegram нет ID, и это
    # нормально — раньше схема требовала int и роняла `/me/employee` в 500.
    telegram_id: int | None = None
    department_id: int | None
    department_name: str | None
    position: str | None
    # Плашка должность/звание — её показывают бот и мини-апп рядом с именем.
    badge: str | None = None
    badge_emoji: str | None = None
    role: str
    experience: str | None
    onboarding_state: str
    # «Учимся вместе»: продолжать обучение в следующих сменах. Флаг не отменяет
    # обязательные чек-листы и поручения — только обучающее сопровождение.
    learning_mode: bool = False
    is_aup: bool
    is_admin: bool
    # Прописанный доступ в админку (шестёрка/владельцы). Переживает смену
    # собственной роли: снял admin — кабинет всё равно доступен.
    is_staff: bool = False
    is_active: bool
    # Тестовый пул `[BOT]`: клиент показывает пометку и может спрятать его.
    is_demo: bool = False
    # «Профиль открыт»: коллеги видят карточку с активностью. Управляющий и
    # администратор видят её в любом случае.
    profile_public: bool = True
    # Приватность карточки: личные галочки и разрешение руководства их менять.
    show_last_seen: bool = True
    show_last_media: bool = True
    can_toggle_last_seen: bool = True
    can_toggle_last_media: bool = True
    # Профиль обязан быть открытым (решение руководства) — тумблер заперт.
    profile_locked: bool = False
    last_seen_at: datetime | None = None


class OnboardingIn(BaseModel):
    department_id: int | None = None
    experience: Literal["new", "experienced"] | None = None
    # «Я уже запомнил»: закрыть знакомство без прохождения уроков. Рабочие
    # чек-листы и поручения при этом остаются обязательными.
    finish: bool = False
    # Выбор режима на следующие смены: «Повторим вместе» (true) — обучение
    # продолжается в рабочем сценарии, «Я уже запомнил» (false) — обычный
    # рабочий режим. Меняется и отдельно, из профиля.
    learning_mode: bool | None = None


class ProfileActivityOut(BaseModel):
    """Одно действие человека в его карточке (из той же ленты событий)."""

    at: datetime
    kind: str
    text: str
    ref_id: int | None = None


class ProfileMediaOut(BaseModel):
    """Последнее медиа сотрудника: готовый адрес картинки и подпись."""

    id: int
    url: str
    at: datetime
    caption: str
    source: Literal["task", "checklist"]


class ProfileCardOut(BaseModel):
    """Карточка коллеги: кто он и что делал. Цифры — только если видно."""

    employee_id: int
    display_name: str
    department_id: int | None = None
    department_name: str | None
    position: str | None
    badge: str | None = None
    badge_emoji: str | None = None
    role: str
    role_label: str
    is_demo: bool = False
    is_self: bool = False
    can_manage: bool = False
    # Профиль открыт для коллег (человек сам решает в своём профиле).
    profile_open: bool
    # Смотрящему доступна активность и цифры.
    can_view: bool
    # Приватность: что показывать и что разрешено менять самому человеку.
    show_last_seen: bool = True
    show_last_media: bool = True
    can_toggle_last_seen: bool = True
    can_toggle_last_media: bool = True
    last_seen_at: datetime | None = None
    last_media: ProfileMediaOut | None = None
    xp: int = 0
    rank_title: str = ""
    rank_emoji: str = ""
    week_xp: int = 0
    week_place: int | None = None
    week_total: int = 0
    checklist_items: int = 0
    tasks_done: int = 0
    shifts_done: int = 0
    activity: list[ProfileActivityOut] = []


class ProfileVisibilityIn(BaseModel):
    is_public: bool


class ProfilePrivacyIn(BaseModel):
    """Личные тумблеры карточки. `None` — не трогать этот пункт."""

    show_last_seen: bool | None = None
    show_last_media: bool | None = None


class DepartmentPersonOut(BaseModel):
    employee_id: int
    display_name: str
    badge: str | None = None
    badge_emoji: str | None = None
    position: str | None = None
    role: str
    is_demo: bool = False
    is_self: bool = False
    shift_status: str | None = None
    checklist_done: int = 0
    checklist_total: int = 0
    tasks_open: int = 0
    tasks_overdue: int = 0
    last_seen_at: datetime | None = None
    profile_public: bool = True


class DepartmentOverviewOut(BaseModel):
    department_id: int
    department_name: str
    department_emoji: str | None = None
    can_manage: bool = False
    show_presence: bool = False
    on_shift: int = 0
    overdue: int = 0
    people: list[DepartmentPersonOut] = []


class OrgSetupOut(BaseModel):
    """Настройка организации: ответы мастера и вытекающие из них правила."""

    done: bool = False
    industry: str = "restaurant"
    headcount: str = "10_30"
    departments: list[str] = []
    sections: list[str] = []
    profile_visibility: str = "colleagues"
    cross_department_watch: bool = False
    allow_hide_last_seen: bool = True
    allow_hide_media: bool = True
    # Языковой пакет (узбекский), включён по умолчанию. Поле отдаётся всем:
    # от него зависит, есть ли в переключателе третий язык.
    uz_pack: bool = True
    # Подсказки для шага «подразделения» — под выбранную отрасль.
    presets: list[dict[str, str]] = []
    # Может ли смотрящий менять настройку (мастер открыт только им).
    can_edit: bool = False
    # Языковой пакет — решение владельца (будущая платная опция тарифа),
    # поэтому у руководителя смены тумблер виден, но неактивен.
    can_manage_packs: bool = False


class OrgSetupIn(BaseModel):
    """Частичный ответ мастера: присылается по шагам, а не целиком."""

    industry: str | None = None
    headcount: str | None = None
    departments: list[str] | None = None
    create_departments: bool = False
    sections: list[str] | None = None
    profile_visibility: Literal["colleagues", "managers", "all_open"] | None = None
    cross_department_watch: bool | None = None
    allow_hide_last_seen: bool | None = None
    allow_hide_media: bool | None = None
    uz_pack: bool | None = None
    done: bool | None = None


class DepartmentOut(BaseModel):
    id: int
    name: str
    slug: str
    emoji: str | None
    sort_order: int


class PhotoOut(BaseModel):
    """Фотоотчёт в виде, пригодном для `<img>`: готовая ссылка и размеры."""

    id: int
    url: str
    width: int | None = None
    height: int | None = None
    created_at: datetime | None = None


class ChecklistItemOut(BaseModel):
    id: int
    title: str
    description: str | None
    requires_photo: bool
    is_mandatory: bool
    done: bool
    done_at: datetime | None
    photo_file_id: str | None
    # Готовая ссылка на фото пункта (из приложения или кеша Telegram).
    photo_url: str | None = None
    note: str | None
    # Расписание по дням недели: «по четвергам» и т. п. Пусто — каждый день.
    weekdays: str | None = None
    schedule_label: str = ""
    # Пункт виден всегда, но сегодня не действует (ждёт своего дня недели).
    active: bool = True


class ChecklistOut(BaseModel):
    run_id: int | None
    template_id: int | None
    template_title: str | None
    kind: str
    shift_date: date
    status: str
    done: int
    total: int
    progress_text: str
    items: list[ChecklistItemOut]
    # Зал смены (для открытия): его выбирает сотрудник до первого пункта.
    hall_id: int | None = None
    hall_name: str | None = None
    # True — сначала нужно выбрать зал, пунктов пока нет.
    needs_hall: bool = False


class HallOut(BaseModel):
    id: int
    name: str
    slug: str
    sort_order: int


class ChooseHallIn(BaseModel):
    hall_id: int


class CompleteIn(BaseModel):
    item_id: int
    # Фото из чата (старый путь) либо загруженное в приложении.
    photo_file_id: str | None = None
    media_id: int | None = None
    note: str | None = None


class TaskOut(BaseModel):
    id: int
    title: str
    description: str | None
    expected_result: str | None
    scope: str
    department_id: int | None
    assignee_employee_id: int | None
    due_at: datetime | None
    priority: str
    requires_photo: bool
    comment: str | None
    status: str
    created_by_employee_id: int | None
    created_at: datetime
    done_at: datetime | None
    is_overdue: bool
    # Групповые поручения: режим, смена и ЛИЧНЫЙ статус сотрудника. Общий
    # `status` — агрегат по всем исполнителям, поэтому в «каждый сам» он не
    # говорит, закрыл ли конкретный человек свою часть.
    mode: str = "one_of"
    shift_date: date | None = None
    # Поручение с проверкой: отметка «выполнено» отправляет работу
    # руководителю (`on_review`), а не закрывает её.
    requires_review: bool = False
    my_status: str | None = None
    progress_done: int = 0
    progress_total: int = 0
    my_part: str | None = None
    # Снимки к поручению: приложение показывает их превью прямо в карточке.
    photos: list[PhotoOut] = []
    # Расписание по дням недели: пусто — каждый день.
    weekdays: str | None = None
    schedule_label: str = ""
    active_today: bool = True


class TaskIssueIn(BaseModel):
    reason_code: str | None = Field(None, max_length=32)
    comment: str | None = None
    eta_at: datetime | None = None


class TaskPhotoIn(BaseModel):
    """Фотоотчёт: id загруженного снимка (приложение) или TG file_id (бот)."""

    file_id: str | None = None
    media_id: int | None = None


class LinkOut(BaseModel):
    id: int
    title: str
    url: str
    emoji: str | None
    department_id: int | None


class FeedbackQuestionOut(BaseModel):
    id: int
    code: str
    text: str
    kind: str
    options: list[str]


class FeedbackAnswerIn(BaseModel):
    question_id: int
    value_scale: int | None = None
    value_choice: str | None = None
    value_text: str | None = None


class FeedbackIn(BaseModel):
    shift_date: date | None = None
    answers: list[FeedbackAnswerIn]


# --------------------------------------------------------------------------
# Хелперы сериализации
# --------------------------------------------------------------------------


async def _department_name(
    session: AsyncSession, department_id: int | None
) -> str | None:
    if department_id is None:
        return None
    dept = await session.get(Department, department_id)
    return dept.name if dept else None


async def _employee_out(
    session: AsyncSession, employee: Employee, user: User
) -> EmployeeOut:
    # В режиме проверки `employee` — теневой профиль со своим пользователем,
    # а `user` остаётся реальным админом. Имя и telegram_id берём у владельца
    # профиля, иначе сотрудник видит в «Профиле» имя проверяющего.
    owner = user
    if int(employee.user_id) != int(user.id):
        owner = await session.get(User, employee.user_id) or user
    preferences = await org_setup.load(session)
    return EmployeeOut(
        id=employee.id,
        user_id=employee.user_id,
        display_name=owner.display_name,
        telegram_id=owner.telegram_id,
        badge=employee.badge,
        badge_emoji=employee.badge_emoji,
        is_demo=employee.is_demo,
        department_id=employee.department_id,
        department_name=await _department_name(session, employee.department_id),
        position=employee.position,
        role=employee.role,
        experience=employee.experience,
        onboarding_state=employee.onboarding_state,
        learning_mode=bool(employee.learning_mode),
        profile_public=bool(employee.profile_public),
        # Тумблер включён, только если его вообще разрешено трогать: иначе UI
        # рисовал бы переключатель, который сервер молча откатит.
        show_last_seen=bool(employee.show_last_seen),
        show_last_media=bool(employee.show_last_media),
        can_toggle_last_seen=preferences.allow_hide_last_seen,
        can_toggle_last_media=preferences.allow_hide_media,
        profile_locked=preferences.profile_visibility == "all_open",
        last_seen_at=employee.last_seen_at,
        is_aup=hr_access.is_aup(employee),
        is_admin=hr_access.is_admin(employee),
        is_staff=hr_access.is_staff(employee, user),
        is_active=employee.is_active,
    )


def _task_out(
    task: Task,
    *,
    my_status: str | None = None,
    my_part: str | None = None,
    progress: tuple[int, int] = (0, 0),
    photos: list[PhotoOut] | None = None,
) -> TaskOut:
    return TaskOut(
        id=task.id,
        title=task.title,
        description=task.description,
        expected_result=task.expected_result,
        scope=task.scope,
        department_id=task.department_id,
        assignee_employee_id=task.assignee_employee_id,
        due_at=task.due_at,
        priority=task.priority,
        requires_photo=bool(task.requires_photo),
        comment=task.comment,
        status=task.status,
        created_by_employee_id=task.created_by_employee_id,
        created_at=task.created_at,
        done_at=task.done_at,
        is_overdue=hr_tasks.is_overdue(task),
        mode=task.mode,
        shift_date=task.shift_date,
        requires_review=bool(task.requires_review),
        my_status=my_status,
        my_part=my_part,
        progress_done=progress[0],
        progress_total=progress[1],
        photos=photos or [],
        weekdays=task.weekdays,
        schedule_label=weekdays.label(task.weekdays),
        active_today=weekdays.is_active_on(task.weekdays, hr_checklists.local_today()),
    )


async def _task_views(
    session: AsyncSession, rows: list[Task], employee: Employee
) -> list[TaskOut]:
    """Поручения со личным статусом и прогрессом — одним запросом на список."""
    if not rows:
        return []
    assignments = await session.scalars(
        select(TaskAssignment).where(
            TaskAssignment.task_id.in_([task.id for task in rows])
        )
    )
    mine: dict[int, TaskAssignment] = {}
    totals: dict[int, int] = {}
    done: dict[int, int] = {}
    for assignment in assignments.all():
        totals[assignment.task_id] = totals.get(assignment.task_id, 0) + 1
        if assignment.status == TASK_DONE:
            done[assignment.task_id] = done.get(assignment.task_id, 0) + 1
        if assignment.employee_id == employee.id:
            mine[assignment.task_id] = assignment

    photos = await _photos_by_task(session, [int(task.id) for task in rows])
    out: list[TaskOut] = []
    for task in rows:
        own = mine.get(task.id)
        out.append(
            _task_out(
                task,
                my_status=own.status if own is not None else None,
                my_part=own.part if own is not None else None,
                progress=(done.get(task.id, 0), totals.get(task.id, 0)),
                photos=photos.get(int(task.id), []),
            )
        )
    return out


async def photos_by_task(
    session: AsyncSession, task_ids: list[int]
) -> dict[int, list[PhotoOut]]:
    """Фото по списку поручений — одним запросом, чтобы список не тормозил."""
    return await _photos_by_task(session, task_ids)


async def _photos_by_task(
    session: AsyncSession, task_ids: list[int]
) -> dict[int, list[PhotoOut]]:
    if not task_ids:
        return {}
    photos = list(
        (
            await session.scalars(
                select(TaskPhoto)
                .where(TaskPhoto.task_id.in_(task_ids))
                .order_by(TaskPhoto.created_at, TaskPhoto.id)
            )
        ).all()
    )
    blobs = {}
    media_ids = [p.media_id for p in photos if p.media_id is not None]
    if media_ids:
        from app.db.hr_models import MediaBlob

        for blob in (
            await session.scalars(select(MediaBlob).where(MediaBlob.id.in_(media_ids)))
        ).all():
            blobs[int(blob.id)] = blob
    out: dict[int, list[PhotoOut]] = {}
    for photo in photos:
        if photo.media_id is not None and int(photo.media_id) in blobs:
            blob = blobs[int(photo.media_id)]
            item = PhotoOut(
                id=int(photo.id),
                url=hr_media.url_for(int(blob.id)),
                width=blob.width,
                height=blob.height,
                created_at=photo.created_at,
            )
        else:
            item = PhotoOut(
                id=int(photo.id),
                url=hr_media.photo_url(int(photo.id)),
                created_at=photo.created_at,
            )
        out.setdefault(int(photo.task_id), []).append(item)
    return out


def _checklist_out(view: hr_checklists.ChecklistView) -> ChecklistOut:
    return ChecklistOut(
        run_id=view.run_id,
        template_id=view.template_id,
        template_title=view.template_title,
        kind=view.kind,
        shift_date=view.shift_date,
        status=view.status,
        done=view.progress.done,
        total=view.progress.total,
        progress_text=view.progress.text(),
        hall_id=view.hall_id,
        hall_name=view.hall_name,
        needs_hall=view.needs_hall,
        items=[
            ChecklistItemOut(
                id=item.id,
                title=item.title,
                description=item.description,
                requires_photo=item.requires_photo,
                is_mandatory=item.is_mandatory,
                done=item.done,
                done_at=item.done_at,
                photo_file_id=item.photo_file_id,
                photo_url=item.photo_url,
                note=item.note,
                weekdays=item.weekdays,
                schedule_label=item.schedule_label,
                active=item.active,
            )
            for item in view.items
        ],
    )


# --------------------------------------------------------------------------
# Профиль и онбординг
# --------------------------------------------------------------------------


@router.get("/me/employee", response_model=EmployeeOut)
async def me_employee(
    session: SessionDep, user: CurrentUser, employee: EmployeeDep
) -> EmployeeOut:
    # Заход в приложение: отметка нужна карточке коллеги («был 10 минут назад»).
    # Пишется лениво, не чаще раза в две минуты — см. `hr_profile.touch_seen`.
    await hr_profile.touch_seen(session, employee)
    return await _employee_out(session, employee, user)


@router.get("/employees/{employee_id}/card", response_model=ProfileCardOut)
async def employee_card(
    employee_id: int, session: SessionDep, employee: EmployeeDep
) -> ProfileCardOut:
    """Карточка коллеги: активность и цифры — по правилу видимости профиля.

    Тап по имени в ленте или табеле приводит сюда. Закрытый профиль отдаёт
    только имя/отдел/плашку с `can_view=false` — приложение показывает
    "Профиль закрыт" без запроса к администратору.
    """
    try:
        card = await hr_profile.build_card(session, employee, employee_id)
    except hr_profile.ProfileError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return ProfileCardOut(
        employee_id=card.employee_id,
        display_name=card.display_name,
        department_id=card.department_id,
        department_name=card.department_name,
        position=card.position,
        badge=card.badge,
        badge_emoji=card.badge_emoji,
        role=card.role,
        role_label=card.role_label,
        is_demo=card.is_demo,
        is_self=card.is_self,
        can_manage=card.can_manage,
        profile_open=card.profile_open,
        can_view=card.can_view,
        show_last_seen=card.show_last_seen,
        show_last_media=card.show_last_media,
        can_toggle_last_seen=card.can_toggle_last_seen,
        can_toggle_last_media=card.can_toggle_last_media,
        last_seen_at=card.last_seen_at,
        last_media=(
            ProfileMediaOut(
                id=card.last_media.id,
                url=card.last_media.url,
                at=card.last_media.at,
                caption=card.last_media.caption,
                source=card.last_media.source,  # type: ignore[arg-type]
            )
            if card.last_media is not None
            else None
        ),
        xp=card.xp,
        rank_title=card.rank_title,
        rank_emoji=card.rank_emoji,
        week_xp=card.week_xp,
        week_place=card.week_place,
        week_total=card.week_total,
        checklist_items=card.checklist_items,
        tasks_done=card.tasks_done,
        shifts_done=card.shifts_done,
        activity=[
            ProfileActivityOut(at=item.at, kind=item.kind, text=item.text, ref_id=item.ref_id)
            for item in card.activity
        ],
    )


@router.post("/me/profile-visibility", response_model=EmployeeOut)
async def set_profile_visibility(
    body: ProfileVisibilityIn,
    session: SessionDep,
    user: CurrentUser,
    employee: EmployeeDep,
) -> EmployeeOut:
    """Открыть или закрыть свой профиль для коллег (не для руководителя)."""
    try:
        await hr_profile.set_visibility(session, employee, is_public=body.is_public)
    except PermissionError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="profile_visibility_locked_by_org"
        ) from exc
    return await _employee_out(session, employee, user)


@router.post("/me/privacy", response_model=EmployeeOut)
async def set_privacy(
    body: ProfilePrivacyIn,
    session: SessionDep,
    user: CurrentUser,
    employee: EmployeeDep,
) -> EmployeeOut:
    """Личные тумблеры «последний заход» и «последнее медиа».

    Если руководство запретило выключение, сервер оставит их включёнными и
    вернёт фактическое состояние — UI покажет именно его, а не тот `false`,
    который прислал клиент.
    """
    if body.show_last_seen is None and body.show_last_media is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="nothing_to_update")
    await hr_profile.set_privacy(
        session,
        employee,
        show_last_seen=body.show_last_seen,
        show_last_media=body.show_last_media,
    )
    return await _employee_out(session, employee, user)


@router.post("/me/onboarding", response_model=EmployeeOut)
async def onboarding(
    body: OnboardingIn, session: SessionDep, user: CurrentUser, employee: EmployeeDep
) -> EmployeeOut:
    """Шаги 2–3 первого запуска: подразделение и опыт работы.

    Состояние двигаем вперёд: выбрал подразделение → ждём опыт; выбрал опыт →
    настройка завершена. Оба поля можно прислать одним запросом.
    """
    if (
        body.department_id is None
        and body.experience is None
        and not body.finish
        and body.learning_mode is None
    ):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail="nothing_to_update"
        )

    if body.department_id is not None:
        dept = await hr_departments.get_department(session, body.department_id)
        if dept is None or not dept.is_active:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="department_unavailable")
        employee.department_id = dept.id
        if employee.onboarding_state in {"new", ONBOARDING_DONE}:
            employee.onboarding_state = ONBOARDING_EXPERIENCE

    if body.experience is not None:
        if body.experience not in EXPERIENCES:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="bad_experience")
        employee.experience = body.experience

    # После опыта идёт этап обучения приложению: он закрывается прохождением
    # уроков (`/me/training`), а не этой ручкой. Уже прошедшим обучение
    # (state=done) повторный онбординг его не откатывает.
    if employee.department_id is not None and employee.experience is not None:
        if employee.onboarding_state != ONBOARDING_DONE:
            employee.onboarding_state = ONBOARDING_TRAINING

    if body.learning_mode is not None:
        employee.learning_mode = body.learning_mode

    if body.finish:
        if employee.department_id is None or employee.experience is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, detail="profile_incomplete"
            )
        employee.onboarding_state = ONBOARDING_DONE

    await session.commit()
    await session.refresh(employee)
    return await _employee_out(session, employee, user)


# --------------------------------------------------------------------------
# Обучение пользованию приложением (этап онбординга)
# --------------------------------------------------------------------------


class LessonOut(BaseModel):
    code: str
    title: str
    emoji: str
    minutes: int
    summary: str
    steps: list[str]
    done: bool
    level: int


class TrainingLevelOut(BaseModel):
    """Уровень программы: сколько уроков и сколько из них пройдено."""

    level: int
    title: str
    hint: str
    done: int
    total: int


class TrainingOut(BaseModel):
    """Курс знакомства: уроки, прогресс и что делать дальше."""

    lessons: list[LessonOut]
    levels: list[TrainingLevelOut]
    done: int
    total: int
    percent: int
    complete: bool
    onboarding_state: str
    next_code: str | None = None
    # Сегодняшняя смена по расписанию обучения (учебная / обычная).
    today_training: bool = False
    # Ставка: `full` или `partial` — видна и сотруднику, и управляющему.
    rate_type: str = "full"


def _training_out(
    progress: hr_training.TrainingProgress,
    state: str,
    *,
    today_training: bool = False,
    rate_type: str = "full",
) -> TrainingOut:
    done = set(progress.done)
    next_lesson = next(
        (code for code in hr_training.MANDATORY_CODES if code not in done), None
    )
    return TrainingOut(
        lessons=[
            LessonOut(
                code=lesson.code,
                title=lesson.title,
                emoji=lesson.emoji,
                minutes=lesson.minutes,
                summary=lesson.summary,
                steps=list(lesson.steps),
                done=lesson.code in done,
                level=lesson.level,
            )
            for lesson in hr_training.LESSONS
        ],
        levels=[
            TrainingLevelOut(
                level=item.level,
                title=item.title,
                hint=item.hint,
                done=level_done,
                total=level_total,
            )
            for item, level_done, level_total in hr_training.level_progress(done)
        ],
        done=len(progress.done),
        total=progress.total,
        percent=progress.percent,
        complete=progress.complete,
        onboarding_state=state,
        next_code=next_lesson,
        today_training=today_training,
        rate_type=rate_type,
    )


async def _training_payload(
    session: AsyncSession, employee: Employee
) -> TrainingOut:
    progress = await hr_training.progress(session, employee)
    return _training_out(
        progress,
        employee.onboarding_state,
        today_training=await hr_training_plan.today_is_training(session, employee),
        rate_type=str(employee.rate_type or "full"),
    )


@router.get("/me/training", response_model=TrainingOut)
async def my_training(session: SessionDep, employee: EmployeeDep) -> TrainingOut:
    return await _training_payload(session, employee)


@router.post("/me/training/reset", response_model=TrainingOut)
async def reset_my_training(
    session: SessionDep, employee: EmployeeDep
) -> TrainingOut:
    """Пройти курс знакомства заново.

    Объявлена ДО `/me/training/{code}`: иначе FastAPI разобрал бы `reset` как
    код урока и вернул 404 `unknown_lesson:reset` — ровно та ошибка, которую
    легко не заметить без живого запроса.

    Доступно себе в любой момент (в том числе разработчику — проверить сценарий
    «как у новичка»): снимаются только отметки уроков, отдел и опыт остаются.
    """
    await hr_training.reset(session, employee)
    await session.refresh(employee)
    return await _training_payload(session, employee)


@router.post("/me/training/{code}", response_model=TrainingOut)
async def complete_training_lesson(
    code: str, session: SessionDep, employee: EmployeeDep
) -> TrainingOut:
    """Отметить урок пройденным. Идемпотентно: повторный тап не даёт 409.

    Последний урок НЕ закрывает онбординг сам: сотрудник выбирает, продолжаем
    ли учиться вместе или переходим в обычный режим (`/me/onboarding`). Иначе
    экран выбора «Повторим вместе / Я уже запомнил» проскакивал бы незамеченным.
    """
    try:
        await hr_training.complete(session, employee, code)
    except hr_training.TrainingError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    await session.commit()
    await session.refresh(employee)
    return await _training_payload(session, employee)


@router.get("/departments", response_model=list[DepartmentOut])
async def departments(session: SessionDep, _: CurrentUser) -> list[DepartmentOut]:
    rows = await hr_departments.list_departments(session)
    return [
        DepartmentOut(
            id=d.id, name=d.name, slug=d.slug, emoji=d.emoji, sort_order=d.sort_order
        )
        for d in rows
    ]


@router.get(
    "/departments/{department_id}/overview", response_model=DepartmentOverviewOut
)
async def department_overview(
    department_id: int, session: SessionDep, employee: EmployeeDep
) -> DepartmentOverviewOut:
    """Дашборд подразделения: кто в смене, у кого не закрыто, что горит.

    Открывается тапом по плашке подразделения в ленте. Область видимости
    считает сервер (`hr_people`): сотрудник — только свой отдел и без личных
    отметок времени, руководитель — свои (или все, если так настроили),
    администратор — все.
    """
    try:
        view = await hr_people.overview(session, employee, department_id)
    except hr_people.DepartmentAccessError as exc:
        code = (
            status.HTTP_404_NOT_FOUND
            if str(exc) == "department_not_found"
            else status.HTTP_403_FORBIDDEN
        )
        raise HTTPException(code, detail=str(exc)) from exc
    return DepartmentOverviewOut(
        department_id=view.department_id,
        department_name=view.department_name,
        department_emoji=view.department_emoji,
        can_manage=view.can_manage,
        show_presence=view.show_presence,
        on_shift=view.on_shift,
        overdue=view.overdue,
        people=[
            DepartmentPersonOut(
                employee_id=row.employee_id,
                display_name=row.display_name,
                badge=row.badge,
                badge_emoji=row.badge_emoji,
                position=row.position,
                role=row.role,
                is_demo=row.is_demo,
                is_self=row.is_self,
                shift_status=row.shift_status,
                checklist_done=row.checklist_done,
                checklist_total=row.checklist_total,
                tasks_open=row.tasks_open,
                tasks_overdue=row.tasks_overdue,
                last_seen_at=row.last_seen_at,
                profile_public=row.profile_public,
            )
            for row in view.people
        ],
    )


# --------------------------------------------------------------------------
# Онбординг организации (мастер руководителя)
# --------------------------------------------------------------------------


def _org_setup_out(
    setup: org_setup.OrgSetup, *, can_edit: bool, can_manage_packs: bool = False
) -> OrgSetupOut:
    return OrgSetupOut(
        done=setup.done,
        industry=setup.industry,
        headcount=setup.headcount,
        departments=list(setup.departments),
        sections=list(setup.sections),
        profile_visibility=setup.profile_visibility,
        cross_department_watch=setup.cross_department_watch,
        allow_hide_last_seen=setup.allow_hide_last_seen,
        allow_hide_media=setup.allow_hide_media,
        uz_pack=setup.uz_pack,
        presets=org_setup.presets_for(setup.industry),
        can_edit=can_edit,
        can_manage_packs=can_manage_packs,
    )


def _may_edit_setup(employee: Employee, user: User) -> bool:
    return (
        not employee.is_simulation
        and (
            hr_access.is_aup(employee)
            or hr_access.is_staff(employee, user)
        )
    )


async def _may_manage_packs(
    session: SessionDep, employee: Employee, user: User
) -> bool:
    """Может ли человек включать/выключать языковой пакет.

    Только владелец организации, а не руководитель смены. Причина не в
    строгости: языковой пакет — это будущая платная опция тарифа, то есть
    решение про деньги. Руководитель смены настраивает работу зала, а цену
    подписки берёт на себя тот, кто организацию завёл.

    Роль берётся из `organization_members`, а не из HR-роли: HR-роли меняются
    по сменам, а владелец — нет.
    """
    if employee.is_simulation:
        return False
    row = await orgs.member(session, org_id=employee.org_id, user_id=user.id)
    return row is not None and row.role == "owner"


@router.get("/org-setup", response_model=OrgSetupOut)
async def get_org_setup(
    session: SessionDep, user: CurrentUser, employee: EmployeeDep
) -> OrgSetupOut:
    """Настройка организации — читать можно всем.

    Именно читать: от неё зависят разделы в нижней полосе и правила
    приватности, а не только экран мастера. Менять — лишь руководителю.
    """
    setup = await org_setup.load(session)
    return _org_setup_out(
        setup,
        can_edit=_may_edit_setup(employee, user),
        can_manage_packs=await _may_manage_packs(session, employee, user),
    )


@router.post("/org-setup", response_model=OrgSetupOut)
async def save_org_setup(
    body: OrgSetupIn,
    session: SessionDep,
    user: CurrentUser,
    employee: EmployeeDep,
) -> OrgSetupOut:
    """Сохранить ответы мастера (можно по шагам) и завести подразделения.

    Подразделения создаются только по явному флагу `create_departments`:
    мастер можно пройти повторно и поправить политику, не плодя дубликаты
    отделов с теми же именами.
    """
    if not _may_edit_setup(employee, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="managers_only")

    # Языковой пакет проверяется отдельно от остальных полей: руководитель
    # правит политику смены (и это его право), а пакет — решение владельца.
    # Иначе тумблер, выключенный владельцем, вернул бы первый же сохранённый
    # руководителем шаг мастера — причём молча, вместе с другими ответами.
    if body.uz_pack is not None and not await _may_manage_packs(
        session, employee, user
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="owner_only")

    current = await org_setup.load(session)
    updated = org_setup.apply_answers(
        current,
        industry=body.industry,
        headcount=body.headcount,
        departments=body.departments,
        sections=body.sections,
        profile_visibility=body.profile_visibility,
        cross_department_watch=body.cross_department_watch,
        allow_hide_last_seen=body.allow_hide_last_seen,
        allow_hide_media=body.allow_hide_media,
        uz_pack=body.uz_pack,
        done=body.done,
    )

    if body.create_departments and body.departments is not None:
        existing = {
            dept.name.strip().lower()
            for dept in await hr_departments.list_departments(
                session, active_only=False
            )
        }
        presets = {
            item["name"].strip().lower(): item["emoji"]
            for item in org_setup.presets_for(updated.industry)
        }
        for name in updated.departments:
            if name.strip().lower() in existing:
                continue
            await hr_departments.create_department(
                session, name=name, emoji=presets.get(name.strip().lower())
            )
            existing.add(name.strip().lower())

    if updated.done:
        # Организация без единого подразделения — тупик, а не «пустая
        # настройка»: выбрать отдел при первом запуске не из чего, а профиль
        # без отдела нельзя закрыть (см. `/me/onboarding`). Мастер можно
        # пропустить, поэтому страховка живёт на сервере, а не в кнопке.
        existing_count = await hr_departments.list_departments(
            session, active_only=False
        )
        if not existing_count:
            await hr_departments.create_department(
                session, name="Общее", emoji="🏢"
            )
        # Мастер — это и есть первый запуск руководителя: он только что назвал
        # отрасль, отделы и правила. Спрашивать следом «где ты работаешь» и
        # «как давно ты в деле» — это второй онбординг подряд, а у владельца
        # организации ещё и нет отдела, где он «работает».
        if employee.onboarding_state != ONBOARDING_DONE:
            employee.onboarding_state = ONBOARDING_DONE

    if body.create_departments or updated.done:
        # Новая организация приходит без единого шаблона чек-листа, и первый же
        # рабочий экран сотрудника говорит «попроси руководителя назначить
        # шаблон». Руководителя рядом нет, что просить — непонятно, и рабочий
        # день начинается не с работы, а с переписки. Поэтому вместе с
        # подразделениями мастер заводит стартовую пару: «Открытие смены» и
        # «Закрытие смены». Функция ничего не трогает там, где шаблон уже есть.
        created = await hr_checklists.ensure_starter_templates_for_all(session)
        if created:
            log.info(
                "org_setup.starter_templates",
                count=len(created),
                department_ids=sorted({t.department_id for t in created}),
            )

    await org_setup.save(session, updated)
    return _org_setup_out(
        updated,
        can_edit=True,
        can_manage_packs=await _may_manage_packs(session, employee, user),
    )


# --------------------------------------------------------------------------
# Залы и чек-лист смены
# --------------------------------------------------------------------------


@router.get("/halls", response_model=list[HallOut])
async def halls(session: SessionDep, _employee: EmployeeDep) -> list[HallOut]:
    """Активные залы для выбора перед чек-листом открытия."""
    rows = await hr_checklists.list_halls(session)
    return [
        HallOut(id=h.id, name=h.name, slug=h.slug, sort_order=h.sort_order)
        for h in rows
    ]


@router.post("/checklist/hall", response_model=ChecklistOut)
async def checklist_choose_hall(
    body: ChooseHallIn, session: SessionDep, employee: EmployeeDep
) -> ChecklistOut:
    """Запомнить зал на сегодня и вернуть чек-лист именно этого зала."""
    hall = await hr_checklists.get_hall(session, body.hall_id)
    if hall is None or not hall.is_active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="hall_not_found")
    day = hr_checklists.local_today()
    await hr_checklists.choose_hall(
        session, employee=employee, hall=hall, shift_date=day
    )
    await session.commit()
    view = await hr_checklists.build_view(
        session, employee, kind=TEMPLATE_SHIFT, shift_date=day
    )
    return _checklist_out(view)


@router.get("/checklist", response_model=ChecklistOut)
async def checklist(
    session: SessionDep,
    employee: EmployeeDep,
    kind: str = TEMPLATE_SHIFT,
    shift_date: date | None = None,
) -> ChecklistOut:
    if kind not in TEMPLATE_KINDS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="bad_kind")
    view = await hr_checklists.build_view(
        session, employee, kind=kind, shift_date=shift_date
    )
    return _checklist_out(view)


@router.post("/checklist/complete", response_model=ChecklistOut)
async def checklist_complete(
    body: CompleteIn, session: SessionDep, employee: EmployeeDep
) -> ChecklistOut:
    item = await session.get(ChecklistItem, body.item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="item_not_found")
    template = await hr_checklists.get_template(session, item.template_id)
    if template is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="template_not_found")

    shift_date = hr_checklists.local_today()
    run = await hr_checklists.get_or_create_run(session, employee, template, shift_date)
    try:
        await hr_checklists.complete_item(
            session,
            employee=employee,
            run=run,
            item=item,
            photo_file_id=body.photo_file_id,
            photo_media_id=body.media_id,
            note=body.note,
        )
    except hr_checklists.ChecklistError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await session.commit()

    view = await hr_checklists.build_view(
        session, employee, kind=template.kind, shift_date=shift_date
    )
    return _checklist_out(view)


# --------------------------------------------------------------------------
# Поручения
# --------------------------------------------------------------------------


@router.get("/tasks", response_model=list[TaskOut])
async def my_tasks(
    session: SessionDep,
    employee: EmployeeDep,
    include_closed: bool = False,
    shift_date: date | None = None,
) -> list[TaskOut]:
    """Мои поручения. `shift_date` — только поручения конкретной смены."""
    rows = await hr_tasks.list_for_employee(
        session, employee, include_closed=include_closed
    )
    if shift_date is not None:
        rows = [task for task in rows if task.shift_date == shift_date]
    return await _task_views(session, rows, employee)


async def _owned_task(
    session: AsyncSession, employee: Employee, task_id: int
) -> Task:
    """Задача, доступная этому сотруднику (иначе 404 — не светим чужие id)."""
    task = await hr_tasks.get_task(session, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="task_not_found")
    visible = await hr_tasks.list_for_employee(session, employee, include_closed=True)
    if all(t.id != task.id for t in visible):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="task_not_found")
    return task


async def _transition(
    session: AsyncSession, employee: Employee, task_id: int, to_status: str
) -> TaskOut:
    task = await _owned_task(session, employee, task_id)
    try:
        await hr_tasks.change_status(session, task, to_status, by=employee)
    except hr_tasks.TaskError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await session.commit()
    await session.refresh(task)
    return (await _task_views(session, [task], employee))[0]


@router.post("/tasks/{task_id}/accept", response_model=TaskOut)
async def task_accept(
    task_id: int, session: SessionDep, employee: EmployeeDep
) -> TaskOut:
    from app.db.hr_models import TASK_ACCEPTED

    return await _transition(session, employee, task_id, TASK_ACCEPTED)


@router.post("/tasks/{task_id}/start", response_model=TaskOut)
async def task_start(
    task_id: int, session: SessionDep, employee: EmployeeDep
) -> TaskOut:
    from app.db.hr_models import TASK_IN_PROGRESS

    return await _transition(session, employee, task_id, TASK_IN_PROGRESS)


@router.post("/tasks/{task_id}/done", response_model=TaskOut)
async def task_done(
    task_id: int, session: SessionDep, employee: EmployeeDep
) -> TaskOut:
    """Сдать работу. Для задач с обязательным фото сервер откажет — их
    закрывает загрузка фото (`/tasks/{id}/photo`).

    Если поручение с проверкой, работа уходит руководителю (`on_review`) и
    остаётся открытой, пока он не примет её или не вернёт на доработку.
    """
    task = await _owned_task(session, employee, task_id)
    if task.requires_photo:
        photos = await hr_tasks.photos_of(session, task.id)
        if not photos:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, detail="photo_report_required"
            )
    from app.db.hr_models import TASK_ON_REVIEW
    from app.services import hr_notify

    try:
        await hr_tasks.submit_work(session, task, employee)
    except hr_tasks.TaskError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if task.requires_review and task.status == TASK_ON_REVIEW:
        user = await session.get(User, employee.user_id)
        await hr_notify.notify_task_submitted(
            session,
            task,
            await _managers(session),
            employee_name=user.display_name if user else None,
        )
    await session.commit()
    await session.refresh(task)
    return (await _task_views(session, [task], employee))[0]


class TaskReviewIn(BaseModel):
    approve: bool
    # Принять одного исполнителя в групповом поручении; `None` — всех, кто
    # сдал (обычный случай: руководитель смотрит работу целиком).
    employee_id: int | None = None
    comment: str | None = None


@router.post("/tasks/{task_id}/review", response_model=TaskOut)
async def task_review(
    task_id: int,
    body: TaskReviewIn,
    session: SessionDep,
    employee: EmployeeDep,
) -> TaskOut:
    """Принять работу или вернуть на доработку. Только АУП.

    Сотрудник не может принять сам себя: `review` пишет событие приёмки на
    исполнителя и закрывает задачу, поэтому права проверяются до вызова.
    """
    if not hr_access.is_aup(employee):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="aup_required")
    from app.services import hr_simulation

    if hr_simulation.current() is not None:
        # Приёмка меняет настоящие задачи — в сеансе проверки это запрещено.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="simulation_self_only")
    task = await hr_tasks.get_task(session, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="task_not_found")
    try:
        reviewed = await hr_tasks.review(
            session,
            task,
            manager=employee,
            approve=body.approve,
            employee_id=body.employee_id,
            comment=body.comment,
        )
    except hr_tasks.TaskError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    # Автору работы — в колокольчик: принято или что именно переделать.
    from app.services import hr_notify

    workers = await session.scalars(
        select(Employee).where(
            Employee.id.in_([row.employee_id for row in reviewed])
        )
    )
    await hr_notify.notify_task_reviewed(
        session,
        task,
        list(workers.all()),
        approved=body.approve,
        comment=body.comment,
    )
    await session.commit()
    await session.refresh(task)
    return (await _task_views(session, [task], employee))[0]


@router.get("/tasks/review-queue", response_model=list[TaskOut])
async def review_queue(
    session: SessionDep, employee: EmployeeDep
) -> list[TaskOut]:
    """Что ждёт приёмки руководителя (пусто для сотрудника)."""
    if not hr_access.is_aup(employee):
        return []
    rows = await hr_tasks.pending_reviews(
        session,
        department_id=(
            None if hr_access.is_admin(employee) else employee.department_id
        ),
    )
    unique: dict[int, Task] = {task.id: task for task, _ in rows}
    return await _task_views(session, list(unique.values()), employee)


@router.post("/tasks/{task_id}/issue", response_model=TaskOut)
async def task_issue(
    task_id: int, body: TaskIssueIn, session: SessionDep, employee: EmployeeDep
) -> TaskOut:
    from app.services import hr_notify, hr_reminders

    task = await _owned_task(session, employee, task_id)
    issue = await hr_tasks.add_issue(
        session,
        task,
        employee=employee,
        reason_code=body.reason_code,
        comment=body.comment,
        eta_at=body.eta_at,
    )
    # Руководителя уведомляем в приложении (видит проблему в списке) и в личке
    # бота — с кнопками «решено / напомнить завтра / мьют»: ответить можно
    # прямо в сообщении, не заходя в приложение.
    managers = await _managers(session)
    await hr_notify.notify_issue(session, task, issue, managers)
    await hr_reminders.alert_managers(
        session,
        employees=managers,
        kind=hr_notify.KIND_TASK_ISSUE,
        text=hr_notify.task_issue_text(task, issue),
        task_id=int(task.id),
    )
    await session.commit()
    await session.refresh(task)
    return (await _task_views(session, [task], employee))[0]


@router.post("/tasks/{task_id}/photo", response_model=TaskOut)
async def task_photo(
    task_id: int, body: TaskPhotoIn, session: SessionDep, employee: EmployeeDep
) -> TaskOut:
    task = await _owned_task(session, employee, task_id)
    if body.media_id is None and not body.file_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail="photo_required"
        )
    try:
        await hr_tasks.add_photo(
            session,
            task,
            employee=employee,
            file_id=body.file_id,
            media_id=body.media_id,
        )
    except hr_tasks.TaskError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await session.commit()
    await session.refresh(task)
    return (await _task_views(session, [task], employee))[0]


async def _managers(session: AsyncSession) -> list[Employee]:
    from app.db.hr_models import ROLE_ADMIN, ROLE_AUP

    rows = await session.scalars(
        select(Employee).where(
            Employee.is_active.is_(True),
            Employee.role.in_((ROLE_AUP, ROLE_ADMIN)),
        )
    )
    return list(rows.all())


# --------------------------------------------------------------------------
# Полезные ссылки и обратная связь
# --------------------------------------------------------------------------


@router.get("/links", response_model=list[LinkOut])
async def links(session: SessionDep, employee: EmployeeDep) -> list[LinkOut]:
    rows = await hr_links.list_links(session, employee)
    return [_link_out(link) for link in rows]


def _link_out(link: UsefulLink) -> LinkOut:
    return LinkOut(
        id=link.id,
        title=link.title,
        url=link.url,
        emoji=link.emoji,
        department_id=link.department_id,
    )


def _question_out(q: FeedbackQuestion) -> FeedbackQuestionOut:
    return FeedbackQuestionOut(
        id=q.id,
        code=q.code,
        text=q.text,
        kind=q.kind,
        options=list(q.options or []),
    )


@router.get("/feedback/questions", response_model=list[FeedbackQuestionOut])
async def feedback_questions(
    session: SessionDep, _: CurrentUser
) -> list[FeedbackQuestionOut]:
    rows = await hr_feedback.list_questions(session)
    return [_question_out(q) for q in rows]


@router.post("/feedback", response_model=list[FeedbackQuestionOut])
async def submit_feedback(
    body: FeedbackIn, session: SessionDep, _: CurrentUser, employee: EmployeeDep
) -> list[FeedbackQuestionOut]:
    shift_date = body.shift_date or hr_checklists.local_today()
    answers = [a.model_dump() for a in body.answers]
    try:
        await hr_feedback.submit_answers(
            session, employee=employee, shift_date=shift_date, answers=answers
        )
    except hr_feedback.FeedbackError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await session.commit()
    rows = await hr_feedback.list_questions(session)
    return [_question_out(q) for q in rows]


# --------------------------------------------------------------------------
# Лента событий (видимость — строго по роли)
# --------------------------------------------------------------------------


class FeedItemOut(BaseModel):
    at: datetime
    kind: str
    employee_id: int | None
    user_id: int | None
    display_name: str
    department_id: int | None
    text: str
    ref_id: int | None
    badge: str | None = None
    badge_emoji: str | None = None
    # Тестовый пул `[BOT]`: одна пометка вместо трёх в строке ленты.
    is_demo: bool = False


class FeedOut(BaseModel):
    scope: str
    can_filter: bool
    items: list[FeedItemOut]


class FeedFilterEmployee(BaseModel):
    id: int
    display_name: str
    # Должность — чтобы в фильтре было видно, кто есть кто: в одном отделе
    # могут быть два «Александра», и выбирать наугад нельзя. У владельцев
    # должности нет, зато есть плашка (`badge`), поэтому отдаём и её.
    position: str | None = None
    badge: str | None = None
    department_id: int | None


class FeedFiltersOut(BaseModel):
    scope: str
    can_filter: bool
    kinds: list[str]
    employees: list[FeedFilterEmployee]
    departments: list[DepartmentOut]


@router.get("/feed/filters", response_model=FeedFiltersOut)
async def feed_filters(session: SessionDep, employee: EmployeeDep) -> FeedFiltersOut:
    """Списки для фильтров ленты — только в доступной области видимости.

    Нужен отдельный путь, потому что админский `/api/admin/employees` закрыт
    ролью `admin`: руководитель подразделения (`aup`) не смог бы собрать фильтр
    по своим людям. Здесь же состав списков считается ТЕМ ЖЕ правилом, что и
    сама лента (`hr_feed.allowed_employee_ids`), поэтому подсказки в фильтре не
    могут выдать чужих сотрудников. Сотрудник получает пустые списки и
    `can_filter=false` — фильтровать ему нечего.
    """
    scope = hr_feed.viewer_scope(employee)
    can_filter = hr_feed.can_filter(employee)

    employees: list[FeedFilterEmployee] = []
    departments: list[DepartmentOut] = []
    if can_filter:
        allowed = await hr_feed.allowed_employee_ids(session, employee)
        stmt = (
            select(
                Employee.id,
                Employee.department_id,
                Employee.position,
                Employee.badge,
                User.display_name,
            )
            .join(User, User.id == Employee.user_id)
            .where(
                Employee.is_active.is_(True),
                Employee.is_simulation.is_(False),
            )
            .order_by(User.display_name)
        )
        if allowed is not None:
            stmt = stmt.where(Employee.id.in_(allowed))
        rows = await session.execute(stmt)
        employees = [
            FeedFilterEmployee(
                id=int(eid),
                display_name=str(name),
                position=position,
                badge=badge,
                department_id=did,
            )
            for eid, did, position, badge, name in rows.all()
        ]
        # Подразделения: управляющий видит все, руководитель — только своё.
        # Срез считает hr_feed (та же функция, что и для самой ленты), а не
        # условие в роуте — правило одно и лежит в одном месте.
        all_departments = hr_feed.scoped_departments(
            employee, await hr_departments.list_departments(session)
        )
        departments = [
            DepartmentOut(
                id=d.id,
                name=d.name,
                slug=d.slug,
                emoji=d.emoji,
                sort_order=d.sort_order,
            )
            for d in all_departments
        ]

    return FeedFiltersOut(
        scope=scope,
        can_filter=can_filter,
        kinds=list(hr_feed.ALL_KINDS),
        employees=employees,
        departments=departments,
    )


@router.get("/me/achievements", response_model=AchievementsOut)
async def my_achievements(
    session: SessionDep, employee: EmployeeDep
) -> AchievementsOut:
    """Скрытый блок личного прогресса в профиле.

    Видимость решает сервер (`services/hr_achievements.visible_for`): сейчас
    ачивки показываются только руководителю и администратору, остальным ручка
    отвечает `visible=false` без обращения к базе. Пороги считаются на чтение и
    выдаются идемпотентно, поэтому блок сам «догоняет» закрытые поручения и
    смены — без джоб и событий.
    """
    view = await hr_achievements.view(session, employee)
    return _achievements_out(view)


@router.get("/kpi", response_model=MyKpiOut)
async def my_kpi(session: SessionDep, employee: EmployeeDep) -> MyKpiOut:
    """Опыт за работу и звание — открыто всем, а не только руководителю.

    В отличие от скрытых ачивок это мотивационный блок: сотрудник видит, за что
    получил опыт (пункты, смены, поручения), сколько до следующего звания и где
    он в недельном рейтинге. Никаких штрафов и «антизваний» здесь нет.
    """
    data = await hr_kpi.my_kpi(session, employee, hr_checklists.local_today())
    return to_my_out(data)


@router.get("/feed", response_model=FeedOut)
async def feed(
    session: SessionDep,
    employee: EmployeeDep,
    employee_id: int | None = None,
    department_id: int | None = None,
    kinds: str | None = None,
    limit: int = hr_feed.DEFAULT_LIMIT,
    lang: str = "ru",
) -> FeedOut:
    """Лента действий. Кто что видит — решает сервер (см. `services/hr_feed`).

    Сотрудник получает только свои записи; фильтры по сотруднику/подразделению
    для него игнорируются, а не «прячутся в UI». Руководитель подразделения —
    действия своих; управляющий — всё с фильтрами.
    """
    selected_kinds: tuple[str, ...] | None = None
    if kinds:
        selected_kinds = tuple(
            k.strip() for k in kinds.split(",") if k.strip()
        )
    try:
        items = await hr_feed.build_feed(
            session,
            employee,
            employee_id=employee_id,
            department_id=department_id,
            kinds=selected_kinds,
            limit=limit,
            # Текст записи собирает сервер, поэтому язык приходит параметром:
            # иначе английский интерфейс показывал русские фразы в ленте.
            lang="en" if str(lang).lower().startswith("en") else "ru",
        )
    except PermissionError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return FeedOut(
        scope=hr_feed.viewer_scope(employee),
        can_filter=hr_feed.can_filter(employee),
        items=[
            FeedItemOut(
                at=item.at,
                kind=item.kind,
                employee_id=item.employee_id,
                user_id=item.user_id,
                display_name=item.display_name,
                department_id=item.department_id,
                text=item.text,
                ref_id=item.ref_id,
                badge=item.badge,
                badge_emoji=item.badge_emoji,
                is_demo=item.is_demo,
            )
            for item in items
        ],
    )


# --- Утренняя сводка (план, 8.2) -------------------------------------------


class DigestOut(BaseModel):
    """Числа утра. Ровно то, что приходит руководителю в Telegram."""

    day: date
    overdue_tasks: int
    overdue_titles: list[str]
    planned_today: int
    not_started: int
    open_runs: int
    problems_open: int
    problems_attention: int
    calm: bool


@router.get("/digest", response_model=DigestOut)
async def my_digest(
    session: SessionDep,
    employee: EmployeeDep,
) -> DigestOut:
    """Сводка дня для руководителя.

    Сотруднику без прав она не отдаётся: числа собираются по правилам
    видимости журнала, но сама ручка — управленческая. Пустые числа при этом
    не ошибка: «всё спокойно» — это валидный ответ.
    """
    if not hr_access.is_aup(employee):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="manager_only")
    digest = await hr_digest.build(session, employee)
    return DigestOut(
        day=digest.day,
        overdue_tasks=digest.overdue_tasks,
        overdue_titles=list(digest.overdue_titles),
        planned_today=digest.planned_today,
        not_started=digest.not_started,
        open_runs=digest.open_runs,
        problems_open=digest.problems_open,
        problems_attention=digest.problems_attention,
        calm=digest.calm,
    )


# --- «Спасибо коллеге» (план, 8.4) -----------------------------------------


class KudosTopOut(BaseModel):
    employee_id: int
    display_name: str
    department_id: int | None = None
    count: int


class KudosWeekOut(BaseModel):
    """Неделя благодарностей глазами смотрящего: топ, личные числа, лимит."""

    since: date
    until: date
    top: list[KudosTopOut]
    received: int
    given: int
    my_place: int | None
    today_left: int
    max_per_day: int
    # Скольким людям вообще можно сказать спасибо. Ноль — это не ошибка:
    # у сотрудника без подразделения коллег нет, и интерфейс честно молчит,
    # а не показывает кнопку в пустоту.
    can_thank: int


class KudosIn(BaseModel):
    to_employee_id: int
    # Ограничение шире сервисного (`MAX_MESSAGE`): длинное сообщение должно
    # вернуть понятный код ошибки, а не «422» от валидатора схемы.
    message: str | None = Field(default=None, max_length=400)


async def _kudos_week_out(
    session: AsyncSession, employee: Employee
) -> KudosWeekOut:
    week = await hr_kudos.weekly(session, employee)
    thankable = await hr_kudos.thankable_ids(session, employee)
    return KudosWeekOut(
        since=week.since,
        until=week.until,
        top=[
            KudosTopOut(
                employee_id=row.employee_id,
                display_name=row.display_name,
                department_id=row.department_id,
                count=row.count,
            )
            for row in week.top
        ],
        received=week.received,
        given=week.given,
        my_place=week.my_place,
        today_left=week.today_left,
        max_per_day=hr_kudos.MAX_PER_DAY,
        can_thank=len(thankable),
    )


@router.get("/kudos/week", response_model=KudosWeekOut)
async def kudos_week(
    session: SessionDep, employee: EmployeeDep
) -> KudosWeekOut:
    """Недельный топ благодарностей и личные числа — открыто всем.

    Это мотивационный блок, а не отчёт: сотрудник видит, сколько сказал и
    сколько получил, руководитель — топ своего подразделения. Область видимости
    та же, что у ленты (`hr_feed`), поэтому топ не становится способом узнать
    чужие имена в обход правил.
    """
    return await _kudos_week_out(session, employee)


@router.post("/kudos", response_model=KudosWeekOut)
async def give_kudos(
    body: KudosIn,
    session: SessionDep,
    user: CurrentUser,
    employee: EmployeeDep,
) -> KudosWeekOut:
    """Сказать спасибо коллеге.

    Отвечаем не «ок», а всей неделей сразу: экран обновляется одним запросом,
    и человек видит, что его спасибо попало в топ, а не просто «сохранено».
    Уведомление получателю пишется в той же транзакции — благодарность без
    сообщения человек просто не заметит.
    """
    recipient = await session.get(Employee, body.to_employee_id)
    if recipient is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=hr_kudos.ERR_OUT_OF_SCOPE
        )
    message = (body.message or "").strip() or None
    try:
        await hr_kudos.give(
            session,
            sender=employee,
            to_employee_id=body.to_employee_id,
            message=message,
        )
    except hr_kudos.KudosError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=exc.code) from exc
    await hr_notify.notify_kudos(
        session,
        recipient,
        from_name=user.display_name,
        message=message,
    )
    await session.commit()
    return await _kudos_week_out(session, employee)


class KudosPersonOut(BaseModel):
    employee_id: int
    display_name: str
    department_id: int | None = None
    position: str | None = None
    badge: str | None = None


@router.get("/kudos/people", response_model=list[KudosPersonOut])
async def kudos_people(
    session: SessionDep, employee: EmployeeDep
) -> list[KudosPersonOut]:
    """Кому этот человек может сказать спасибо — список для выбора.

    Отдельная ручка, а не `/feed/filters`: там люди отдаются только тем, кто
    вправе фильтровать ленту, а поблагодарить коллегу нужно каждому, включая
    рядового сотрудника. Правило берётся из `hr_kudos.thankable_ids` — то же
    самое, что и в самой благодарности, поэтому список и проверка не могут
    разойтись.
    """
    ids = await hr_kudos.thankable_ids(session, employee)
    if not ids:
        return []
    rows = await session.execute(
        select(
            Employee.id,
            User.display_name,
            Employee.department_id,
            Employee.position,
            Employee.badge,
        )
        .join(User, User.id == Employee.user_id)
        .where(Employee.id.in_(ids))
        .order_by(User.display_name)
    )
    return [
        KudosPersonOut(
            employee_id=int(eid),
            display_name=str(name),
            department_id=did,
            position=position,
            badge=badge,
        )
        for eid, name, did, position, badge in rows.all()
    ]


class TranslateIn(BaseModel):
    """Строки данных, которые человек хочет прочитать на своём языке.

    Ограничения здесь, а не только в сервисе: ручка не должна превращаться в
    «переведи мне весь экран». 20 строк — это блок задания целиком (заголовок,
    описание, подписи) с запасом; 500 символов — длинный пункт чек-листа.
    """

    target: Literal["en", "uz"]
    texts: list[str] = Field(default_factory=list)


class TranslateItemOut(BaseModel):
    # `None` — перевода нет: либо строка уже не по-русски (`provider="same"`),
    # либо на этом хосте нет модели (`available=false`). Пустая строка вместо
    # `None` выглядела бы как «перевод получился пустым».
    translated: str | None = None
    provider: str | None = None


class TranslateOut(BaseModel):
    target: str
    # Есть ли на этом хосте модель. Amvera на 0,5 ГБ отвечает `false` — и это
    # не ошибка: кэш от другого контура при этом всё равно работает.
    available: bool
    reason: str | None = None
    items: list[TranslateItemOut]


@router.post("/translate", response_model=TranslateOut)
async def translate_data(
    body: TranslateIn,
    session: SessionDep,
    employee: EmployeeDep,
) -> TranslateOut:
    """Перевести данные на язык интерфейса — по нажатию, а не всегда.

    Почему это ручка, а не поле в каждой задаче. Перевод нужен не всем и не
    всегда: одному человеку в бригаде, на один блок, на минуту. Считать его
    заранее для всех заданий — значит платить моделью за то, что никто не
    откроет.

    Почему нажатие, а не автоперевод. Машинный перевод корявый, и подменять им
    текст задания, по которому сотрудник отчитывается, нельзя: он должен уметь
    вернуться к оригиналу одним тапом (это делает фронтенд).
    """
    if not body.texts:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="empty_texts")
    if len(body.texts) > translate_service.MAX_TEXTS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="too_many_texts")
    if any(len(text) > translate_service.MAX_TEXT_CHARS for text in body.texts):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="text_too_long")

    provider = translate_service.get_provider()
    # `supports`, а не просто «провайдер есть»: у узбекского нужна вторая
    # модель (en→uz), и на хосте, где её нет, кнопка не должна обещать
    # английский перевод узбекской строки.
    if provider is not None and not provider.supports(body.target):
        provider = None
    items, reason = await translate_service.translate_texts(
        session, body.texts, body.target, provider=provider
    )
    # Коммит нужен только когда что-то посчитали; `translate_texts` пишет через
    # `ON CONFLICT DO NOTHING`, поэтому повторный запрос ничего не дублирует.
    await session.commit()
    return TranslateOut(
        target=body.target,
        available=provider is not None,
        # `model_unavailable` — это «на этом хосте нет модели для этого языка»,
        # и клиент по нему говорит человеку правду, а не крутит бесконечный
        # спиннер.
        reason=reason,
        items=[
            TranslateItemOut(translated=item.translated, provider=item.provider)
            for item in items
        ],
    )
