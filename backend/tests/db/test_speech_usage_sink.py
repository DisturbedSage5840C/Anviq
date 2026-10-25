from contextlib import asynccontextmanager
from decimal import Decimal

from app.db.loop_store import PostgresSpeechUsageSink
from app.speech.metering import SpeechUsage


class FakeConn:
    def __init__(self) -> None:
        self.statements: list[tuple[str, dict]] = []

    async def execute(self, statement, params) -> None:
        self.statements.append((str(statement), params))


class FakeEngine:
    def __init__(self) -> None:
        self.conn = FakeConn()

    @asynccontextmanager
    async def begin(self):
        yield self.conn


async def test_a_usage_row_carries_only_amounts_into_speech_usage() -> None:
    engine = FakeEngine()
    sink = PostgresSpeechUsageSink(engine)  # type: ignore[arg-type]

    await sink.record(SpeechUsage("sarvam", "stt", Decimal("12.5"), Decimal("0.1042")))

    [(sql, params)] = engine.conn.statements
    assert "insert into speech_usage" in sql
    assert params == {
        "provider": "sarvam",
        "kind": "stt",
        "amount": Decimal("12.5"),
        "cost": Decimal("0.1042"),
    }
