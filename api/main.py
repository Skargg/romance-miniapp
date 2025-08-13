from typing import Optional, List
import os
import asyncio
import platform
from pathlib import Path
import hmac
import hashlib
import json
from urllib.parse import parse_qsl
from datetime import datetime, timezone, timedelta

from fastapi import FastAPI, Depends, Header, HTTPException, status, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
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
    AgeConsent,
    UserItem,
)


app = FastAPI(title="Romance MiniApp API")
# Simple in-memory catalog for demo (to be replaced with DB/YAML items)
ITEM_CATALOG: dict[str, dict[str, int]] = {
    "office_flirt": {
        "tshirt_your": 10,
        "whip": 15,
        "sport_top_red": 5,
    }
}


@app.on_event("startup")
async def on_startup():
    # Windows event loop policy for psycopg async
    try:
        if platform.system() == "Windows":
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except Exception:
        pass
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

# CORS (на время разработки)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# Статика фронтенда (если собран dist)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = PROJECT_ROOT / "frontend" / "dist"
if DIST_DIR.exists():
    app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets")


@app.get("/api/health")
async def health():
    return {"ok": True}


@app.get("/")
async def index_root():
    if DIST_DIR.exists():
        index_path = DIST_DIR / "index.html"
        if index_path.exists():
            return FileResponse(index_path)
    return {"ok": True, "hint": "Frontend dist not found. Use npm run build."}


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

class ShopItemOut(BaseModel):
    code: str
    price_gems: int
    owned: bool


class StateOut(BaseModel):
    scene: SceneOut
    choices: List[ChoiceOut]
    wallet: WalletOut
    age_confirmed: bool = False
    items: List[str] = []
    next_energy_in: int = 0
    shop: List[ShopItemOut] = []


class ChooseIn(BaseModel):
    story_code: str
    choice_code: str
    lang: str = "ru"
    init_data: Optional[str] = None


# Dev: grant resources
class DevGrantIn(BaseModel):
    energy: int = 0
    gems: int = 0
    premium: bool = False


class AgeConfirmIn(BaseModel):
    agree: bool


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
        # В DEV режиме без токена можно разрешить парсинг без проверки подписи
        if os.getenv("DEV_ALLOW_UNVERIFIED") == "1":
            try:
                pairs = dict(parse_qsl(init_data, keep_blank_values=True))
                user_json = pairs.get("user")
                if user_json:
                    return int(json.loads(user_json).get("id"))
            except Exception:
                return None
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
        # Разрешить небезопасный режим для локальной отладки через прокси/туннели
        if os.getenv("DEV_ALLOW_UNVERIFIED") == "1":
            try:
                user_obj = json.loads(pairs.get("user", "{}"))
                return int(user_obj.get("id"))
            except Exception:
                return None
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


def _now_ts() -> int:
    return int(datetime.now(tz=timezone.utc).timestamp())


def _regenerate_energy(wallet: Wallet, now_ts: int, cap: int = 7, step_seconds: int = 30 * 60) -> int:
    """Ленивая регенерация энергии. Возвращает секунд до следующего +1."""
    try:
        last_ts = int(wallet.last_energy_at or 0)
    except Exception:
        last_ts = 0

    if wallet.energy >= cap:
        wallet.last_energy_at = str(now_ts)
        return 0

    if last_ts == 0:
        wallet.last_energy_at = str(now_ts)
        return step_seconds

    elapsed = max(0, now_ts - last_ts)
    gained = elapsed // step_seconds
    if gained > 0:
        new_energy = min(cap, wallet.energy + int(gained))
        wallet.energy = new_energy
        # Сдвигаем last_energy_at на целые шаги
        wallet.last_energy_at = str(last_ts + int(gained) * step_seconds)

    # Рассчитать секунды до следующего тика
    last_ts = int(wallet.last_energy_at or now_ts)
    if wallet.energy >= cap:
        return 0
    return max(1, step_seconds - max(0, now_ts - last_ts))


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
    age = (
        await session.execute(select(AgeConsent).where(AgeConsent.user_id == user.id))
    ).scalar_one_or_none()
    owned_items = (
        await session.execute(select(UserItem.item_code).where(UserItem.user_id == user.id, UserItem.story_id == story.id))
    ).scalars().all()
    catalog = ITEM_CATALOG.get(story.code, {})
    shop_list = [
        ShopItemOut(code=icode, price_gems=price, owned=(icode in owned_items))
        for icode, price in catalog.items()
    ]
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
        age_confirmed=bool(age is not None),
        items=list(owned_items),
        shop=shop_list,
    )


# -------------------------------
# API: /api/state
# -------------------------------


