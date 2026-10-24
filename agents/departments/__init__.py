"""Kisisel asistan departman kayit defteri - 6 departman (okul, iletisim, sistem, telefon, bilgi, gunluk).

CYRAEN (Conductor) karmasik gorevleri departmana + alt ajana delege eder.
"""

from __future__ import annotations

from agents.departments import (
    bilgi,
    gunluk,
    iletisim,
    okul,
    sistem,
    telefon,
)
from agents.schemas import DEPARTMENT_TITLES, AgentSpec, Department, DepartmentSpec

DEPARTMENTS: dict[Department, DepartmentSpec] = {
    Department.OKUL: okul.DEPARTMENT,
    Department.ILETISIM: iletisim.DEPARTMENT,
    Department.SISTEM: sistem.DEPARTMENT,
    Department.TELEFON: telefon.DEPARTMENT,
    Department.BILGI: bilgi.DEPARTMENT,
    Department.GUNLUK: gunluk.DEPARTMENT,
}


def all_agents() -> dict[str, AgentSpec]:
    """name -> AgentSpec (tum departmanlar)."""
    out: dict[str, AgentSpec] = {}
    for dept in DEPARTMENTS.values():
        for agent in dept.agents:
            agent.department = dept.key
            out[agent.name] = agent
    return out


def agents_of(dept: Department) -> list[AgentSpec]:
    return list(DEPARTMENTS[dept].agents)


def department_catalog(agents: dict[str, AgentSpec] | None = None) -> str:
    """Conductor'un routing icin okudugu ozet.

    `agents` verilirse (orn. agents.json override'lari dahil) katalog ondan uretilir;
    yerlesik departman sirasi korunur, yeni departmanlar sona eklenir.
    """
    if agents is None:
        groups = {dept.key: list(dept.agents) for dept in DEPARTMENTS.values()}
    else:
        groups = {key: [] for key in DEPARTMENTS}
        for spec in agents.values():
            groups.setdefault(spec.department, []).append(spec)

    lines: list[str] = []
    for key, specs in groups.items():
        if not specs:
            continue
        if key in DEPARTMENTS:
            dept = DEPARTMENTS[key]
            lines.append(f"\n[{key.value}] {dept.title} - {dept.description}")
        elif key is not None:
            lines.append(f"\n[{key.value}] {DEPARTMENT_TITLES.get(key, key.value)}")
        else:
            lines.append("\n[diger] Departmansiz ajanlar")
        for a in specs:
            lines.append(f"  - {a.name} ({a.title}): {a.description}")
    return "\n".join(lines)


AGENT_COUNT = sum(len(d.agents) for d in DEPARTMENTS.values())
