"""Opt-in mirror clips: kept only for a teacher who said yes, deleted whenever they say no."""

import secrets
from dataclasses import replace
from datetime import timedelta

from sqlalchemy import text

from app.core.teacher_store import CLIP_RETENTION, StoredClip, TeacherExport
from tests.core.test_teacher_store import (  # noqa: F401  (pytest fixtures)
    ENROLLED,
    Harness,
    _save,
    harness,
    phone_hash,
)

OGG = b"OggS\x00\x02first-recording"
LATER = b"OggS\x00\x02a-later-recording"
LATEST = b"OggS\x00\x02the-newest-recording"
MIME = "audio/ogg"


async def _opt_in(h: Harness, phone_hash: bytes, enabled: bool = True) -> bool:
    async with h.store.locked(phone_hash) as session:
        return await session.set_clip_opt_in(enabled)


async def _keep(h: Harness, phone_hash: bytes, audio: bytes) -> bool:
    async with h.store.locked(phone_hash) as session:
        return await session.save_clip(audio, MIME)


async def _first_and_latest(h: Harness, phone_hash: bytes) -> tuple[StoredClip, StoredClip] | None:
    async with h.store.locked(phone_hash) as session:
        return await session.first_and_latest_clips()


async def _export(h: Harness, phone_hash: bytes) -> TeacherExport:
    async with h.store.locked(phone_hash) as session:
        found = await session.export()
    assert found is not None
    return found


async def _clip_rows(h: Harness) -> int:
    """How many clip rows exist for the teachers this test created."""
    if h.memory is not None:
        return sum(len(clips) for clips in h.memory.clips.values())
    assert h.engine is not None
    async with h.engine.begin() as conn:
        found = await conn.execute(
            text(
                "select count(*) from mirror_clips c join teachers t on t.id = c.teacher_id "
                "where t.phone_hash = any(:hashes)"
            ),
            {"hashes": h.hashes},
        )
        return int(found.scalar_one())


async def _expire_clips(h: Harness, phone_hash: bytes) -> None:
    """Make every clip look past its expiry, without waiting."""
    if h.memory is not None:
        kept = h.memory.clips[phone_hash]
        h.memory.clips[phone_hash] = tuple(
            replace(clip, expires_at=clip.created_at - timedelta(seconds=1)) for clip in kept
        )
        return
    assert h.engine is not None
    async with h.engine.begin() as conn:
        await conn.execute(
            text(
                "update mirror_clips set expires_at = now() - interval '1 second' "
                "where teacher_id = (select id from teachers where phone_hash = :h)"
            ),
            {"h": phone_hash},
        )


async def test_clips_are_off_until_the_teacher_says_yes(harness: Harness, phone_hash: bytes):
    await _save(harness, phone_hash, ENROLLED)

    export = await _export(harness, phone_hash)

    assert export.clip_opt_in is False
    assert export.clip_count == 0


async def test_a_recording_is_dropped_while_the_teacher_has_not_opted_in(
    harness: Harness, phone_hash: bytes
):
    await _save(harness, phone_hash, ENROLLED)

    assert await _keep(harness, phone_hash, OGG) is False

    assert await _clip_rows(harness) == 0
    assert await _first_and_latest(harness, phone_hash) is None


async def test_opting_in_needs_an_enrolled_teacher_with_consent(
    harness: Harness, phone_hash: bytes
):
    assert await _opt_in(harness, phone_hash) is False

    async with harness.store.locked(phone_hash) as session:
        await session.save(ENROLLED, "919876543210")  # saved, but no consent recorded

    assert await _opt_in(harness, phone_hash) is False
    assert await _keep(harness, phone_hash, OGG) is False


async def test_an_opted_in_teacher_has_their_recording_kept_and_counted(
    harness: Harness, phone_hash: bytes
):
    await _save(harness, phone_hash, ENROLLED)
    assert await _opt_in(harness, phone_hash) is True

    assert await _keep(harness, phone_hash, OGG) is True

    export = await _export(harness, phone_hash)
    assert export.clip_opt_in is True
    assert export.clip_count == 1


