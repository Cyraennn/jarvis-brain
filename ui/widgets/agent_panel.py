"""Sol kenar panel: 6 departman agaci + otonomi rozetleri + ajan detay karti + gorev akisi."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QLabel,
    QListWidget,
    QListWidgetItem,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ui import theme
from ui.strings import AUTONOMY_LABELS, DEPARTMENT_TITLES, TASK_STATUS_LABELS, tr_upper

# Kisilik paleti degisince yerinde guncellenir (refresh_palette_colors)
_STATUS: dict[str, tuple[str, str]] = {}
_AUTONOMY: dict[str, tuple[str, str]] = {}


def refresh_palette_colors() -> None:
    status_color = {
        "idle": theme.TEXT_FAINT, "queued": theme.WARN, "routing": theme.ACCENT, "running": theme.ACCENT,
        "tool": theme.ACCENT, "awaiting_approval": theme.WARN, "done": theme.GOOD, "failed": theme.BAD,
        "blocked": theme.MYSTIC, "cancelled": theme.TEXT_FAINT,
    }
    autonomy_color = {
        "fully_autonomous": theme.ACCENT, "human_assisted": theme.GOLD, "human_led": theme.MYSTIC,
    }
    _STATUS.update({k: (c, TASK_STATUS_LABELS[k]) for k, c in status_color.items()})
    _AUTONOMY.update({k: (c, AUTONOMY_LABELS[k]) for k, c in autonomy_color.items()})


refresh_palette_colors()
_DEP_TITLE = {k: tr_upper(v) for k, v in DEPARTMENT_TITLES.items()}


class AgentPanel(QWidget):
    agent_selected = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._specs: dict[str, object] = {}
        self._items: dict[str, QTreeWidgetItem] = {}

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 4)
        lay.setSpacing(3)

        h1 = QLabel("DEPARTMANLAR")
        self._h1 = h1
        h1.setObjectName("navHeader")
        lay.addWidget(h1)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setIndentation(12)
        self._tree.setFrameShape(QTreeWidget.Shape.NoFrame)
        self._tree.itemClicked.connect(self._on_click)
        lay.addWidget(self._tree, 3)

        self._detail = QTextEdit()
        self._detail.setReadOnly(True)
        self._detail.setMaximumHeight(180)
        self._detail.setObjectName("log")
        self._detail.setHtml(self._detail_html(None))
        lay.addWidget(self._detail)

        h2 = QLabel("GÖREV AKIŞI")
        self._h2 = h2
        h2.setObjectName("navHeader")
        lay.addWidget(h2)
        self._feed = QListWidget()
        self._feed.setFrameShape(QListWidget.Shape.NoFrame)
        self._feed.setWordWrap(True)
        lay.addWidget(self._feed, 2)

    # ------------------------------------------------------------------ API
    def sections(self) -> dict[str, QWidget]:
        """HUD: agac / detay / gorev akisini ayri kartlara tasimak icin panelden cikarir.

        Mantik (set_agents, add_task_update...) bu nesnede kalir; yalnizca widget'lar yer degistirir.
        """
        lay = self.layout()
        for w in (self._h1, self._tree, self._detail, self._h2, self._feed):
            lay.removeWidget(w)
        self._h1.hide()
        self._h2.hide()
        self.hide()
        return {"tree": self._tree, "detail": self._detail, "feed": self._feed}

    def set_agents(self, agents: list) -> None:
        self._h1.setText(f"DEPARTMANLAR · {len(agents)} AJAN")
        self._tree.clear()
        self._specs.clear()
        self._items.clear()
        by_dep: dict[str, list] = {}
        for s in agents:
            self._specs[getattr(s, "name", str(s))] = s
            dep = getattr(getattr(s, "department", None), "value", None) or "genel"
            by_dep.setdefault(dep, []).append(s)

        for dep in sorted(by_dep):
            top = QTreeWidgetItem([f"▸ {_DEP_TITLE.get(dep, dep.upper())}"])
            top.setForeground(0, QColor(theme.ACCENT))
            top.setExpanded(False)
            self._tree.addTopLevelItem(top)
            for s in by_dep[dep]:
                name = getattr(s, "name", str(s))
                title = getattr(s, "title", name)
                auto = getattr(getattr(s, "autonomy", None), "value", "")
                acol, alabel = _AUTONOMY.get(auto, (theme.TEXT_FAINT, ""))
                child = QTreeWidgetItem([f"● {title}"])
                child.setData(0, Qt.ItemDataRole.UserRole, name)
                child.setForeground(0, QColor(theme.TEXT_DIM))
                child.setToolTip(0, f"{alabel}")
                top.addChild(child)
                self._items[name] = child

    def refresh_theme(self) -> None:
        """Kisilik paleti degisti: departman basliklari yeni vurgu rengini alir."""
        refresh_palette_colors()
        accent = QColor(theme.ACCENT)
        for i in range(self._tree.topLevelItemCount()):
            self._tree.topLevelItem(i).setForeground(0, accent)

    def set_agent_status(self, name: str, status: str) -> None:
        item = self._items.get(name)
        if item is None:
            return
        color, label = _STATUS.get(status, (theme.TEXT_FAINT, status))
        spec = self._specs.get(name)
        title = getattr(spec, "title", name)
        item.setText(0, f"● {title}   · {label}")
        item.setForeground(0, QColor(color))

    def add_task_update(self, update) -> None:
        status = getattr(update, "status", "")
        color, label = _STATUS.get(status, (theme.TEXT_DIM, status))
        spec = self._specs.get(getattr(update, "agent", ""))
        agent = getattr(spec, "title", getattr(update, "agent", "?"))
        dep = getattr(update, "department", "")
        result = getattr(update, "result", None)
        detail = getattr(update, "detail", "") or ""
        text = (result if (result and status == "done") else detail or "").strip()
        if len(text) > 110:
            text = text[:110] + "…"
        head = f"[{label}] {agent}" + (f"  ({_DEP_TITLE.get(dep, dep)})" if dep else "")
        item = QListWidgetItem(head + (f"\n{text}" if text else ""))
        item.setForeground(QColor(color))
        self._feed.insertItem(0, item)
        while self._feed.count() > 80:
            self._feed.takeItem(self._feed.count() - 1)

    def expand_department(self, dept_key: str) -> None:
        """Beyin haritasinda tiklanan departmani agacta ac + one getir (digerlerini kapat)."""
        target = _DEP_TITLE.get(dept_key, dept_key.upper())
        for i in range(self._tree.topLevelItemCount()):
            top = self._tree.topLevelItem(i)
            match = top.text(0).removeprefix("▸ ") == target
            top.setExpanded(match)
            if match:
                self._tree.setCurrentItem(top)
                self._tree.scrollToItem(top)

    def select(self, name: str) -> None:
        item = self._items.get(name)
        if item is not None:
            self._tree.setCurrentItem(item)
            item.parent().setExpanded(True)
            self._detail.setHtml(self._detail_html(self._specs.get(name)))

    # ------------------------------------------------------------- internal
    def _on_click(self, item: QTreeWidgetItem, _col: int) -> None:
        name = item.data(0, Qt.ItemDataRole.UserRole)
        if name:
            self._detail.setHtml(self._detail_html(self._specs.get(str(name))))
            self.agent_selected.emit(str(name))
        else:
            item.setExpanded(not item.isExpanded())

    def _detail_html(self, spec) -> str:
        if spec is None:
            return (f"<div style='color:{theme.TEXT_FAINT};font-size:11px;'>"
                    "Bir ajana tıkla — SOP, otonomi ve skill dosyaları burada görünür.</div>")
        auto = getattr(getattr(spec, "autonomy", None), "value", "")
        acol, alabel = _AUTONOMY.get(auto, (theme.TEXT_FAINT, auto))
        skills = getattr(spec, "skills", []) or []
        sop = getattr(spec, "sop", "") or "—"
        skill_html = "".join(
            f"<div style='color:{theme.ACCENT};font-size:10px;'>⬇ {s}</div>" for s in skills
        ) or f"<div style='color:{theme.TEXT_FAINT};font-size:10px;'>skill dosyası yok</div>"
        return (
            f"<div style='font-size:12px;color:{theme.TEXT};font-weight:700;'>"
            f"{getattr(spec, 'title', '')}</div>"
            f"<div style='margin:3px 0;'><span style='background:{acol};color:#06070d;"
            f"padding:1px 6px;border-radius:4px;font-size:9px;font-weight:700;'>{alabel}</span></div>"
            f"<div style='color:{theme.TEXT_DIM};font-size:10px;margin:4px 0;'>"
            f"<b style='color:{theme.ACCENT};'>SOP:</b> {sop}</div>"
            f"<div style='margin-top:4px;'>{skill_html}</div>"
        )
