from typing import Optional, List
import os
import hmac
import hashlib
import json
from urllib.parse import parse_qsl

from fastapi import FastAPI, Depends, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import Base, engine, get_session
from .models import (
    User,
    Wallet,
    Story,
    Scene,
    SceneI18n,
    Choice,
    ChoiceI18n,
    Progress,
    ProgressMeta,
    GemUnlock,
)


app = FastAPI(title="Romance MiniApp API")


@app.on_event("startup")
async def on_startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

# CORS для локального фронтенда
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)


@app.get("/api/health")
async def health():
    return {"ok": True}


# -------------------------------
# Pydantic schemas
# -------------------------------


class ChoiceOut(BaseModel):
    code: str
    label: str
    leads_to: Optional[str] = None
    gem_cost: int = 0
    heat_points: int = 0
    requires_item: Optional[str] = None
    is_premium: bool = False


class SceneOut(BaseModel):
    code: str
    image_url: str
    is_premium: bool
    energy_cost: int
    text: str


class WalletOut(BaseModel):
    energy: int
    gems: int
    is_premium: bool


class StateOut(BaseModel):
    scene: SceneOut
    choices: List[ChoiceOut]
    wallet: WalletOut


class ChooseIn(BaseModel):
    story_code: str
    choice_code: str
    lang: str = "ru"


# Dev: grant resources
class DevGrantIn(BaseModel):
    energy: int = 0
    gems: int = 0
    premium: bool = False


# -------------------------------
# Helpers
# -------------------------------


def _is_premium_active(user: User, wallet: Wallet) -> bool:
    # MVP: считаем активным, если флаг is_premium или есть непустой premium_until
    return bool(user.is_premium or (wallet.premium_until and len(wallet.premium_until) > 0))


def _verify_telegram_init_data(init_data: Optional[str]) -> Optional[int]:
    """Проверка подписи Telegram WebApp initData. Возвращает tg_id или None."""
    if not init_data:
        return None
    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token:
        return None
    # разобрать пары key=value из initData
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        return None
    # data_check_string
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret_key = hashlib.sha256(("WebAppData" + bot_token).encode()).digest()
    computed_hash = hmac.new(secret_key, msg=data_check_string.encode(), digestmod=hashlib.sha256).hexdigest()
    if computed_hash != received_hash:
        return None
    # извлечь user.id
    user_json = pairs.get("user")
    if not user_json:
        return None
    try:
        user_obj = json.loads(user_json)
        tg_id = int(user_obj.get("id"))
        return tg_id
    except Exception:
        return None


async def _get_or_create_user(
    session: AsyncSession, tg_id: int, lang: str
) -> tuple[User, Wallet]:
    user = (
        await session.execute(select(User).where(User.tg_id == tg_id))
    ).scalar_one_or_none()
    if not user:
        user = User(tg_id=tg_id, lang=lang)
        session.add(user)
        await session.flush()
        wallet = Wallet(user_id=user.id)
        session.add(wallet)
        await session.flush()
        await session.commit()
        return user, wallet
    wallet = (
        await session.execute(select(Wallet).where(Wallet.user_id == user.id))
    ).scalar_one_or_none()
    if not wallet:
        wallet = Wallet(user_id=user.id)
        session.add(wallet)
        await session.flush()
        await session.commit()
    return user, wallet


async def _get_story(session: AsyncSession, code: str) -> Story:
    story = (
        await session.execute(select(Story).where(Story.code == code))
    ).scalar_one_or_none()
    if not story:
        raise HTTPException(status_code=404, detail="story_not_found")
    return story


async def _get_or_create_progress(
    session: AsyncSession, user: User, story: Story
) -> tuple[Progress, ProgressMeta]:
    progress = (
        await session.execute(
            select(Progress).where(
                Progress.user_id == user.id, Progress.story_id == story.id
            )
        )
    ).scalar_one_or_none()
    if not progress:
        progress = Progress(user_id=user.id, story_id=story.id, current_scene=story.start_scene)
        session.add(progress)
        await session.flush()
    meta = (
        await session.execute(
            select(ProgressMeta).where(
                ProgressMeta.user_id == user.id, ProgressMeta.story_id == story.id
            )
        )
    ).scalar_one_or_none()
    if not meta:
        meta = ProgressMeta(user_id=user.id, story_id=story.id, heat_score=0)
        session.add(meta)
        await session.flush()
    await session.commit()
    return progress, meta


