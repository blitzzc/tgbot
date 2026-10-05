import asyncio
import pytest
from tests.conftest import setup_place, add_person
from tests.telegram_harness import TelegramHarness


@pytest.mark.parametrize("pause", [True, False])
def test_outdated_reason_hint_notice_and_no_revival(service, pause):
    team, place = setup_place(service)
    add_person(service, 2)
    offer = service.create_offer(2, "application", 2, place, "Привет")
    if pause:
        service.set_recruitment(101, team, False)
        service.set_recruitment(101, team, True)
    else:
        service.close_vacancy(101, place)
        service.reuse_vacancy(101, place, service.vacancy(place)["version"])
    assert service.offer(2, offer)["status"] == "outdated"
    notices = [n["body"] for n in service.pending_notifications() if n["user_id"] == 2]
    assert any("можно подать новую заявку" in text for text in notices)
    async def scenario():
        h = TelegramHarness(service)
        try:
            await h.send(2, "/start")
            await h.callback(2, f"offer:view:{offer}")
            assert "Причина:" in h.last(2).text
            assert "можно подать новую заявку" in h.last(2).text
            await h.callback(2, f"offer:accept:{offer}")
            assert service.membership(2) is None
        finally:
            await h.close()
    asyncio.run(scenario())