async def test_the_first_and_the_latest_recording_come_back_with_their_bytes(
    harness: Harness, phone_hash: bytes
):
    await _save(harness, phone_hash, ENROLLED)
    await _opt_in(harness, phone_hash)
    for audio in (OGG, LATER, LATEST):
        await _keep(harness, phone_hash, audio)

    found = await _first_and_latest(harness, phone_hash)

    assert found is not None
    first, latest = found
    assert (first.audio, latest.audio) == (OGG, LATEST)
    assert (first.mime, latest.mime) == (MIME, MIME)
    assert first.created_at <= latest.created_at


async def test_a_single_recording_is_both_the_first_and_the_latest(
    harness: Harness, phone_hash: bytes
):
    await _save(harness, phone_hash, ENROLLED)
    await _opt_in(harness, phone_hash)
    await _keep(harness, phone_hash, OGG)

    found = await _first_and_latest(harness, phone_hash)

    assert found is not None
    assert found[0].audio == found[1].audio == OGG


async def test_a_clip_is_kept_for_exactly_the_retention_period(harness: Harness, phone_hash: bytes):
    await _save(harness, phone_hash, ENROLLED)
    await _opt_in(harness, phone_hash)
    await _keep(harness, phone_hash, OGG)

    found = await _first_and_latest(harness, phone_hash)

    assert found is not None
    assert found[0].expires_at - found[0].created_at == CLIP_RETENTION


async def test_an_expired_clip_is_never_played_back(harness: Harness, phone_hash: bytes):
    await _save(harness, phone_hash, ENROLLED)
    await _opt_in(harness, phone_hash)
    await _keep(harness, phone_hash, OGG)

    await _expire_clips(harness, phone_hash)

    assert await _first_and_latest(harness, phone_hash) is None


async def test_nothing_is_played_back_before_any_recording(harness: Harness, phone_hash: bytes):
    await _save(harness, phone_hash, ENROLLED)
    await _opt_in(harness, phone_hash)

    assert await _first_and_latest(harness, phone_hash) is None


async def test_opting_out_deletes_every_recording_and_stops_new_ones(
    harness: Harness, phone_hash: bytes
):
    await _save(harness, phone_hash, ENROLLED)
    await _opt_in(harness, phone_hash)
    await _keep(harness, phone_hash, OGG)
    await _keep(harness, phone_hash, LATER)

    await _opt_in(harness, phone_hash, enabled=False)

    assert await _clip_rows(harness) == 0
    assert await _keep(harness, phone_hash, LATEST) is False
    export = await _export(harness, phone_hash)
    assert (export.clip_opt_in, export.clip_count) == (False, 0)


async def test_withdrawing_consent_deletes_the_recordings_and_the_opt_in(
    harness: Harness, phone_hash: bytes
):
    await _save(harness, phone_hash, ENROLLED)
    await _opt_in(harness, phone_hash)
    await _keep(harness, phone_hash, OGG)

    async with harness.store.locked(phone_hash) as session:
        await session.withdraw_consent()

    assert await _clip_rows(harness) == 0
    assert await _keep(harness, phone_hash, LATER) is False


async def test_erasing_the_teacher_takes_the_recordings_with_them(
    harness: Harness, phone_hash: bytes
):
    await _save(harness, phone_hash, ENROLLED)
    await _opt_in(harness, phone_hash)
    await _keep(harness, phone_hash, OGG)

    async with harness.store.locked(phone_hash) as session:
        await session.erase()

    assert await _clip_rows(harness) == 0


async def test_one_teachers_recordings_are_not_visible_to_another(
    harness: Harness, phone_hash: bytes
):
    other = secrets.token_bytes(32)
    harness.hashes.append(other)
    await _save(harness, phone_hash, ENROLLED)
    await _save(harness, other, ENROLLED)
    await _opt_in(harness, phone_hash)
    await _keep(harness, phone_hash, OGG)

    assert await _first_and_latest(harness, other) is None
    assert (await _export(harness, other)).clip_count == 0


async def test_the_stored_recording_is_encrypted_at_rest(harness: Harness, phone_hash: bytes):
    if harness.engine is None:
        return  # the in-memory fake has no storage layer to inspect
    await _save(harness, phone_hash, ENROLLED)
    await _opt_in(harness, phone_hash)
    await _keep(harness, phone_hash, OGG)

    async with harness.engine.begin() as conn:
        sealed = (
            await conn.execute(
                text(
                    "select audio_enc from mirror_clips "
                    "where teacher_id = (select id from teachers where phone_hash = :h)"
                ),
                {"h": phone_hash},
            )
        ).scalar_one()

    assert OGG not in bytes(sealed)