async def _get_scene_by_code(
    session: AsyncSession, story_id: int, scene_code: str
) -> Scene:
    scene = (
        await session.execute(
            select(Scene).where(Scene.story_id == story_id, Scene.code == scene_code)
        )
    ).scalar_one_or_none()
    if not scene:
        raise HTTPException(status_code=404, detail="scene_not_found")
    return scene


async def _get_scene_text(session: AsyncSession, scene_id: int, lang: str) -> str:
    row = (
        await session.execute(
            select(SceneI18n.text).where(SceneI18n.scene_id == scene_id, SceneI18n.lang == lang)
        )
    ).scalar_one_or_none()
    if row is None:
        # fallback: любой язык
        row = (
            await session.execute(
                select(SceneI18n.text).where(SceneI18n.scene_id == scene_id)
            )
        ).scalar_one_or_none()
    return row or ""


async def _get_choices(
    session: AsyncSession, scene_id: int, lang: str
) -> List[ChoiceOut]:
    choices = (
        await session.execute(select(Choice).where(Choice.scene_id == scene_id))
    ).scalars().all()
    result: List[ChoiceOut] = []
    for ch in choices:
        label = (
            await session.execute(
                select(ChoiceI18n.label).where(
                    ChoiceI18n.choice_id == ch.id, ChoiceI18n.lang == lang
                )
            )
        ).scalar_one_or_none()
        if label is None:
            label = (
                await session.execute(
                    select(ChoiceI18n.label).where(ChoiceI18n.choice_id == ch.id)
                )
            ).scalar_one_or_none() or ch.code
        result.append(
            ChoiceOut(
                code=ch.code,
                label=label,
                leads_to=ch.leads_to,
                gem_cost=ch.gem_cost,
                heat_points=ch.heat_points,
                requires_item=ch.requires_item,
                is_premium=ch.is_premium,
            )
        )
    return result


async def _build_state(
    session: AsyncSession, user: User, wallet: Wallet, story: Story, scene_code: str, lang: str
) -> StateOut:
    scene = await _get_scene_by_code(session, story.id, scene_code)
    text = await _get_scene_text(session, scene.id, lang)
    choices = await _get_choices(session, scene.id, lang)
    return StateOut(
        scene=SceneOut(
            code=scene.code,
            image_url=scene.image_url,
            is_premium=scene.is_premium,
            energy_cost=scene.energy_cost,
            text=text,
        ),
        choices=choices,
        wallet=WalletOut(
            energy=wallet.energy,
            gems=wallet.gems,
            is_premium=_is_premium_active(user, wallet),
        ),
    )


# -------------------------------
# API: /api/state
# -------------------------------


