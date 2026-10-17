from app.core.dialogue import EchoBrain, Utterance


async def test_echo_brain_repeats_the_teacher_in_her_language():
    utterance = Utterance(
        "919999900000", "दो जमा दो", "hi", via_voice=True, needs_confirmation=False
    )

    reply = await EchoBrain().respond(utterance)

    assert (reply.text, reply.lang, reply.speak) == ("दो जमा दो", "hi", True)


async def test_echo_brain_asks_before_echoing_an_uncertain_transcript():
    utterance = Utterance("919999900000", "दो", "hi", via_voice=True, needs_confirmation=True)

    reply = await EchoBrain().respond(utterance)

    assert "दो" in reply.text
    assert "सही" in reply.text
