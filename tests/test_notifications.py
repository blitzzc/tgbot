import asyncio
import pytest

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramNetworkError, TelegramRetryAfter

from app.bot import deliver_notifications
from app.services.core import Service
from tests.conftest import add_person, setup_place
from tests.telegram_harness import RecordingSession


def test_crash_after_send_waits_then_marks_possible_repeat(service, monkeypatch):
    _, place = setup_place(service)
    add_person(service, 202)
    service.create_offer(202, "application", 202, place, "Привет")
    original = service.notification_result
    def crash(*args):
        raise RuntimeError("Искусственная авария записи результата")
    async def scenario():
        session = RecordingSession()
        bot = Bot("123456:TEST_TRANSPORT_ONLY", session=session)
        try:
            monkeypatch.setattr(service, "notification_result", crash)
            with pytest.raises(RuntimeError):
                await deliver_notifications(bot, service)
            assert len(session.sent) == 1
            restarted = Service(service.config)
            await deliver_notifications(bot, restarted)
            assert len(session.sent) == 1
            with service.db.connect(write=True) as c:
                c.execute("UPDATE notifications SET sending_at=sending_at-61")
            monkeypatch.setattr(service, "notification_result", original)
            await deliver_notifications(bot, service)
            assert len(session.sent) == 2
            assert "Повторное уведомление" in session.sent[-1].text
            await deliver_notifications(bot, service)
            assert len(session.sent) == 2
        finally:
            await bot.session.close()
    asyncio.run(scenario())


def test_claim_is_exclusive_and_old_ack_does_not_override_new_attempt(service):
    _, place = setup_place(service)
    add_person(service, 202)
    service.create_offer(202, "application", 202, place, "Привет")
    notice = service.pending_notifications()[0]
    first = service.claim_notification(notice["id"])
    assert service.claim_notification(notice["id"]) is None
    with service.db.connect(write=True) as c:
        c.execute("UPDATE notifications SET sending_at=sending_at-61")
    second = service.claim_notification(notice["id"])
    service.notification_result(notice["id"], True, claim_token=first["claim_token"])
    with service.db.connect() as c:
        assert c.execute("SELECT status FROM notifications").fetchone()[0] == "pending"
    service.notification_result(notice["id"], True, claim_token=second["claim_token"])


class FailingSession(RecordingSession):
    def __init__(self, failure):
        super().__init__()
        self.failure = failure

    async def make_request(self, bot, method, timeout=None):
        raise self.failure(method=method, message="Тестовый сбой")


def test_delivery_failure_does_not_undo_join_and_records_failed_state(service):
    team_id, place = setup_place(service)
    add_person(service, 202)
    offer = service.create_offer(202, "application", 202, place, "Привет")
    service.resolve_offer(101, offer, "accept")

    async def scenario():
        bot = Bot("123456:TEST_TRANSPORT_ONLY", session=FailingSession(TelegramForbiddenError))
        await deliver_notifications(bot, service)
        await bot.session.close()

    asyncio.run(scenario())
    assert service.membership(202)["team_id"] == team_id
    assert service.vacancy(place)["status"] == "filled"
    with service.db.connect() as c:
        assert {r[0] for r in c.execute("SELECT status FROM notifications")} == {"failed"}


def test_network_error_stays_pending_with_retry(service):
    _, place = setup_place(service)
    add_person(service, 202)
    service.create_offer(202, "application", 202, place, "Привет")

    async def scenario():
        bot = Bot("123456:TEST_TRANSPORT_ONLY", session=FailingSession(TelegramNetworkError))
        await deliver_notifications(bot, service)
        await bot.session.close()

    asyncio.run(scenario())
    with service.db.connect() as c:
        row = c.execute("SELECT * FROM notifications").fetchone()
        assert row["status"] == "pending" and row["attempts"] == 1 and row["next_attempt"] > 0


def test_data_and_pending_notifications_survive_restart(service):
    team_id, place = setup_place(service)
    add_person(service, 202)
    offer = service.create_offer(202, "application", 202, place, "Привет")
    service.resolve_offer(101, offer, "accept")
    restarted = Service(service.config)
    assert restarted.membership(202)["team_id"] == team_id
    assert restarted.offer(202, offer)["status"] == "accepted"
    assert restarted.pending_notifications()


def test_retry_after_respects_telegram_delay(service):
    _, place = setup_place(service)
    add_person(service, 202)
    service.create_offer(202, "application", 202, place, "Привет")

    class RateLimitSession(RecordingSession):
        async def make_request(self, bot, method, timeout=None):
            raise TelegramRetryAfter(method=method, message="Тест", retry_after=90)

    async def scenario():
        bot = Bot("123456:TEST_TRANSPORT_ONLY", session=RateLimitSession())
        await deliver_notifications(bot, service)
        await bot.session.close()

    import time
    before = time.time()
    asyncio.run(scenario())
    with service.db.connect() as c:
        row = c.execute("SELECT * FROM notifications").fetchone()
        assert row["status"] == "pending" and row["next_attempt"] >= before + 90