@app.get("/api/state", response_model=StateOut)
async def get_state(
    story: str,
    lang: str = "ru",
    x_telegram_init_data: Optional[str] = Header(None, alias="X-Telegram-Init-Data"),
    x_debug_tg_id: Optional[str] = Header(None, alias="X-Debug-Tg-Id"),
    session: AsyncSession = Depends(get_session),
):
    tg_id: Optional[int] = None
    # Сначала пробуем Telegram initData
    tg_id = _verify_telegram_init_data(x_telegram_init_data)
    if tg_id is None:
        # Фолбэк: локальная отладка по X-Debug-Tg-Id
        if not x_debug_tg_id:
            raise HTTPException(status_code=401, detail="missing_tg_id")
        try:
            tg_id = int(x_debug_tg_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid_tg_id")

    user, wallet = await _get_or_create_user(session, tg_id, lang)
    story_row = await _get_story(session, story)
    progress, _ = await _get_or_create_progress(session, user, story_row)
    return await _build_state(session, user, wallet, story_row, progress.current_scene, lang)


# -------------------------------
# API: /api/choose
# -------------------------------


@app.post("/api/choose", response_model=StateOut)
async def post_choose(
    body: ChooseIn,
    x_telegram_init_data: Optional[str] = Header(None, alias="X-Telegram-Init-Data"),
    x_debug_tg_id: Optional[str] = Header(None, alias="X-Debug-Tg-Id"),
    session: AsyncSession = Depends(get_session),
):
    tg_id: Optional[int] = None
    tg_id = _verify_telegram_init_data(x_telegram_init_data)
    if tg_id is None:
        if not x_debug_tg_id:
            raise HTTPException(status_code=401, detail="missing_tg_id")
        try:
            tg_id = int(x_debug_tg_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid_tg_id")

    lang = body.lang or "ru"
    user, wallet = await _get_or_create_user(session, tg_id, lang)
    story_row = await _get_story(session, body.story_code)
    progress, meta = await _get_or_create_progress(session, user, story_row)

    # текущая сцена
    current_scene = await _get_scene_by_code(session, story_row.id, progress.current_scene)

    # выбор
    choice = (
        await session.execute(
            select(Choice).where(Choice.scene_id == current_scene.id, Choice.code == body.choice_code)
        )
    ).scalar_one_or_none()
    if not choice:
        raise HTTPException(status_code=400, detail="invalid_choice")

    # проверки: предмет
    if choice.requires_item:
        # Инвентаря ещё нет — считаем, что предмета нет
        raise HTTPException(status_code=400, detail="item_required")

    # проверка: премиум
    premium_active = _is_premium_active(user, wallet)
    if choice.is_premium and not premium_active:
        raise HTTPException(status_code=400, detail="premium_required")

    # проверка/списание: гемы (разовый анлок на сцену)
    if choice.gem_cost and choice.gem_cost > 0:
        already_unlocked = (
            await session.execute(
                select(GemUnlock).where(
                    GemUnlock.user_id == user.id,
                    GemUnlock.story_id == story_row.id,
                    GemUnlock.scene_code == current_scene.code,
                )
            )
        ).scalar_one_or_none()
        if not already_unlocked:
            if wallet.gems < choice.gem_cost:
                raise HTTPException(status_code=400, detail="gems_required")
            wallet.gems -= choice.gem_cost
            session.add(GemUnlock(user_id=user.id, story_id=story_row.id, scene_code=current_scene.code))

    # определить следующую сцену
    next_scene_code: Optional[str] = choice.leads_to
    if not next_scene_code:
        # Роутер концовок по heat_score
        heat = meta.heat_score
        if heat <= 0:
            next_scene_code = "ending_soft"
        elif heat <= 2:
            next_scene_code = "ending_hot"
        else:
            next_scene_code = "ending_max"

    # целевая сцена
    target_scene = await _get_scene_by_code(session, story_row.id, next_scene_code)

    # премиум требование также учитываем на вход в premium-сцену
    if target_scene.is_premium and not premium_active:
        raise HTTPException(status_code=400, detail="premium_required")

    # списание энергии за целевую сцену
    if target_scene.energy_cost and target_scene.energy_cost > 0:
        if wallet.energy < target_scene.energy_cost:
            raise HTTPException(status_code=400, detail="energy_required")
        wallet.energy -= target_scene.energy_cost

    # начислить heat
    if choice.heat_points and choice.heat_points > 0:
        meta.heat_score += choice.heat_points

    # сохранить прогресс
    progress.current_scene = target_scene.code

    await session.commit()

    # вернуть новое состояние
    return await _build_state(session, user, wallet, story_row, progress.current_scene, lang)


# -------------------------------
# API: /api/dev/grant (local dev only)
# -------------------------------


@app.post("/api/dev/grant")
async def post_dev_grant(
    body: DevGrantIn,
    x_debug_tg_id: Optional[str] = Header(None, alias="X-Debug-Tg-Id"),
    session: AsyncSession = Depends(get_session),
):
    if not x_debug_tg_id:
        raise HTTPException(status_code=401, detail="missing_tg_id")
    try:
        tg_id = int(x_debug_tg_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid_tg_id")

    user, wallet = await _get_or_create_user(session, tg_id, lang="ru")
    wallet.energy = max(0, wallet.energy + int(body.energy or 0))
    wallet.gems = max(0, wallet.gems + int(body.gems or 0))
    if body.premium:
        user.is_premium = True
    await session.commit()
    return {"ok": True}
