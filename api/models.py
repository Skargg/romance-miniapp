from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import BigInteger, String, Boolean, Integer, ForeignKey, Text, UniqueConstraint
from .db import Base

# Пользователи
class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    lang: Mapped[str] = mapped_column(String(5), default="ru")
    is_premium: Mapped[bool] = mapped_column(Boolean, default=False)

# Кошелёк/ресурсы
class Wallet(Base):
    __tablename__ = "wallet"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    energy: Mapped[int] = mapped_column(Integer, default=7)
    gems: Mapped[int] = mapped_column(Integer, default=0)
    premium_until: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_energy_at: Mapped[str | None] = mapped_column(String(10), nullable=True)

# Истории и сцены
class Story(Base):
    __tablename__ = "stories"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    start_scene: Mapped[str] = mapped_column(String(100))

class Scene(Base):
    __tablename__ = "scenes"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    story_id: Mapped[int] = mapped_column(ForeignKey("stories.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(100))
    image_url: Mapped[str] = mapped_column(Text, default="")
    is_premium: Mapped[bool] = mapped_column(Boolean, default=False)
    energy_cost: Mapped[int] = mapped_column(Integer, default=0)

class SceneI18n(Base):
    __tablename__ = "scene_i18n"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    scene_id: Mapped[int] = mapped_column(ForeignKey("scenes.id", ondelete="CASCADE"))
    lang: Mapped[str] = mapped_column(String(5))
    text: Mapped[str] = mapped_column(Text)

class Choice(Base):
    __tablename__ = "choices"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    scene_id: Mapped[int] = mapped_column(ForeignKey("scenes.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(100))
    leads_to: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_premium: Mapped[bool] = mapped_column(Boolean, default=False)
    gem_cost: Mapped[int] = mapped_column(Integer, default=0)
    heat_points: Mapped[int] = mapped_column(Integer, default=0)
    requires_item: Mapped[str | None] = mapped_column(String(100), nullable=True)

class ChoiceI18n(Base):
    __tablename__ = "choice_i18n"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    choice_id: Mapped[int] = mapped_column(ForeignKey("choices.id", ondelete="CASCADE"))
    lang: Mapped[str] = mapped_column(String(5))
    label: Mapped[str] = mapped_column(Text)

# Прогресс и мета
class Progress(Base):
    __tablename__ = "progress"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    story_id: Mapped[int] = mapped_column(ForeignKey("stories.id", ondelete="CASCADE"))
    current_scene: Mapped[str] = mapped_column(String(100))

class ProgressMeta(Base):
    __tablename__ = "progress_meta"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    story_id: Mapped[int] = mapped_column(ForeignKey("stories.id", ondelete="CASCADE"), primary_key=True)
    heat_score: Mapped[int] = mapped_column(Integer, default=0)

class GemUnlock(Base):
    __tablename__ = "gem_unlocks"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    story_id: Mapped[int] = mapped_column(ForeignKey("stories.id", ondelete="CASCADE"))
    scene_code: Mapped[str] = mapped_column(String(100))
    __table_args__ = (UniqueConstraint("user_id", "story_id", "scene_code", name="uq_gemunlock"),)

# Рефералка
class Affiliate(Base):
    __tablename__ = "affiliates"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    ref_code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    created_at: Mapped[str] = mapped_column(String(32))

class Referral(Base):
    __tablename__ = "referrals"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    invited_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    source: Mapped[str] = mapped_column(String(32), default="internal")
    created_at: Mapped[str] = mapped_column(String(32))
    __table_args__ = (UniqueConstraint("user_id", name="uq_referrals_user"),)

class RefPayout(Base):
    __tablename__ = "ref_payouts"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    referrer_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    referred_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    amount_cents: Mapped[int] = mapped_column(Integer, default=0)
    reason: Mapped[str] = mapped_column(String(64), default="purchase")
    created_at: Mapped[str] = mapped_column(String(32))

# Согласие 18+
class AgeConsent(Base):
    __tablename__ = "age_consent"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    confirmed_at: Mapped[str] = mapped_column(String(32))

# Инвентарь пользователя (по истории)
class UserItem(Base):
    __tablename__ = "user_items"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    story_id: Mapped[int] = mapped_column(ForeignKey("stories.id", ondelete="CASCADE"))
    item_code: Mapped[str] = mapped_column(String(100))
    __table_args__ = (UniqueConstraint("user_id", "story_id", "item_code", name="uq_user_item"),)
