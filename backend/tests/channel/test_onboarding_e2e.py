"""A scripted WhatsApp onboarding and deletion through the real pipeline and the real router."""

from app.content.copy import render
from tests.channel.e2e_support import (
    make_harness,
    text_message,
    transcript,
    voice_message,
    welcome_to_first_practice,
)


async def test_a_teacher_can_onboard_entirely_by_voice_note():
    harness = make_harness(
        transcript("नमस्ते"),
        transcript("हिंदी"),
        transcript("दो और तीन मिली-जुली"),
        transcript("हाँ"),
    )

    for _ in range(4):
        await harness.pipeline.handle(voice_message())

    assert harness.texts()[-1] == welcome_to_first_practice("hi")
    assert harness.audio_count() == 3  # nothing is spoken until the language is chosen


async def test_a_typed_english_onboarding_is_answered_in_text_and_voice():
    harness = make_harness()

    for body in ("hello", "English", "2", "yes"):
        await harness.pipeline.handle(text_message(body))

    assert harness.texts()[-1] == welcome_to_first_practice("en")
    assert harness.audio_count() == 3


async def test_deleting_by_voice_erases_the_teacher_and_says_goodbye_in_their_language():
    harness = make_harness(
        transcript("delete my data", "en-IN"), transcript("yes, delete", "en-IN")
    )
    for body in ("hello", "English", "2", "yes"):
        await harness.pipeline.handle(text_message(body))

    await harness.pipeline.handle(voice_message())
    await harness.pipeline.handle(voice_message())

    assert harness.texts()[-1] == render("deleted", "en")
    assert harness.store.teachers == {}
