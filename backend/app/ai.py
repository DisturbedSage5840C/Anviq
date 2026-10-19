"""Builds the model-backed parts from settings and shared resources.

Without ANTHROPIC_API_KEY nothing here is built, and Plan, Reflect and Mirror answer
"unavailable" (the router's documented behaviour), so a local or demo deployment without a key
still runs.
"""

from app.config import Settings
from app.core.ask.answer import AskAnviq
from app.core.ask.retrieve import HybridRetriever
from app.core.children.registry import RegistryMisconceptions
from app.core.daily_loop import DailyLoop, PipelineDailyLoop
from app.core.planner import Planner
from app.core.reflect import Reflector
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


def build_daily_loop(resources: Resources, settings: Settings) -> DailyLoop | None:
    llm = build_llm(resources, settings)
    if llm is None:
        return None
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
    )


def build_ask(resources: Resources, settings: Settings) -> AskAnviq | None:
    """Ask Anviq over the ingested corpus. The router's ASK phase is not wired to it yet."""
    llm = build_llm(resources, settings)
    if llm is None:
        return None
    retriever = HybridRetriever([PostgresFullTextSearch(resources.engine)], settings.ask_min_score)
    return AskAnviq(
        llm, retriever, fast_model=settings.model_fast, smart_model=settings.model_smart
    )
