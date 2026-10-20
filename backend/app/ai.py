"""Builds the teacher-facing brain from settings and shared resources.

One model client serves the daily loop, Ask and the practice. Without ANTHROPIC_API_KEY none of
them is built, and Plan, Reflect, Ask, Mirror and the practice answer "unavailable" (the router's
documented behaviour), so a local or demo deployment without a key still runs.
"""

from app.channel.model_budget import RedisModelBudget
from app.config import Settings
from app.core.ask.answer import AskAnviq
from app.core.ask.retrieve import HybridRetriever
from app.core.children.registry import RegistryMisconceptions
from app.core.children.verbalizer import LLMChildVoice
from app.core.coach import Coach
from app.core.daily_loop import DailyLoop, PipelineDailyLoop
from app.core.planner import Planner
from app.core.reflect import Reflector
from app.core.rehearsal import RehearsalEngine
from app.core.rehearsal_flow import RehearsalFlow
from app.core.router_brain import RouterBrain
from app.core.topics import TopicResolverWithModel
from app.core.writers import LLMPlanWriter, LLMReflectionWriter
from app.db.corpus import PostgresFullTextSearch
from app.db.loop_store import PostgresMirrors, PostgresPositions, PostgresUsageSink
from app.llm.client import LLMClient
from app.resources import Resources


def build_llm(resources: Resources, settings: Settings) -> LLMClient | None:
    if settings.anthropic_api_key is None:
        return None
    return LLMClient(
        resources.http,
        settings.anthropic_api_key.get_secret_value(),
        sink=PostgresUsageSink(resources.engine),
    )


def build_router_brain(resources: Resources, settings: Settings) -> RouterBrain:
    """The teacher-facing brain. One model client serves the daily loop, Ask and the practice."""
    llm = build_llm(resources, settings)
    return RouterBrain(
        resources.teacher_store,
        resources.keyring.phone_pepper,
        None if llm is None else _daily_loop(llm, resources, settings),
        None if llm is None else _rehearsals(llm, resources, settings),
        RedisModelBudget(resources.redis, settings.max_model_steps_per_day),
    )


def _daily_loop(llm: LLMClient, resources: Resources, settings: Settings) -> DailyLoop:
    planner = Planner(
        TopicResolverWithModel(llm, settings.model_fast),
        RegistryMisconceptions(),
        LLMPlanWriter(llm, settings.model_smart),
    )
    demo = settings.demo_cycle_minutes
    return PipelineDailyLoop(
        planner,
        Reflector(LLMReflectionWriter(llm, settings.model_smart)),
        PostgresPositions(resources.engine, demo_minutes=demo),
        PostgresMirrors(resources.engine, demo_minutes=demo),
        asker=_ask_anviq(llm, resources, settings),
    )


def _rehearsals(llm: LLMClient, resources: Resources, settings: Settings) -> RehearsalFlow:
    """The practice with the three AI children. The children speak with the fast model."""
    engine = RehearsalEngine(
        LLMChildVoice(llm, settings.model_fast), Coach(llm, settings.model_smart)
    )
    positions = PostgresPositions(resources.engine, demo_minutes=settings.demo_cycle_minutes)
    return RehearsalFlow(engine, positions)


def _ask_anviq(llm: LLMClient, resources: Resources, settings: Settings) -> AskAnviq:
    retriever = HybridRetriever([PostgresFullTextSearch(resources.engine)], settings.ask_min_score)
    return AskAnviq(
        llm, retriever, fast_model=settings.model_fast, smart_model=settings.model_smart
    )
