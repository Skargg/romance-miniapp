import asyncio
import asyncio
import os
import sys
import yaml
from pathlib import Path

# --- гарантируем, что корень проекта в sys.path ---
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# ---------------------------------------------------

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from dotenv import load_dotenv

from api.db import engine, AsyncSessionLocal, Base
from api.models import Story, Scene, SceneI18n, Choice, ChoiceI18n

# Windows: psycopg async требует Selector event loop
try:
    import platform
    if platform.system() == "Windows":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
except Exception:
    pass

load_dotenv()
STORY_PATH = os.path.join("content", "stories", "office_flirt", "story.yaml")

async def import_story():
    # 1) создать таблицы, если их ещё нет
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 2) прочитать YAML
    if not os.path.exists(STORY_PATH):
        print(f"Story file not found: {STORY_PATH}")
        return
    with open(STORY_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    async with AsyncSessionLocal() as session:
        # 3) удалить старую историю (аккуратно дочерние сущности)
        old = (await session.execute(select(Story).where(Story.code == data["code"]))).scalar_one_or_none()
        if old:
            scene_ids = [s.id for s in (await session.execute(select(Scene).where(Scene.story_id == old.id))).scalars().all()]
            if scene_ids:
                choice_ids = [c.id for c in (await session.execute(select(Choice).where(Choice.scene_id.in_(scene_ids)))).scalars().all()]
                if choice_ids:
                    await session.execute(delete(ChoiceI18n).where(ChoiceI18n.choice_id.in_(choice_ids)))
                    await session.execute(delete(Choice).where(Choice.id.in_(choice_ids)))
                await session.execute(delete(SceneI18n).where(SceneI18n.scene_id.in_(scene_ids)))
                await session.execute(delete(Scene).where(Scene.id.in_(scene_ids)))
            await session.execute(delete(Story).where(Story.id == old.id))
            await session.commit()

        # 4) создать Story
        st = Story(code=data["code"], start_scene=data["start_scene"])
        session.add(st); await session.flush()

        # 5) сцены + тексты + выборы
        for s in data.get("scenes", []):
            scene = Scene(
                story_id=st.id,
                code=s["code"],
                image_url=s.get("image_url",""),
                is_premium=s.get("is_premium", False),
                energy_cost=s.get("energy_cost", 0),
            )
            session.add(scene); await session.flush()
            for lang, text in s.get("text", {}).items():
                session.add(SceneI18n(scene_id=scene.id, lang=lang, text=text))
            for c in s.get("choices", []):
                choice = Choice(
                    scene_id=scene.id,
                    code=c["code"],
                    leads_to=c.get("leads_to"),
                    is_premium=c.get("is_premium", False),
                    gem_cost=c.get("gem_cost", 0),
                    heat_points=c.get("heat_points", 0),
                    requires_item=c.get("requires_item"),
                )
                session.add(choice); await session.flush()
                for lang, label in c.get("label", {}).items():
                    session.add(ChoiceI18n(choice_id=choice.id, lang=lang, label=label))

        await session.commit()
        print("Story imported:", data["code"])

if __name__ == "__main__":
    asyncio.run(import_story())