@app.get("/api/state", response_model=StateOut)
async def get_state(
    story: str,
    lang: str = "ru",
    x_telegram_init_data: Optional[str] = Header(None, alias="X-Telegram-Init-Data"),
    init_data_q: Optional[str] = Query(None, alias="init_data"),
    x_debug_tg_id: Optional[str] = Header(None, alias="X-Debug-Tg-Id"),
    session: AsyncSession = Depends(get_session),
):
    tg_id: Optional[int] = None
    # Сначала пробуем Telegram initData (header или query)
    tg_id = _verify_telegram_init_data(x_telegram_init_data or init_data_q)
    if tg_id is None:
        # Фолбэк: локальная отладка по X-Debug-Tg-Id
        if not x_debug_tg_id:
            raise HTTPException(status_code=401, detail="missing_tg_id")
        try:
            tg_id = int(x_debug_tg_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid_tg_id")

    user, wallet = await _get_or_create_user(session, tg_id, lang)
    # ленивое восстановление энергии
    next_energy_in = _regenerate_energy(wallet, _now_ts())
    story_row = await _get_story(session, story)
    progress, _ = await _get_or_create_progress(session, user, story_row)
    await session.commit()
    state = await _build_state(session, user, wallet, story_row, progress.current_scene, lang)
    state.next_energy_in = next_energy_in
    return state


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
    tg_id = _verify_telegram_init_data(body.init_data or x_telegram_init_data)
    if tg_id is None:
        if not x_debug_tg_id:
            raise HTTPException(status_code=401, detail="missing_tg_id")
        try:
            tg_id = int(x_debug_tg_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid_tg_id")

    lang = body.lang or "ru"
    user, wallet = await _get_or_create_user(session, tg_id, lang)
    _regenerate_energy(wallet, _now_ts())
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
        have_item = (
            await session.execute(
                select(UserItem).where(
                    UserItem.user_id == user.id,
                    UserItem.story_id == story_row.id,
                    UserItem.item_code == choice.requires_item,
                )
            )
        ).scalar_one_or_none()
        if not have_item:
            price = ITEM_CATALOG.get(story_row.code, {}).get(choice.requires_item, 0)
            raise HTTPException(status_code=400, detail={"code": "item_required", "item_code": choice.requires_item, "price_gems": price})

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

    # выдача предмета, если leads_to помечен в YAML как дающий (через специальный код)
    # Для простоты: если choice.code начинается с 'give_' — item_code = после префикса
    if choice.code.startswith("give_"):
        item_code = choice.code.removeprefix("give_")
        exists = (
            await session.execute(
                select(UserItem).where(
                    UserItem.user_id == user.id,
                    UserItem.story_id == story_row.id,
                    UserItem.item_code == item_code,
                )
            )
        ).scalar_one_or_none()
        if not exists:
            session.add(UserItem(user_id=user.id, story_id=story_row.id, item_code=item_code))

    # сохранить прогресс
    progress.current_scene = target_scene.code

    await session.commit()

    # вернуть новое состояние
    state = await _build_state(session, user, wallet, story_row, progress.current_scene, lang)
    state.next_energy_in = _regenerate_energy(wallet, _now_ts())
    return state


# -------------------------------
# API: /api/purchase/mock (MVP stub)
# -------------------------------


class PurchaseMockIn(BaseModel):
    gems: int = 0
    premium_days: int = 0


@app.post("/api/purchase/mock")
async def post_purchase_mock(
    body: PurchaseMockIn,
    x_telegram_init_data: Optional[str] = Header(None, alias="X-Telegram-Init-Data"),
    x_debug_tg_id: Optional[str] = Header(None, alias="X-Debug-Tg-Id"),
    session: AsyncSession = Depends(get_session),
):
    tg_id: Optional[int] = _verify_telegram_init_data(x_telegram_init_data)
    if tg_id is None:
        if not x_debug_tg_id:
            raise HTTPException(status_code=401, detail="missing_tg_id")
        try:
            tg_id = int(x_debug_tg_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid_tg_id")

    user, wallet = await _get_or_create_user(session, tg_id, lang="ru")
    if body.gems > 0:
        wallet.gems = max(0, wallet.gems + int(body.gems))
    if body.premium_days and body.premium_days > 0:
        user.is_premium = True
    await session.commit()
    return {"ok": True}


# -------------------------------
# API: /api/restart — начать историю заново
# -------------------------------


class RestartIn(BaseModel):
    story_code: str
    lang: str = "ru"


@app.post("/api/restart", response_model=StateOut)
async def post_restart(
    body: RestartIn,
    x_telegram_init_data: Optional[str] = Header(None, alias="X-Telegram-Init-Data"),
    x_debug_tg_id: Optional[str] = Header(None, alias="X-Debug-Tg-Id"),
    session: AsyncSession = Depends(get_session),
):
    tg_id: Optional[int] = _verify_telegram_init_data(x_telegram_init_data)
    if tg_id is None:
        if not x_debug_tg_id:
            raise HTTPException(status_code=401, detail="missing_tg_id")
        try:
            tg_id = int(x_debug_tg_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid_tg_id")

    user, wallet = await _get_or_create_user(session, tg_id, body.lang)
    story_row = await _get_story(session, body.story_code)

    # сброс прогресса
    progress, meta = await _get_or_create_progress(session, user, story_row)
    progress.current_scene = story_row.start_scene
    meta.heat_score = 0
    # очистить разовые анлоки (предметы сохраняем между прохождениями)
    await session.execute(
        select(GemUnlock)  # pragma: no cover
    )
    await session.execute(
        GemUnlock.__table__.delete().where(
            GemUnlock.user_id == user.id, GemUnlock.story_id == story_row.id
        )
    )
    await session.commit()

    state = await _build_state(session, user, wallet, story_row, progress.current_scene, body.lang)
    state.next_energy_in = _regenerate_energy(wallet, _now_ts())
    return state


# -------------------------------
# API: /api/item/buy — покупка предмета за 💎
# -------------------------------


class BuyItemIn(BaseModel):
    story_code: str
    item_code: str
    price_gems: int = 0
    lang: str = "ru"


@app.post("/api/item/buy", response_model=StateOut)
async def post_item_buy(
    body: BuyItemIn,
    x_telegram_init_data: Optional[str] = Header(None, alias="X-Telegram-Init-Data"),
    x_debug_tg_id: Optional[str] = Header(None, alias="X-Debug-Tg-Id"),
    session: AsyncSession = Depends(get_session),
):
    tg_id: Optional[int] = _verify_telegram_init_data(x_telegram_init_data)
    if tg_id is None:
        if not x_debug_tg_id:
            raise HTTPException(status_code=401, detail="missing_tg_id")
        try:
            tg_id = int(x_debug_tg_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid_tg_id")

    user, wallet = await _get_or_create_user(session, tg_id, body.lang)
    story_row = await _get_story(session, body.story_code)

    # уже есть?
    exist = (
        await session.execute(
            select(UserItem).where(
                UserItem.user_id == user.id,
                UserItem.story_id == story_row.id,
                UserItem.item_code == body.item_code,
            )
        )
    ).scalar_one_or_none()
    if exist:
        # просто вернуть состояние
        progress, _ = await _get_or_create_progress(session, user, story_row)
        state = await _build_state(session, user, wallet, story_row, progress.current_scene, body.lang)
        state.next_energy_in = _regenerate_energy(wallet, _now_ts())
        return state

    price = max(0, int(body.price_gems or 0))
    if wallet.gems < price:
        raise HTTPException(status_code=400, detail="gems_required")
    wallet.gems -= price
    session.add(UserItem(user_id=user.id, story_id=story_row.id, item_code=body.item_code))

    progress, _ = await _get_or_create_progress(session, user, story_row)
    await session.commit()
    state = await _build_state(session, user, wallet, story_row, progress.current_scene, body.lang)
    state.next_energy_in = _regenerate_energy(wallet, _now_ts())
    return state


# -------------------------------
# API: /api/dev/grant (local dev only)
# -------------------------------


@app.post("/api/dev/grant")
async def post_dev_grant(
    body: DevGrantIn,
    x_telegram_init_data: Optional[str] = Header(None, alias="X-Telegram-Init-Data"),
    x_debug_tg_id: Optional[str] = Header(None, alias="X-Debug-Tg-Id"),
    session: AsyncSession = Depends(get_session),
):
    tg_id: Optional[int] = _verify_telegram_init_data(x_telegram_init_data)
    if tg_id is None:
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


@app.post("/api/age/confirm")
async def post_age_confirm(
    body: AgeConfirmIn,
    x_telegram_init_data: Optional[str] = Header(None, alias="X-Telegram-Init-Data"),
    x_debug_tg_id: Optional[str] = Header(None, alias="X-Debug-Tg-Id"),
    session: AsyncSession = Depends(get_session),
):
    tg_id: Optional[int] = _verify_telegram_init_data(x_telegram_init_data)
    if tg_id is None:
        if not x_debug_tg_id:
            raise HTTPException(status_code=401, detail="missing_tg_id")
        try:
            tg_id = int(x_debug_tg_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid_tg_id")
    user, _ = await _get_or_create_user(session, tg_id, lang="ru")
    exist = (
        await session.execute(select(AgeConsent).where(AgeConsent.user_id == user.id))
    ).scalar_one_or_none()
    if body.agree:
        if not exist:
            session.add(AgeConsent(user_id=user.id, confirmed_at="now"))
    else:
        if exist:
            # отозвать согласие
            await session.delete(exist)
    await session.commit()
    return {"ok": True}
