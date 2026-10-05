from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
import pytest
from app.config import Config
from app.services.core import DomainError, Service
from tests.conftest import add_person, setup_place


@pytest.mark.parametrize("value", [0, -1, 101, True, "10", 1.5])
def test_quota_config_validation(value):
    with pytest.raises(ValueError):
        Config(max_offers_per_day=value)


@pytest.mark.parametrize("kind", ["application", "invitation"])
def test_quota_interval_cancellation_and_restart(service, kind):
    _, place = setup_place(service)
    add_person(service, 2)
    actor = 2 if kind == "application" else 101
    now = [2000000000.0]
    service.offer_clock = lambda: now[0]
    for n in range(10):
        offer = service.create_offer(actor, kind, 2, place, "Привет")
        service.resolve_offer(actor, offer, "cancel")
        if n == 0:
            with pytest.raises(DomainError, match="три секунды"):
                service.create_offer(actor, kind, 2, place, "Рано")
        now[0] += 3
    restarted = Service(service.config)
    restarted.offer_clock = lambda: now[0]
    with pytest.raises(DomainError, match="24 часа"):
        restarted.create_offer(actor, kind, 2, place, "Лишнее")
    now[0] += 86400
    assert restarted.create_offer(actor, kind, 2, place, "Новый день")


def test_quota_one_concurrent_send_and_unauthorized_does_not_consume(service):
    t1, p1 = setup_place(service)
    _, p2 = setup_place(service, captain=303)
    add_person(service, 2)
    service.offer_clock = lambda: 2000000000
    with pytest.raises(DomainError):
        service.create_offer(2, "invitation", 2, p1, "Нет прав")
    def send(place):
        try:
            return service.create_offer(2, "application", 2, place, "Привет")
        except DomainError:
            return None
    with ThreadPoolExecutor(2) as pool:
        assert sum(result is not None for result in pool.map(send, (p1, p2))) == 1
