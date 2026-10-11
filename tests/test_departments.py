"""Kisisel asistan departmanlari: kayit defteri, yetenekler, anahtar kelime yonlendirmesi."""
import pytest

from agents.agent_tools import CAPABILITIES, build_callables, known_capabilities
from agents.conductor import Conductor
from agents.departments import AGENT_COUNT, DEPARTMENTS, all_agents
from agents.schemas import DEPARTMENT_TITLES, Department
from agents.skills import SKILLS


def test_six_personal_departments():
    assert {d.value for d in DEPARTMENTS} == {"okul", "iletisim", "sistem", "telefon", "bilgi", "gunluk"}
    assert set(DEPARTMENT_TITLES) == set(Department)
    assert all(DEPARTMENTS[d].agents for d in DEPARTMENTS)


def test_agent_names_unique_and_counted():
    names = [a.name for d in DEPARTMENTS.values() for a in d.agents]
    assert len(names) == len(set(names)) == AGENT_COUNT == len(all_agents())


def test_every_capability_and_skill_exists():
    known = set(known_capabilities())
    for spec in all_agents().values():
        assert set(spec.capabilities) <= known, spec.name
        if spec.skill:
            assert spec.skill in SKILLS, spec.name
        assert spec.department is not None


def test_capability_callables_have_docstrings_for_the_model():
    for cap, fns in CAPABILITIES.items():
        for fn in fns:
            assert (fn.__doc__ or "").strip(), f"{cap}:{fn.__name__}"
    assert {f.__name__ for f in build_callables(["adb"])} == {
        "phone_devices", "phone_unlock", "phone_open", "phone_play_media"}


@pytest.mark.parametrize("task, dept, agent", [
    ("yarın sınavım var, çalışma planı yap", "okul", "sinav_kocu"),
    ("ödevlerimi listele", "okul", "odev_takipcisi"),
    ("gelen maillerimi özetle", "iletisim", "eposta_triyaj"),
    ("telefonda spotify'ı aç", "telefon", "telefon_operatoru"),
    ("bana 10 dakika sonra hatırlat", "gunluk", "hatirlatici"),
    ("docs klasöründeki markdown dosyalarını denetle", "sistem", "markdown_denetcisi"),
    ("kara delikler hakkında araştırma", "bilgi", "arastirmaci"),
])
def test_fallback_routing(task, dept, agent):
    decision = Conductor(None, [])._fallback(task)
    assert (decision.department.value, decision.agent) == (dept, agent)
