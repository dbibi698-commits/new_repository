"""gui/overlays.py — Panels that open over the HUD: setup, customise, plugins, confirm, audio, memory, remote.

Split out of ui.py in Mark LVII; behaviour unchanged."""
from __future__ import annotations

import json
import math
import os
import platform
import random
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil

from PyQt6.QtCore import (
    QEasingCurve, QLineF, QMimeData, QObject, QParallelAnimationGroup, QPointF,
    QPoint, QPropertyAnimation, QRect, QRectF, QSize, QSizeF, Qt, QTimer,
    QUrl, pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush, QColor, QConicalGradient, QDragEnterEvent, QDropEvent, QFont,
    QFontDatabase, QKeySequence, QLinearGradient, QPainter, QPainterPath,
    QPen, QPixmap, QRadialGradient, QShortcut,
)
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QPushButton, QScrollArea, QSizePolicy, QSplitter,
    QGraphicsScene, QGraphicsView, QGraphicsPixmapItem,
    QStackedWidget, QTextEdit, QVBoxLayout, QWidget, QProgressBar, QSlider,
)

from gui.theme import (
    C,
    DEFAULT_UI_COLOR,
    _OS,
    qcol,
)

from gui.style import hud_font, mono_font

from core.agents import REGISTRY


class SetupOverlay(QWidget):
    done = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            SetupOverlay {{
                background: rgba(0, 6, 10, 245);
                border: 1px solid {C.BORDER_B};
                border-radius: 6px;
            }}
        """)

        detected = {"darwin": "mac", "windows": "windows"}.get(
            _OS.lower(), "linux"
        )
        self._sel_os = detected

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 22, 30, 22)
        layout.setSpacing(8)

        def _lbl(txt, font_size=9, bold=False, color=C.PRI,
                 align=Qt.AlignmentFlag.AlignCenter):
            w = QLabel(txt)
            w.setAlignment(align)
            w.setFont(hud_font(font_size,
                            QFont.Weight.Bold if bold else QFont.Weight.Normal))
            w.setStyleSheet(f"color: {color}; background: transparent;")
            return w

        layout.addWidget(_lbl("◈  INITIALISATION REQUIRED", 13, True))
        layout.addWidget(_lbl("Configure J.A.R.V.I.S. before first boot.", 9, color=C.PRI_DIM))
        layout.addSpacing(6)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER};"); layout.addWidget(sep)
        layout.addSpacing(4)

        layout.addWidget(_lbl("GEMINI API KEY", 8, color=C.TEXT_DIM,
                               align=Qt.AlignmentFlag.AlignLeft))
        self._key_input = QLineEdit()
        self._key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._key_input.setPlaceholderText("AIza…")
        self._key_input.setFont(hud_font(10))
        self._key_input.setFixedHeight(32)
        self._key_input.setStyleSheet(f"""
            QLineEdit {{
                background: #000d12; color: {C.TEXT};
                border: 1px solid {C.BORDER}; border-radius: 3px; padding: 4px 8px;
            }}
            QLineEdit:focus {{ border: 1px solid {C.PRI}; }}
        """)
        layout.addWidget(self._key_input)
        layout.addSpacing(12)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"color: {C.BORDER};"); layout.addWidget(sep2)
        layout.addSpacing(4)

        layout.addWidget(_lbl("OPERATING SYSTEM", 8, color=C.TEXT_DIM,
                               align=Qt.AlignmentFlag.AlignLeft))
        det_name = {"windows": "Windows", "mac": "macOS", "linux": "Linux"}[detected]
        layout.addWidget(_lbl(f"Auto-detected: {det_name}", 8, color=C.ACC2,
                               align=Qt.AlignmentFlag.AlignLeft))

        os_row = QHBoxLayout(); os_row.setSpacing(6)
        self._os_btns: dict[str, QPushButton] = {}
        for key, label in [("windows","⊞  Windows"),("mac","  macOS"),("linux","🐧  Linux")]:
            btn = QPushButton(label)
            btn.setFont(hud_font(9, QFont.Weight.Bold))
            btn.setFixedHeight(32)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, k=key: self._sel(k))
            os_row.addWidget(btn)
            self._os_btns[key] = btn
        layout.addLayout(os_row)
        self._sel(detected)
        layout.addSpacing(12)

        init_btn = QPushButton("▸  INITIALISE SYSTEMS")
        init_btn.setFont(hud_font(10, QFont.Weight.Bold))
        init_btn.setFixedHeight(36)
        init_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        init_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.PRI};
                border: 1px solid {C.PRI_DIM}; border-radius: 3px;
            }}
            QPushButton:hover {{
                background: {C.PRI_GHO}; border: 1px solid {C.PRI};
            }}
        """)
        init_btn.clicked.connect(self._submit)
        layout.addWidget(init_btn)

        # Gemini is not required. Somebody running a model on their own machine,
        # or out of free quota, has to be able to start without a key.
        local_btn = QPushButton("NO KEY — USE A LOCAL MODEL")
        local_btn.setFont(hud_font(9, QFont.Weight.Bold))
        local_btn.setFixedHeight(30)
        local_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        local_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_DIM};
                border: 1px solid {C.BORDER}; border-radius: 3px;
            }}
            QPushButton:hover {{ color: {C.TEXT}; border: 1px solid {C.BORDER_B}; }}
        """)
        local_btn.clicked.connect(lambda: self.done.emit("", self._sel_os))
        layout.addWidget(local_btn)

    def _sel(self, key: str):
        self._sel_os = key
        pal = {"windows":(C.PRI,"#001a22"),"mac":(C.ACC2,"#1a1400"),"linux":(C.GREEN,"#001a0d")}
        for k, btn in self._os_btns.items():
            if k == key:
                fg, bg = pal[k]
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {fg}; color: {bg};
                        border: none; border-radius: 3px; font-weight: bold;
                    }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: #000d12; color: {C.TEXT_DIM};
                        border: 1px solid {C.BORDER}; border-radius: 3px;
                    }}
                    QPushButton:hover {{ color: {C.TEXT}; border: 1px solid {C.BORDER_B}; }}
                """)

    def _submit(self):
        key = self._key_input.text().strip()
        if not key:
            self._key_input.setStyleSheet(
                self._key_input.styleSheet() +
                f" QLineEdit {{ border: 1px solid {C.RED}; }}"
            )
            return
        self.done.emit(key, self._sel_os)


class HueWheel(QWidget):
    """
    Circular colour picker. The user drags the handle (small white circle)
    around the wheel to choose from ALL hues. The filled circle in the centre
    is a live preview of the selected colour.
    """

    hue_picked    = pyqtSignal(str)   # while dragging (live)
    hue_committed = pyqtSignal(str)   # when the handle is released

    _RING = 16   # ring thickness (px)

    def __init__(self, initial_hex: str = DEFAULT_UI_COLOR, parent=None):
        super().__init__(parent)
        self.setFixedSize(148, 148)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hue  = 0.53
        self._drag = False
        self.set_color(initial_hex)

    # ── API ──────────────────────────────────────────────────────────────────
    def color(self) -> str:
        return QColor.fromHsvF(self._hue, 1.0, 1.0).name()

    def set_color(self, hex_str: str):
        c = QColor((hex_str or "").strip())
        if c.isValid() and c.hsvHueF() >= 0:
            self._hue = c.hsvHueF()
            self.update()

    # ── geometry helpers ─────────────────────────────────────────────────────
    def _ring_rect(self) -> QRectF:
        m = self._RING / 2 + 3
        return QRectF(self.rect()).adjusted(m, m, -m, -m)

    def _hue_from_pos(self, pos: QPointF) -> float:
        c  = QRectF(self.rect()).center()
        dx = pos.x() - c.x()
        dy = c.y() - pos.y()          # screen y goes down — flip to math axis
        ang = math.atan2(dy, dx)      # [-π, π], counter-clockwise
        return (ang / (2 * math.pi)) % 1.0

    # ── drawing ──────────────────────────────────────────────────────────────
    def paintEvent(self, _):
        p = QPainter(self)
        if not p.isActive():
            return
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect   = self._ring_rect()
        center = rect.center()

        grad = QConicalGradient(center, 0)
        for i in range(0, 361, 20):
            grad.setColorAt(i / 360.0, QColor.fromHsvF((i % 360) / 360.0, 1.0, 1.0))
        p.setPen(QPen(QBrush(grad), self._RING))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(rect)

        # centre preview circle
        preview = QColor.fromHsvF(self._hue, 1.0, 1.0)
        inner   = rect.adjusted(30, 30, -30, -30)
        p.setPen(QPen(qcol(C.BORDER_B), 1))
        p.setBrush(QBrush(preview))
        p.drawEllipse(inner)

        # draggable handle
        r   = rect.width() / 2
        ang = self._hue * 2 * math.pi
        hx  = center.x() + r * math.cos(ang)
        hy  = center.y() - r * math.sin(ang)
        p.setPen(QPen(QColor("#00060a"), 2))
        p.setBrush(QBrush(QColor("#ffffff")))
        p.drawEllipse(QPointF(hx, hy), 7.5, 7.5)
        p.end()

    # ── fare ─────────────────────────────────────────────────────────────────
    def mousePressEvent(self, e):
        self._drag = True
        self._hue  = self._hue_from_pos(e.position())
        self.update()
        self.hue_picked.emit(self.color())

    def mouseMoveEvent(self, e):
        if self._drag:
            self._hue = self._hue_from_pos(e.position())
            self.update()
            self.hue_picked.emit(self.color())

    def mouseReleaseEvent(self, e):
        if self._drag:
            self._drag = False
            self.hue_committed.emit(self.color())


class CustomizeOverlay(QWidget):
    """Floating overlay — change assistant name, user name, UI colour and voice."""

    saved = pyqtSignal(str, str, str, str)   # assistant_name, user_name, ui_color, voice
    _OW, _OH = 400, 588

    def __init__(self, assistant_name="JARVIS", user_name="",
                 ui_color=DEFAULT_UI_COLOR, voice="", parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            CustomizeOverlay {{
                background: rgba(0, 6, 10, 245);
                border: 1px solid {C.BORDER_B};
                border-radius: 6px;
            }}
        """)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 18, 24, 18)
        lay.setSpacing(8)

        def _lbl(txt, fs=9, bold=False, color=C.PRI, align=Qt.AlignmentFlag.AlignCenter):
            w = QLabel(txt); w.setAlignment(align)
            w.setFont(hud_font(fs,
                            QFont.Weight.Bold if bold else QFont.Weight.Normal))
            w.setStyleSheet(f"color: {color}; background: transparent;")
            return w

        _fs = (f"QLineEdit {{ background: #000d12; color: {C.TEXT}; "
               f"border: 1px solid {C.BORDER}; border-radius: 3px; padding: 4px 8px; }}"
               f"QLineEdit:focus {{ border: 1px solid {C.PRI}; }}")

        lay.addWidget(_lbl("⚙  CUSTOMISE ASSISTANT", 12, True))
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER}; margin: 2px 0;")
        lay.addWidget(sep)

        lay.addWidget(_lbl("ASSISTANT NAME", 8, color=C.TEXT_DIM,
                            align=Qt.AlignmentFlag.AlignLeft))
        self._name_input = QLineEdit(assistant_name)
        self._name_input.setFont(hud_font(10))
        self._name_input.setFixedHeight(32)
        self._name_input.setStyleSheet(_fs)
        lay.addWidget(self._name_input)

        lay.addSpacing(4)
        lay.addWidget(_lbl("YOUR NAME  (leave blank for default sir / efendim)", 8,
                            color=C.TEXT_DIM, align=Qt.AlignmentFlag.AlignLeft))
        self._user_input = QLineEdit(user_name)
        self._user_input.setPlaceholderText("e.g.  Tony   (leave blank for auto)")
        self._user_input.setFont(hud_font(10))
        self._user_input.setFixedHeight(32)
        self._user_input.setStyleSheet(_fs)
        lay.addWidget(self._user_input)

        # ── Assistant voice — Gemini prebuilt voices ─────────────────────────
        # Names are language-neutral proper nouns, so the row reads the same in
        # every locale. Selecting one and applying rebuilds the Live session.
        from memory.config_manager import AVAILABLE_VOICES, DEFAULT_VOICE
        lay.addSpacing(4)
        lay.addWidget(_lbl("ASSISTANT VOICE", 8, color=C.TEXT_DIM,
                            align=Qt.AlignmentFlag.AlignLeft))
        self._sel_voice   = (voice or DEFAULT_VOICE)
        if self._sel_voice not in AVAILABLE_VOICES:
            self._sel_voice = DEFAULT_VOICE
        self._voice_btns: dict[str, QPushButton] = {}
        voice_row = QHBoxLayout(); voice_row.setSpacing(4)
        for _v in AVAILABLE_VOICES:
            b = QPushButton(_v)
            b.setCheckable(True)
            b.setFixedHeight(28)
            b.setFont(hud_font(8, QFont.Weight.Bold))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, name=_v: self._on_voice_pick(name))
            self._voice_btns[_v] = b
            voice_row.addWidget(b)
        lay.addLayout(voice_row)
        self._refresh_voice_btns()

        # ── UI colour — colour wheel ─────────────────────────────────────────
        lay.addSpacing(4)
        clr_hdr = QHBoxLayout()
        clr_hdr.addWidget(_lbl("UI COLOUR  —  drag the handle", 8,
                               color=C.TEXT_DIM, align=Qt.AlignmentFlag.AlignLeft))
        clr_hdr.addStretch()
        df_btn = QPushButton("DEFAULT")
        df_btn.setFixedSize(64, 20)
        df_btn.setFont(hud_font(7, QFont.Weight.Bold))
        df_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        df_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 3px;
            }}
            QPushButton:hover {{ color: {C.TEXT}; border-color: {C.BORDER_B}; }}
        """)
        df_btn.clicked.connect(lambda: self._set_color(DEFAULT_UI_COLOR))
        clr_hdr.addWidget(df_btn)
        lay.addLayout(clr_hdr)

        self._initial_color = (ui_color or DEFAULT_UI_COLOR).strip().lower()
        self._sel_color     = self._initial_color
        self.on_preview     = None   # callable(hex) — live preview; MainWindow wires it

        self._wheel = HueWheel(self._sel_color)
        wheel_row = QHBoxLayout()
        wheel_row.addStretch(); wheel_row.addWidget(self._wheel); wheel_row.addStretch()
        lay.addLayout(wheel_row)
        self._wheel.hue_picked.connect(self._on_wheel_pick)
        self._wheel.hue_committed.connect(self._on_wheel_commit)

        self._hex_input = QLineEdit(self._sel_color)
        self._hex_input.setPlaceholderText("#00d4ff   (custom hex colour)")
        self._hex_input.setFont(hud_font(10))
        self._hex_input.setFixedHeight(28)
        self._hex_input.setStyleSheet(_fs)
        self._hex_input.textEdited.connect(self._on_hex_edited)
        lay.addWidget(self._hex_input)

        lay.addSpacing(6)
        btn_row = QHBoxLayout(); btn_row.setSpacing(8)

        save_btn = QPushButton("▸  APPLY CHANGES")
        save_btn.setFixedHeight(34)
        save_btn.setFont(hud_font(9, QFont.Weight.Bold))
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.PRI};
                border: 1px solid {C.PRI_DIM}; border-radius: 3px;
            }}
            QPushButton:hover {{ background: {C.PRI_GHO}; border: 1px solid {C.PRI}; }}
        """)
        save_btn.clicked.connect(self._save)
        btn_row.addWidget(save_btn)

        cancel_btn = QPushButton("CANCEL")
        cancel_btn.setFixedHeight(34)
        cancel_btn.setFont(hud_font(9))
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 3px;
            }}
            QPushButton:hover {{ color: {C.TEXT}; border-color: {C.BORDER_B}; }}
        """)
        cancel_btn.clicked.connect(self._cancel)
        btn_row.addWidget(cancel_btn)
        lay.addLayout(btn_row)

    # ── voice selection ──────────────────────────────────────────────────────
    def _on_voice_pick(self, name: str):
        self._sel_voice = name
        self._refresh_voice_btns()

    def _refresh_voice_btns(self):
        """Highlight the selected voice pill; dim the rest."""
        for name, b in self._voice_btns.items():
            on = (name == self._sel_voice)
            b.setChecked(on)
            if on:
                b.setStyleSheet(f"""
                    QPushButton {{ background: {C.PRI_GHO}; color: {C.PRI};
                        border: 1px solid {C.PRI}; border-radius: 3px; }}
                """)
            else:
                b.setStyleSheet(f"""
                    QPushButton {{ background: transparent; color: {C.TEXT_MED};
                        border: 1px solid {C.BORDER}; border-radius: 3px; }}
                    QPushButton:hover {{ color: {C.TEXT}; border-color: {C.BORDER_B}; }}
                """)

    # ── colour flow ──────────────────────────────────────────────────────────
    def _set_color(self, hx: str, update_wheel: bool = True, preview: bool = True):
        """Updates the selected colour; hex box + wheel stay in sync, theme is live-previewed."""
        self._sel_color = hx.strip().lower()
        self._hex_input.blockSignals(True)
        self._hex_input.setText(self._sel_color)
        self._hex_input.blockSignals(False)
        if update_wheel:
            self._wheel.set_color(self._sel_color)
        if preview and self.on_preview:
            self.on_preview(self._sel_color)

    def _on_wheel_pick(self, hx: str):
        # While dragging: update the hex box, don't apply the theme yet
        self._sel_color = hx
        self._hex_input.blockSignals(True)
        self._hex_input.setText(hx)
        self._hex_input.blockSignals(False)

    def _on_wheel_commit(self, hx: str):
        # Handle released → live-preview the whole interface
        self._set_color(hx, update_wheel=False)

    def _on_hex_edited(self, text: str):
        t = text.strip().lower()
        if t.startswith("#") and len(t) == 7:
            try:
                int(t[1:], 16)
            except ValueError:
                return
            self._set_color(t, update_wheel=True, preview=True)

    def _cancel(self):
        # If a preview was applied, revert to the colour from launch
        if self.on_preview and self._sel_color != self._initial_color:
            self.on_preview(self._initial_color)
        self.hide()

    def _save(self):
        name = self._name_input.text().strip() or "JARVIS"
        user = self._user_input.text().strip()
        self.saved.emit(name, user, self._sel_color or DEFAULT_UI_COLOR, self._sel_voice)
        self.hide()


class PluginManagerOverlay(QWidget):
    """Floating overlay — lists discovered plugins with per-plugin ON/OFF toggles."""

    _OW = 420

    def __init__(self, plugins: list[dict], parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            PluginManagerOverlay {{
                background: rgba(0, 6, 10, 245);
                border: 1px solid {C.BORDER_B};
                border-radius: 6px;
            }}
        """)
        self.setFixedWidth(self._OW)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(6)

        hdr = QLabel("🧩  PLUGIN MANAGER")
        hdr.setFont(hud_font(12, QFont.Weight.Bold))
        hdr.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        lay.addWidget(hdr)
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER}; margin: 2px 0;")
        lay.addWidget(sep)

        if not plugins:
            empty = QLabel("No plugins found in /plugins.")
            empty.setFont(hud_font(8))
            empty.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
            lay.addWidget(empty)

        for p in plugins:
            lay.addLayout(self._build_row(p))

        lay.addSpacing(4)
        close_btn = QPushButton("CLOSE")
        close_btn.setFixedHeight(30)
        close_btn.setFont(hud_font(9))
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 3px;
            }}
            QPushButton:hover {{ color: {C.TEXT}; border-color: {C.BORDER_B}; }}
        """)
        close_btn.clicked.connect(self.hide)
        lay.addWidget(close_btn)
        self.adjustSize()

    def _build_row(self, p: dict) -> QHBoxLayout:
        row = QHBoxLayout(); row.setSpacing(6)

        label_text = p["name"] if p["valid"] else f"{p['name']}  (⚠ {p['file']})"
        lbl = QLabel(label_text)
        lbl.setFont(hud_font(8))
        lbl.setStyleSheet(f"color: {C.TEXT if p['valid'] else C.TEXT_DIM}; background: transparent;")
        lbl.setToolTip(p["description"] if p["valid"] else p["error"])
        lbl.setWordWrap(False)
        row.addWidget(lbl, stretch=1)

        btn = QPushButton()
        btn.setFixedSize(72, 24)
        btn.setFont(hud_font(7, QFont.Weight.Bold))
        if not p["valid"]:
            btn.setText("BROKEN")
            btn.setEnabled(False)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent; color: {C.TEXT_DIM};
                    border: 1px solid {C.BORDER}; border-radius: 3px;
                }}
            """)
        else:
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self._style_toggle(btn, p["enabled"])
            btn.clicked.connect(lambda _, name=p["name"], b=btn: self._toggle(name, b))
        row.addWidget(btn)
        return row

    def _style_toggle(self, btn: QPushButton, enabled: bool):
        if enabled:
            btn.setText("ON")
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: #001a08; color: {C.GREEN};
                    border: 1px solid {C.GREEN_D}; border-radius: 3px;
                }}
                QPushButton:hover {{ background: #002010; }}
            """)
        else:
            btn.setText("OFF")
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent; color: {C.TEXT_DIM};
                    border: 1px solid {C.BORDER}; border-radius: 3px;
                }}
                QPushButton:hover {{ color: {C.TEXT}; border-color: {C.BORDER_B}; }}
            """)

    def _toggle(self, name: str, btn: QPushButton):
        from memory.config_manager import get_plugin_enabled, save_plugin_enabled
        new_val = not get_plugin_enabled(name)
        save_plugin_enabled(name, new_val)
        self._style_toggle(btn, new_val)


class _HudOverlay(QWidget):
    """Base for the floating panels placed by hand over the HUD.

    They are children of the central widget but sit in no layout, so Qt never
    invalidates the region they occupy when they hide or shrink: the HUD keeps
    painting around them and their last frame stays on screen as a ghost. Any
    overlay positioned with _centre_overlay needs this."""

    def hideEvent(self, e):
        p = self.parentWidget()
        if p is not None:
            # Repaint exactly what we were covering, before we stop covering it.
            p.update(self.geometry())
        super().hideEvent(e)

    def closeEvent(self, e):
        p = self.parentWidget()
        if p is not None:
            p.update(self.geometry())
        super().closeEvent(e)


class ConfirmBanner(_HudOverlay):
    """The gate in front of an action that cannot be taken back.

    The old confirmation was a tool parameter the model filled in itself, which
    means it confirmed its own shutdown requests. This is the interface asking,
    and the answer travels from a human finger to core/confirm.py without the
    model in the loop. Nothing blocks while it is up: the assistant keeps
    talking, so this costs no latency — unlike the old gate, which spent two
    tool round trips on every power command."""

    answered = pyqtSignal(bool)
    _OW = 430

    def __init__(self, title: str, detail: str, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            ConfirmBanner {{
                background: rgba(14, 3, 0, 250);
                border: 1px solid {C.ACC};
                border-radius: 6px;
            }}
        """)
        self.setFixedWidth(self._OW)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(8)

        hdr = QLabel("⚠  CONFIRM")
        hdr.setFont(hud_font(11, QFont.Weight.Bold))
        hdr.setStyleSheet(f"color: {C.ACC}; background: transparent;")
        lay.addWidget(hdr)

        ttl = QLabel(title)
        ttl.setWordWrap(True)
        ttl.setFont(hud_font(10, QFont.Weight.Bold))
        ttl.setStyleSheet(f"color: {C.TEXT}; background: transparent;")
        lay.addWidget(ttl)

        if detail:
            dtl = QLabel(detail)
            dtl.setWordWrap(True)
            dtl.setFont(hud_font(8))
            dtl.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
            lay.addWidget(dtl)

        row = QHBoxLayout(); row.setSpacing(8)

        yes = QPushButton("▸  CONFIRM")
        yes.setFixedHeight(32)
        yes.setFont(hud_font(9, QFont.Weight.Bold))
        yes.setCursor(Qt.CursorShape.PointingHandCursor)
        yes.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {C.ACC};
                border: 1px solid {C.ACC}; border-radius: 3px; }}
            QPushButton:hover {{ background: rgba(255,107,0,40); }}
        """)
        yes.clicked.connect(lambda: self.answered.emit(True))
        row.addWidget(yes)

        no = QPushButton("CANCEL")
        no.setFixedHeight(32)
        no.setFont(hud_font(9))
        no.setCursor(Qt.CursorShape.PointingHandCursor)
        no.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 3px; }}
            QPushButton:hover {{ color: {C.TEXT}; border-color: {C.BORDER_B}; }}
        """)
        no.clicked.connect(lambda: self.answered.emit(False))
        row.addWidget(no)
        lay.addLayout(row)

        # Default focus on CANCEL: if someone hits Enter without reading, the
        # safe answer wins.
        no.setDefault(True)
        no.setFocus()


class AudioDeviceOverlay(_HudOverlay):
    """Choose which microphone JARVIS listens to and which speakers it uses.

    Both audio streams used to open with no `device=` at all, so they always
    took the OS default — which on Windows moves by itself the moment a headset
    is plugged in. 'JARVIS can't hear me' is usually 'JARVIS is listening to the
    webcam'."""

    picked = pyqtSignal()      # emitted after Apply, when something changed

    # THESE EXIST BECAUSE QTimer.singleShot FROM A WORKER THREAD NEVER FIRES.
    #
    # The first version posted results back with `QTimer.singleShot(0, fn)` from
    # inside the audio thread. A QTimer belongs to the thread that creates it,
    # and that thread has no event loop — so the timer was created, never ran,
    # and the panel sat on "Speak now…" for ever while the recording finished
    # silently behind it. Reported as "I saw no sign of anything at all", which
    # is precisely what it looked like.
    #
    # A signal is the thread-safe way across: Qt queues it onto the receiving
    # object's thread, which for a widget is the GUI thread. Both carry only
    # plain values — never a widget — because the widgets belong to the GUI
    # thread and the worker must not touch them even to pass them along.
    _level_seen = pyqtSignal(int)          # 0-100, while recording
    _test_result = pyqtSignal(str, bool)   # sentence, was it good

    _OW = 460

    def __init__(self, parent=None):
        super().__init__(parent)
        from core.audio_devices import list_devices, DEFAULT_LABEL
        from memory.config_manager import get_input_device, get_output_device

        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            AudioDeviceOverlay {{
                background: rgba(0, 6, 10, 245);
                border: 1px solid {C.BORDER_B};
                border-radius: 6px;
            }}
        """)
        self.setFixedWidth(self._OW)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(6)

        hdr = QLabel("🎧  AUDIO DEVICES")
        hdr.setFont(hud_font(12, QFont.Weight.Bold))
        hdr.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        lay.addWidget(hdr)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER}; margin: 2px 0;")
        lay.addWidget(sep)

        _combo_css = (
            f"QComboBox {{ background: #000d12; color: {C.TEXT}; "
            f"border: 1px solid {C.BORDER}; border-radius: 3px; padding: 4px 8px; }}"
            f"QComboBox:hover {{ border-color: {C.BORDER_B}; }}"
            f"QComboBox QAbstractItemView {{ background: #000d12; color: {C.TEXT}; "
            f"selection-background-color: {C.PRI_GHO}; border: 1px solid {C.BORDER}; }}"
        )

        _test_css = (
            f"QPushButton {{ background: transparent; color: {C.TEXT_DIM}; "
            f"border: 1px solid {C.BORDER}; border-radius: 3px; }}"
            f"QPushButton:hover {{ color: {C.PRI}; border-color: {C.PRI_DIM}; }}"
            f"QPushButton:disabled {{ color: {C.BORDER}; }}"
        )

        def _row(label: str, kind: str, current: str) -> QComboBox:
            cap = QLabel(label)
            cap.setFont(hud_font(8))
            cap.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
            lay.addWidget(cap)

            box = QComboBox()
            box.setFont(hud_font(9))
            box.setFixedHeight(30)
            box.setStyleSheet(_combo_css)
            # The list is served from a cache warmed on a background thread at
            # startup, so opening this panel never blocks the Qt thread on the
            # host audio API.
            box.addItem(DEFAULT_LABEL, "")
            for name in list_devices(kind):
                box.addItem(name, name)
            idx = box.findData(current) if current else 0
            box.setCurrentIndex(idx if idx >= 0 else 0)
            if current and idx < 0:
                # Saved device is not plugged in right now. Show it rather than
                # silently resetting the user's choice to default.
                box.addItem(f"{current}  (not connected)", current)
                box.setCurrentIndex(box.count() - 1)

            # THE ONE CHECK THE STARTUP PROBE CANNOT MAKE.
            #
            # core/audio_devices decides at launch whether a device opens and
            # whether it moves audio, and it does that with silence. A muted
            # microphone, a level slider at zero and a privacy shutter all pass
            # every one of those tests and still deliver a flat line — the only
            # thing that separates them from a working microphone is a person
            # speaking into it.
            #
            # So the button is here, beside the dropdown, in the panel somebody
            # opens when JARVIS cannot hear them. It replaces a loose
            # `ses_testi.py` in the project root that nobody would ever find.
            btn_row = QHBoxLayout(); btn_row.setSpacing(6)
            btn_row.addWidget(box, 1)
            test = QPushButton("TEST")
            test.setFixedSize(64, 30)
            test.setFont(hud_font(8, QFont.Weight.Bold))
            test.setCursor(Qt.CursorShape.PointingHandCursor)
            test.setStyleSheet(_test_css)
            btn_row.addWidget(test)
            lay.addLayout(btn_row)

            # A meter, because a static label is indistinguishable from a hang.
            # Three seconds of "Speak now" with nothing moving was reported as
            # "I saw no sign of anything" — correctly, since nothing on screen
            # responded to the user's voice.
            meter = QProgressBar()
            meter.setRange(0, 100)
            meter.setValue(0)
            meter.setTextVisible(False)
            meter.setFixedHeight(6)
            meter.setStyleSheet(
                f"QProgressBar {{ background: #000d12; border: 1px solid {C.BORDER}; "
                f"border-radius: 3px; }}"
                f"QProgressBar::chunk {{ background: {C.PRI}; border-radius: 2px; }}")
            meter.hide()
            lay.addWidget(meter)

            result = QLabel("")
            result.setWordWrap(True)
            result.setFont(hud_font(7))
            result.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
            lay.addWidget(result)

            test.clicked.connect(
                lambda _=False, k=kind, b=box, t=test, r=result, m=meter:
                    self._run_test(k, b, t, r, m))
            return box

        # Which row is being tested right now. One at a time — the button is
        # disabled for the duration — so a single slot is enough, and it keeps
        # widgets off the signal payload.
        self._active = None                # (button, label, meter)
        self._level_seen.connect(self._on_level)
        self._test_result.connect(self._on_result)

        self._in_box  = _row("MICROPHONE — what JARVIS hears you with",
                             "input", get_input_device())
        lay.addSpacing(4)
        self._out_box = _row("SPEAKERS — what JARVIS talks through",
                             "output", get_output_device())

        # ── Output volume, beside the output device ──────────────────────────
        #
        # Choosing "Realtek(R) Audio" here and finding it far too quiet used to
        # mean leaving this panel, opening the system sound settings, finding
        # the same endpoint again and moving a slider there. The volume belongs
        # next to the device it applies to.
        _vol_now = None
        try:
            from core.audio_devices import get_output_volume
            # The SELECTED output, not the system default. Somebody puts the
            # assistant on their speakers and keeps everything else in their
            # headphones; a slider labelled with one device that moves the
            # other is worse than no slider at all.
            _vol_now = get_output_volume(self._out_box.currentData() or "")
        except Exception:
            pass

        if _vol_now is not None:
            vcap = QLabel("OUTPUT VOLUME")
            vcap.setFont(hud_font(8))
            vcap.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
            lay.addSpacing(4)
            lay.addWidget(vcap)

            vrow = QHBoxLayout(); vrow.setSpacing(8)
            self._vol = QSlider(Qt.Orientation.Horizontal)
            self._vol.setRange(0, 100)
            self._vol.setValue(int(_vol_now))
            self._vol.setFixedHeight(22)
            self._vol.setStyleSheet(
                f"QSlider::groove:horizontal {{ background: #000d12; height: 4px; "
                f"border: 1px solid {C.BORDER}; border-radius: 2px; }}"
                f"QSlider::sub-page:horizontal {{ background: {C.PRI_DIM}; "
                f"border-radius: 2px; }}"
                f"QSlider::handle:horizontal {{ background: {C.PRI}; width: 10px; "
                f"margin: -5px 0; border-radius: 5px; }}")
            self._vol_lbl = QLabel(f"{int(_vol_now)}%")
            self._vol_lbl.setFont(hud_font(8))
            self._vol_lbl.setFixedWidth(40)
            self._vol_lbl.setStyleSheet(f"color: {C.TEXT}; background: transparent;")
            vrow.addWidget(self._vol, 1)
            vrow.addWidget(self._vol_lbl)
            lay.addLayout(vrow)

            # valueChanged fires for every pixel of a drag, and each one is a
            # COM call into the audio endpoint. sliderReleased fires once, when
            # the user has decided — the label still follows the handle so the
            # number moves while they drag.
            self._vol.valueChanged.connect(
                lambda v: self._vol_lbl.setText(f"{v}%"))
            self._vol.sliderReleased.connect(self._apply_volume)
            self._out_box.currentIndexChanged.connect(
                lambda _i: self._volume_follows_device())

        note = QLabel("Applying reconnects the session. Your conversation is kept.")
        note.setWordWrap(True)
        note.setFont(hud_font(7))
        note.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        lay.addSpacing(6)
        lay.addWidget(note)

        row = QHBoxLayout(); row.setSpacing(8)
        ok = QPushButton("▸  APPLY")
        ok.setFixedHeight(32)
        ok.setFont(hud_font(9, QFont.Weight.Bold))
        ok.setCursor(Qt.CursorShape.PointingHandCursor)
        ok.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {C.PRI};
                border: 1px solid {C.PRI_DIM}; border-radius: 3px; }}
            QPushButton:hover {{ background: {C.PRI_GHO}; border-color: {C.PRI}; }}
        """)
        ok.clicked.connect(self._apply)
        row.addWidget(ok)

        cancel = QPushButton("CLOSE")
        cancel.setFixedHeight(32)
        cancel.setFont(hud_font(9))
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 3px; }}
            QPushButton:hover {{ color: {C.TEXT}; border-color: {C.BORDER_B}; }}
        """)
        cancel.clicked.connect(self.hide)
        row.addWidget(cancel)
        lay.addLayout(row)

    def _apply_volume(self):
        """Set the system output volume from the slider, off the Qt thread.

        The Windows path goes through COM, which can block for tens of
        milliseconds; that is not long enough to see but is long enough to
        stutter a drag, and there is no reason to make the interface wait for
        it.
        """
        import threading
        value = self._vol.value()
        device = self._out_box.currentData() or ""

        def _work():
            from core import audio_devices
            if not audio_devices.set_output_volume(value, device):
                print(f"[Audio] the volume of '{device}' could not be set "
                      f"to {value}%")

        threading.Thread(target=_work, daemon=True, name="audio-volume").start()

    def _volume_follows_device(self):
        """Re-read the slider when the chosen output changes.

        Each device keeps its own level, so leaving the handle where it was
        would show the previous device's volume against the new device's name —
        and the next drag would then jump it there.
        """
        if not hasattr(self, "_vol"):
            return
        try:
            from core.audio_devices import get_output_volume
            now = get_output_volume(self._out_box.currentData() or "")
        except Exception:
            now = None
        if now is None:
            return
        self._vol.blockSignals(True)
        self._vol.setValue(int(now))
        self._vol.blockSignals(False)
        self._vol_lbl.setText(f"{int(now)}%")

    def _run_test(self, kind, box, button, label, meter=None):
        """Record or play for real, off the Qt thread.

        Both calls block for seconds — recording waits for the user to speak,
        the tone waits for itself — and doing that on the Qt thread freezes the
        HUD, which is the mistake Mark LV already paid for once with a 2.1
        second wake-word import in the settings drawer.

        Results come back by signal, not by timer. See the note on
        `_level_seen` above for why that distinction is the whole feature.
        """
        import threading

        name = box.currentData() or ""
        self._active = (button, label, meter)
        button.setEnabled(False)
        label.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        label.setText("Speak now…" if kind == "input" else "Playing a tone…")
        if meter is not None and kind == "input":
            meter.setValue(0)
            meter.show()

        def _work():
            from core import audio_devices
            try:
                if kind == "input":
                    res = audio_devices.measure_input(
                        name,
                        on_level=lambda f: self._level_seen.emit(int(f * 100)))
                    text = f"peak {res['peak']}  —  {res['verdict']}"
                else:
                    res = audio_devices.play_tone(name)
                    text = res["verdict"]
                good = bool(res.get("ok", False))
            except Exception as e:
                text, good = f"The test itself failed: {e}", False
            self._test_result.emit(text, good)

        threading.Thread(target=_work, daemon=True, name=f"audio-test-{kind}").start()

    def _on_level(self, value: int):
        """A live level, already on the GUI thread thanks to the signal."""
        if self._active and self._active[2] is not None:
            self._active[2].setValue(max(0, min(100, value)))

    def _on_result(self, text: str, good: bool):
        if not self._active:
            return
        button, label, meter = self._active
        self._active = None
        button.setEnabled(True)
        if meter is not None:
            meter.setValue(0)
            meter.hide()
        label.setStyleSheet(
            f"color: {C.PRI if good else C.TEXT_DIM}; background: transparent;")
        label.setText(text)

    def _apply(self):
        from memory.config_manager import (
            get_input_device, get_output_device,
            save_input_device, save_output_device,
        )
        new_in  = self._in_box.currentData()  or ""
        new_out = self._out_box.currentData() or ""
        changed = (new_in != get_input_device()) or (new_out != get_output_device())
        save_input_device(new_in)
        save_output_device(new_out)
        self.hide()
        # Only rebuild the session if something actually moved — a no-op Apply
        # should not cost a reconnect.
        if changed:
            self.picked.emit()


class MemoryOverlay(_HudOverlay):
    """Everything JARVIS has stored about you, and when it learned it.

    Memory used to be a 2200-character store that deleted its oldest entries
    when full and mentioned it only on stdout. The cap is gone; this panel is
    the other half of that change — a memory you cannot inspect is a memory you
    cannot trust, and 'delete' has to be something the person can do."""

    _OW = 520

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            MemoryOverlay {{
                background: rgba(0, 6, 10, 246);
                border: 1px solid {C.BORDER_B};
                border-radius: 6px;
            }}
        """)
        self.setFixedWidth(self._OW)

        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(20, 16, 20, 16)
        self._lay.setSpacing(5)
        self._rebuild()

    def _clear_layout(self):
        """Take every item out of the layout and detach it from the widget tree
        in this call.

        deleteLater() on its own is not enough: it queues destruction for the
        next event-loop pass, and until then the old rows are still children of
        this widget and still paint — which is what drew half of the previous
        panel over the new one. setParent(None) removes them from the tree now;
        deleteLater() then frees them safely."""
        while self._lay.count():
            item = self._lay.takeAt(0)
            w = item.widget()
            if w is not None:
                # hide() stops it painting in this frame; deleteLater() frees it
                # safely afterwards. setParent(None) would also stop the paint,
                # but it turns the widget into a top-level window for the moment
                # between the two calls, which is not something to leave lying
                # around inside a click handler.
                w.hide()
                w.deleteLater()
                continue
            sub = item.layout()
            if sub is not None:
                while sub.count():
                    si = sub.takeAt(0)
                    sw = si.widget()
                    if sw is not None:
                        sw.hide()
                        sw.deleteLater()
                sub.deleteLater()

    def _settle(self, before):
        """Size the panel to its content, re-centre it, and repaint what the old
        size covered.

        The re-size has to happen here rather than at the end of _rebuild
        because Qt has not polished the freshly-created children at that point,
        so the size hint it would read is the empty-layout one. Measured: a
        first adjustSize() returned 32 px for a panel whose content needed 155,
        and a second call — after the same widgets had been through the event
        loop — returned 155. So this runs twice: once now, once on the next
        turn, from _rebuild.

        The re-centre and the repaint are needed because the overlay is placed
        by hand and is in no layout: shrinking it leaves it off-centre and
        leaves its former pixels on screen, since nothing tells the parent that
        region changed. The repaint has to cover the union of the old and new
        rectangles."""
        self._lay.invalidate()
        self._lay.activate()
        self.updateGeometry()
        self.adjustSize()

        p = self.parentWidget()
        if p is None:
            self.update()
            return
        self.move(max(0, (p.width()  - self.width())  // 2),
                  max(0, (p.height() - self.height()) // 2))
        p.update(before.united(self.geometry()))
        self.update()

    def _rebuild(self):
        before = self.geometry()
        self._clear_layout()

        from memory.memory_manager import all_entries_for_ui

        hdr = QLabel("🧠  WHAT JARVIS REMEMBERS")
        hdr.setFont(hud_font(12, QFont.Weight.Bold))
        hdr.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        self._lay.addWidget(hdr)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER}; margin: 2px 0;")
        self._lay.addWidget(sep)

        rows = all_entries_for_ui()

        cap = QLabel(f"{len(rows)} stored facts — newest first. "
                     f"Nothing here is sent anywhere; it lives in "
                     f"memory/long_term.json on this machine.")
        cap.setWordWrap(True)
        cap.setFont(hud_font(7))
        cap.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        self._lay.addWidget(cap)

        if not rows:
            empty = QLabel("Nothing stored yet.")
            empty.setFont(hud_font(9))
            empty.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
            self._lay.addWidget(empty)
        else:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFixedHeight(min(420, 34 * len(rows) + 10))
            scroll.setStyleSheet(
                f"QScrollArea {{ border: 1px solid {C.BORDER}; border-radius: 3px; "
                f"background: transparent; }}"
            )
            inner = QWidget()
            ilay  = QVBoxLayout(inner)
            ilay.setContentsMargins(6, 6, 6, 6)
            ilay.setSpacing(3)

            for r in rows:
                line = QHBoxLayout(); line.setSpacing(6)
                txt = QLabel(f"<b>{r['key'].replace('_', ' ')}</b> "
                             f"<span style='color:{C.TEXT_MED}'>— {r['value']}</span>")
                txt.setWordWrap(True)
                txt.setFont(hud_font(8))
                txt.setStyleSheet(f"color: {C.TEXT}; background: transparent;")
                line.addWidget(txt, 1)

                meta = QLabel(f"{r['category'][:4]} · {r['updated'] or '—'}")
                meta.setFont(hud_font(7))
                meta.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
                line.addWidget(meta)

                rm = QPushButton("✕")
                rm.setFixedSize(20, 20)
                rm.setFont(hud_font(8, QFont.Weight.Bold))
                rm.setCursor(Qt.CursorShape.PointingHandCursor)
                rm.setToolTip("Forget this")
                rm.setStyleSheet(f"""
                    QPushButton {{ background: transparent; color: {C.TEXT_DIM};
                        border: 1px solid {C.BORDER}; border-radius: 3px; }}
                    QPushButton:hover {{ color: {C.RED}; border-color: {C.RED}; }}
                """)
                rm.clicked.connect(
                    lambda _=False, c=r["category"], k=r["key"]: self._forget(c, k))
                line.addWidget(rm)

                holder = QWidget()
                holder.setLayout(line)
                ilay.addWidget(holder)

            ilay.addStretch()
            scroll.setWidget(inner)
            self._lay.addWidget(scroll)

        close = QPushButton("CLOSE")
        close.setFixedHeight(30)
        close.setFont(hud_font(9))
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 3px; }}
            QPushButton:hover {{ color: {C.TEXT}; border-color: {C.BORDER_B}; }}
        """)
        close.clicked.connect(self.hide)
        self._lay.addWidget(close)

        self._settle(before)
        # …and again once Qt has polished the new children, because the size
        # hint is not final until then. Harmless when the first pass already
        # got it right: _settle is idempotent.
        QTimer.singleShot(0, lambda g=before: self._settle(g))

    def _forget(self, category: str, key: str):
        from memory.memory_manager import forget
        forget(key, category)
        # Rebuild on the NEXT event-loop turn, not inside this click handler.
        # The rebuild destroys the very ✕ button that emitted this signal, and
        # Qt is entitled to touch the sender after a slot returns; tearing it
        # down mid-emission is how a widget ends up half-alive on screen.
        QTimer.singleShot(0, self._rebuild)


class _ScrollSafeCombo(QComboBox):
    """A dropdown that does not change when you scroll past it.

    Qt's default is that a combo box under the pointer swallows the wheel and
    steps its own value with it. Inside a scrolling panel that is not a
    convenience, it is a trap: scrolling down the list of settings silently
    changes whichever ones the pointer crossed on the way, and nothing on screen
    says so. It was reported as "selections move around when I scroll", and it
    is the same bug every Qt settings panel has until somebody fixes it.

    The wheel is only accepted when the box has been clicked into. Otherwise the
    event is passed up, which is what makes the panel scroll instead.
    """

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        # StrongFocus so it can still be tabbed to and used from the keyboard;
        # the wheel is gated on having focus, not on being focusable.
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, e):
        if self.hasFocus():
            super().wheelEvent(e)
        else:
            e.ignore()




class ClipboardPanel(QWidget):
    """Floating panel shown when text is copied — offers quick Jarvis actions."""

    action_requested = pyqtSignal(str)
    _W, _H = 326, 112

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            ClipboardPanel {{
                background: rgba(0, 8, 14, 248);
                border: 1px solid {C.BORDER_B};
                border-radius: 6px;
            }}
        """)
        self.setFixedWidth(self._W)
        self._clip_text = ""

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 7)
        lay.setSpacing(4)

        hdr = QHBoxLayout(); hdr.setSpacing(4)
        icon_lbl = QLabel("◈  CLIPBOARD DETECTED")
        icon_lbl.setFont(hud_font(7, QFont.Weight.Bold))
        icon_lbl.setStyleSheet(f"color: {C.ACC2}; background: transparent;")
        hdr.addWidget(icon_lbl); hdr.addStretch()
        x_btn = QPushButton("✕")
        x_btn.setFixedSize(16, 16)
        x_btn.setFont(hud_font(8))
        x_btn.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent; border: none;")
        x_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        x_btn.clicked.connect(self.hide)
        hdr.addWidget(x_btn)
        lay.addLayout(hdr)

        self._preview = QLabel()
        self._preview.setFont(hud_font(8))
        self._preview.setStyleSheet(f"""
            color: {C.TEXT}; background: {C.PANEL2};
            border: 1px solid {C.BORDER}; border-radius: 3px; padding: 4px 6px;
        """)
        self._preview.setWordWrap(False)
        self._preview.setFixedHeight(28)
        lay.addWidget(self._preview)

        btn_row = QHBoxLayout(); btn_row.setSpacing(4)
        _bs = (f"QPushButton {{ background: {C.PANEL2}; color: {C.TEXT_MED}; "
               f"border: 1px solid {C.BORDER}; border-radius: 2px; }}"
               f"QPushButton:hover {{ color: {C.PRI}; border-color: {C.BORDER_B}; }}")
        for label, cmd_fmt in [
            ("TRANSLATE", "Translate this text to English: {text}"),
            ("SUMMARISE", "Summarise this: {text}"),
            ("EXPLAIN",   "Explain this: {text}"),
            ("FIX",       "Fix grammar and spelling: {text}"),
        ]:
            b = QPushButton(label)
            b.setFixedHeight(22)
            b.setFont(hud_font(7, QFont.Weight.Bold))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(_bs)
            b.clicked.connect(lambda _, c=cmd_fmt: self._trigger(c))
            btn_row.addWidget(b)
        lay.addLayout(btn_row)

        self._dismiss_timer = QTimer(self)
        self._dismiss_timer.setSingleShot(True)
        self._dismiss_timer.timeout.connect(self.hide)
        self.hide()

    def _trigger(self, cmd_fmt: str):
        if self._clip_text:
            self.action_requested.emit(cmd_fmt.format(text=self._clip_text[:800]))
        self.hide()

    def show_clipboard(self, text: str):
        self._clip_text = text
        preview = text[:58].replace('\n', ' ')
        if len(text) > 58:
            preview += "…"
        self._preview.setText(f'"{preview}"')
        self.show(); self.raise_()
        self._dismiss_timer.start(8000)


class PluginSettingsOverlay(QWidget):
    """Floating overlay — renders per-plugin settings forms.

    Fully generic: it iterates the settings schemas a plugin declared via its
    PLUGIN_SETTINGS constant (delivered by PluginRegistry.settings_schemas) and
    builds a form for each. It knows NOTHING about any specific plugin, so the
    core stays clean and plugins remain pure drop-in — install a plugin that
    declares fields (e.g. the 3D-printer suite) and its section appears here;
    install none and this panel simply says there's nothing to configure.

    One documented exception: a section may declare "widget": "create_repo"
    (the 🔗 CONNECTORS plugin does) and the overlay builds the "Create
    Repository" box at the end of that section — name / description / private
    / Create button / clickable result. The box calls core/connectors.py on a
    worker thread and never touches widgets off the Qt thread.
    """

    _test_done = pyqtSignal(str, bool, str)   # namespace, ok, message
    _repo_done = pyqtSignal(bool, str)        # create-repo finished: ok, message
    _OW = 460

    def __init__(self, sections: list[dict], parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            PluginSettingsOverlay {{
                background: rgba(0, 6, 10, 245);
                border: 1px solid {C.BORDER_B};
                border-radius: 6px;
            }}
        """)
        self._sections = sections or []
        self._widgets: dict[tuple, object] = {}    # (namespace, key) -> input widget
        self._types:   dict[tuple, str]    = {}     # (namespace, key) -> field type
        self._status_labels: dict[str, QLabel] = {} # namespace -> status QLabel
        self._test_done.connect(self._on_test_done)
        # Create-Repository box widgets (only built when a section declares
        # "widget": "create_repo"); None until then.
        self._repo_name: object = None
        self._repo_desc: object = None
        self._repo_private: object = None
        self._repo_create_btn: object = None
        self._repo_result: object = None
        self._repo_done.connect(self._on_repo_done)

        self._fs = (f"QLineEdit {{ background: #000d12; color: {C.TEXT}; "
                    f"border: 1px solid {C.BORDER}; border-radius: 3px; padding: 4px 8px; }}"
                    f"QLineEdit:focus {{ border: 1px solid {C.PRI}; }}")

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 16, 22, 16)
        root.setSpacing(8)

        root.addWidget(self._lbl("⚙  PLUGIN SETTINGS", 12, True))
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER}; margin: 2px 0;")
        root.addWidget(sep)

        if not self._sections:
            root.addWidget(self._lbl(
                "No configurable plugins are installed.\nDrop a plugin that needs "
                "settings (like the 3D-printer suite) into the plugins folder and "
                "it will show up here.", 9, color=C.TEXT_DIM))
        else:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setStyleSheet("QScrollArea { background: transparent; }")
            inner = QWidget()
            inner.setStyleSheet("background: transparent;")
            form = QVBoxLayout(inner)
            form.setContentsMargins(0, 0, 6, 0)
            form.setSpacing(6)
            for sec in self._sections:
                self._build_section(form, sec)
            form.addStretch(1)
            scroll.setWidget(inner)
            root.addWidget(scroll, 1)

        # ── bottom buttons ───────────────────────────────────────────────────
        btn_row = QHBoxLayout(); btn_row.setSpacing(8)
        if self._sections:
            save_btn = QPushButton("▸  SAVE")
            save_btn.setFixedHeight(34)
            save_btn.setFont(hud_font(9, QFont.Weight.Bold))
            save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            save_btn.setStyleSheet(f"""
                QPushButton {{ background: transparent; color: {C.PRI};
                    border: 1px solid {C.PRI_DIM}; border-radius: 3px; }}
                QPushButton:hover {{ background: {C.PRI_GHO}; border: 1px solid {C.PRI}; }}
            """)
            save_btn.clicked.connect(self._save_all)
            btn_row.addWidget(save_btn)

        close_btn = QPushButton("CLOSE")
        close_btn.setFixedHeight(34)
        close_btn.setFont(hud_font(9))
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 3px; }}
            QPushButton:hover {{ color: {C.TEXT}; border-color: {C.BORDER_B}; }}
        """)
        close_btn.clicked.connect(self.hide)
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)

    # ── helpers ───────────────────────────────────────────────────────────────
    def _lbl(self, txt, fs=9, bold=False, color=C.PRI,
             align=Qt.AlignmentFlag.AlignLeft):
        w = QLabel(txt); w.setAlignment(align); w.setWordWrap(True)
        w.setFont(hud_font(fs,
                        QFont.Weight.Bold if bold else QFont.Weight.Normal))
        w.setStyleSheet(f"color: {color}; background: transparent;")
        return w

    def _build_section(self, form: QVBoxLayout, sec: dict):
        ns     = sec.get("namespace") or sec.get("plugin") or "plugin"
        title  = sec.get("title") or ns
        fields = sec.get("fields") or []
        values = sec.get("values") or {}

        form.addSpacing(4)
        form.addWidget(self._lbl(title, 10, True, C.PRI))

        for field in fields:
            if not isinstance(field, dict) or not field.get("key"):
                continue
            key   = field["key"]
            ftype = (field.get("type") or "text").lower()
            label = field.get("label") or key
            default = field.get("default")
            stored  = values.get(key, default)

            form.addWidget(self._lbl(label.upper(), 8, color=C.TEXT_DIM))

            if ftype == "choice":
                w = QComboBox()
                w.addItems([str(o) for o in field.get("options", [])])
                w.setFont(hud_font(9))
                w.setFixedHeight(30)
                w.setStyleSheet(
                    f"QComboBox {{ background: #000d12; color: {C.TEXT}; "
                    f"border: 1px solid {C.BORDER}; border-radius: 3px; padding: 2px 8px; }}"
                    f"QComboBox QAbstractItemView {{ background: #000d12; color: {C.TEXT}; "
                    f"selection-background-color: {C.PRI_GHO}; }}")
                if stored is not None:
                    w.setCurrentText(str(stored))
            elif ftype == "toggle":
                w = QPushButton()
                w.setCheckable(True)
                w.setChecked(bool(stored))
                w.setFixedHeight(28)
                w.setFont(hud_font(8, QFont.Weight.Bold))
                w.setCursor(Qt.CursorShape.PointingHandCursor)
                self._style_toggle(w)
                w.toggled.connect(lambda _=False, b=w: self._style_toggle(b))
            else:  # text / password
                w = QLineEdit("" if stored is None else str(stored))
                w.setFont(hud_font(10))
                w.setFixedHeight(30)
                w.setStyleSheet(self._fs)
                if field.get("placeholder"):
                    w.setPlaceholderText(str(field["placeholder"]))
                if ftype == "password":
                    w.setEchoMode(QLineEdit.EchoMode.Password)

            self._widgets[(ns, key)] = w
            self._types[(ns, key)]   = ftype
            form.addWidget(w)

        # optional test/connect action button + status line
        action = sec.get("action")
        if isinstance(action, dict) and callable(action.get("run")):
            form.addSpacing(2)
            ab = QPushButton(str(action.get("label") or "TEST"))
            ab.setFixedHeight(30)
            ab.setFont(hud_font(8, QFont.Weight.Bold))
            ab.setCursor(Qt.CursorShape.PointingHandCursor)
            ab.setStyleSheet(f"""
                QPushButton {{ background: #00091a; color: {C.PRI};
                    border: 1px solid {C.PRI_DIM}; border-radius: 3px; }}
                QPushButton:hover {{ background: {C.PRI_GHO}; border-color: {C.PRI}; }}
            """)
            ab.clicked.connect(lambda _=False, n=ns: self._run_action(n))
            form.addWidget(ab)

        status = self._lbl("", 8, color=C.TEXT_DIM)
        self._status_labels[ns] = status
        form.addWidget(status)

        # Optional extra box declared by the section, e.g. "create_repo"
        # (🔗 CONNECTORS): rendered at the end of this section.
        if sec.get("widget") == "create_repo":
            self._build_create_repo_box(form)

        line = QFrame(); line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"color: {C.BORDER}; margin: 4px 0;")
        form.addWidget(line)

    def _style_toggle(self, btn: QPushButton):
        on = btn.isChecked()
        btn.setText("ON" if on else "OFF")
        if on:
            btn.setStyleSheet(f"QPushButton {{ background: {C.PRI_GHO}; color: {C.PRI}; "
                              f"border: 1px solid {C.PRI}; border-radius: 3px; }}")
        else:
            btn.setStyleSheet(f"QPushButton {{ background: transparent; color: {C.TEXT_MED}; "
                              f"border: 1px solid {C.BORDER}; border-radius: 3px; }}")

    # ── data ──────────────────────────────────────────────────────────────────
    def _gather(self, ns: str) -> dict:
        out = {}
        for (n, key), w in self._widgets.items():
            if n != ns:
                continue
            t = self._types.get((n, key), "text")
            if t == "choice":
                out[key] = w.currentText()
            elif t == "toggle":
                out[key] = w.isChecked()
            else:
                out[key] = w.text().strip()
        return out

    def _save_ns(self, ns: str):
        from memory.config_manager import save_plugin_config
        save_plugin_config(ns, self._gather(ns))

    def _save_all(self):
        for sec in self._sections:
            ns = sec.get("namespace") or sec.get("plugin")
            if ns:
                self._save_ns(ns)
                lbl = self._status_labels.get(ns)
                if lbl:
                    lbl.setText("Saved ✓")
                    lbl.setStyleSheet(f"color: {C.PRI}; background: transparent;")

    def _run_action(self, ns: str):
        sec = next((s for s in self._sections
                    if (s.get("namespace") or s.get("plugin")) == ns), None)
        if not sec:
            return
        run_fn = (sec.get("action") or {}).get("run")
        if not callable(run_fn):
            return
        self._save_ns(ns)                 # persist what the user typed before testing
        values = self._gather(ns)
        lbl = self._status_labels.get(ns)
        if lbl:
            lbl.setText("Testing…")
            lbl.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")

        def worker():
            try:
                res = run_fn(values)
                if isinstance(res, tuple) and len(res) == 2:
                    ok, msg = bool(res[0]), str(res[1])
                else:
                    ok, msg = bool(res), str(res)
            except Exception as e:
                ok, msg = False, str(e)
            self._test_done.emit(ns, ok, msg)

        threading.Thread(target=worker, daemon=True).start()

    def _on_test_done(self, ns: str, ok: bool, msg: str):
        lbl = self._status_labels.get(ns)
        if not lbl:
            return
        lbl.setText(msg)
        color = C.PRI if ok else "#ff6b6b"
        lbl.setStyleSheet(f"color: {color}; background: transparent;")

    # ── Create Repository box (GitHub token diye repo banano) ───────────────
    def _build_create_repo_box(self, form: QVBoxLayout):
        """'📦 CREATE REPOSITORY' box at the end of the 🔗 CONNECTORS section.

        Fields: repository name, description (optional), Private checkbox,
        Create button, result line (new repo URL is clickable). The GitHub
        token is read from the SAVED config only — never typed here, never
        shown, never logged. The API call runs on a worker thread; the result
        comes back through _repo_done so only the Qt thread touches widgets.
        """
        form.addSpacing(6)
        form.addWidget(self._lbl("📦  CREATE REPOSITORY — GitHub", 10, True, C.PRI))
        form.addWidget(self._lbl(
            "GitHub token diye notun repo banao. Token-ta oporer GitHub token "
            "field-e bosiye SAVE korte hobe — token kokhono ekhane likho na.",
            8, color=C.TEXT_DIM))

        form.addWidget(self._lbl("REPOSITORY NAME", 8, color=C.TEXT_DIM))
        self._repo_name = QLineEdit()
        self._repo_name.setFont(hud_font(10))
        self._repo_name.setFixedHeight(30)
        self._repo_name.setStyleSheet(self._fs)
        self._repo_name.setPlaceholderText("e.g. my-new-repo")
        form.addWidget(self._repo_name)

        form.addWidget(self._lbl("DESCRIPTION (OPTIONAL)", 8, color=C.TEXT_DIM))
        self._repo_desc = QLineEdit()
        self._repo_desc.setFont(hud_font(10))
        self._repo_desc.setFixedHeight(30)
        self._repo_desc.setStyleSheet(self._fs)
        self._repo_desc.setPlaceholderText("ki korbe ei repo-ta")
        form.addWidget(self._repo_desc)

        self._repo_private = QCheckBox("🔒  Private repo")
        self._repo_private.setFont(hud_font(9))
        self._repo_private.setCursor(Qt.CursorShape.PointingHandCursor)
        self._repo_private.setStyleSheet(
            f"QCheckBox {{ color: {C.TEXT_MED}; background: transparent; }}"
            f"QCheckBox::indicator {{ border: 1px solid {C.BORDER}; "
            f"border-radius: 2px; width: 14px; height: 14px; }}"
            f"QCheckBox::indicator:checked {{ background: {C.PRI}; "
            f"border-color: {C.PRI}; }}")
        form.addWidget(self._repo_private)

        create_btn = QPushButton("▸  CREATE REPOSITORY")
        create_btn.setFixedHeight(30)
        create_btn.setFont(hud_font(8, QFont.Weight.Bold))
        create_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        create_btn.setStyleSheet(f"""
            QPushButton {{ background: #00091a; color: {C.PRI};
                border: 1px solid {C.PRI_DIM}; border-radius: 3px; }}
            QPushButton:hover {{ background: {C.PRI_GHO}; border-color: {C.PRI}; }}
            QPushButton:disabled {{ color: {C.BORDER}; border-color: {C.BORDER}; }}
        """)
        create_btn.clicked.connect(self._on_create_repo)
        form.addWidget(create_btn)
        self._repo_create_btn = create_btn

        self._repo_result = QLabel("")
        self._repo_result.setWordWrap(True)
        self._repo_result.setFont(hud_font(8))
        self._repo_result.setOpenExternalLinks(True)
        self._repo_result.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextBrowserInteraction)
        self._repo_result.setStyleSheet(
            f"color: {C.TEXT_DIM}; background: transparent;")
        form.addWidget(self._repo_result)

    def _set_repo_result(self, ok: bool, msg: str, color: str | None = None):
        if color is None:
            color = C.PRI if ok else "#ff6b6b"
        self._repo_result.setText(msg)
        self._repo_result.setStyleSheet(
            f"color: {color}; background: transparent;")

    def _on_create_repo(self):
        name = (self._repo_name.text() or "").strip()
        if not name:
            self._set_repo_result(False, "Repo-r naam dao.")
            return
        try:
            from core import connectors as _conn
            token = _conn.get_token("github_token")
        except Exception:
            token = ""
        if not token:
            # The token field sits in this same overlay, just above the box —
            # the user only has to paste it there and hit SAVE.
            self._set_repo_result(False,
                "GitHub token set kora nei — opore GitHub token field-e token "
                "bosao, SAVE chapho, tarpor ekhane Create chapho.")
            return
        desc = (self._repo_desc.text() or "").strip()
        private = bool(self._repo_private.isChecked())
        self._repo_create_btn.setEnabled(False)
        self._set_repo_result(False, "Creating…", color=C.TEXT_DIM)
        threading.Thread(target=self._create_repo_worker,
                         args=(name, desc, private), daemon=True).start()

    def _create_repo_worker(self, name: str, desc: str, private: bool):
        try:
            from core import connectors as _conn
            res = _conn.github_create_repo(None, name, private, desc)
            ok = isinstance(res, str) and res.startswith("✅")
        except Exception as e:
            ok, res = False, f"Repo banate parlam na: {e}"
        self._repo_done.emit(ok, res)

    def _on_repo_done(self, ok: bool, msg: str):
        self._repo_create_btn.setEnabled(True)
        if ok:
            import re as _re
            m = _re.search(r"https://github\.com/\S+", msg)
            url = m.group(0) if m else ""
            if url:
                self._set_repo_result(
                    True, f"✅ Repo banalam: <a href=\"{url}\">{url}</a>")
            else:
                self._set_repo_result(True, msg)
            self._repo_name.clear()
            self._repo_desc.clear()
            self._repo_private.setChecked(False)
        else:
            self._set_repo_result(False, msg)


class RemoteKeyOverlay(QWidget):
    """Floating overlay — QR code for instant phone pairing + manual key fallback."""

    closed = pyqtSignal()

    _OW, _OH = 400, 465

    def __init__(self, url: str, key: str, auto_login_url: str = "",
                 manual_url: str = "", expiry_secs: int = 600, parent=None,
                 bind_error: str = ""):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            RemoteKeyOverlay {{
                background: rgba(0, 4, 12, 0.95);
                border: 1px solid {C.BORDER_B};
                border-radius: 14px;
            }}
        """)
        self._expiry          = time.time() + expiry_secs
        self._on_new_key      = None
        self._auto_login_url  = auto_login_url
        self._manual_url      = manual_url or url

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 16, 24, 16)
        lay.setSpacing(5)

        def _lbl(txt, fs=9, bold=False, color=C.PRI,
                 align=Qt.AlignmentFlag.AlignCenter):
            w = QLabel(txt)
            w.setAlignment(align)
            w.setFont(hud_font(fs,
                            QFont.Weight.Bold if bold else QFont.Weight.Normal))
            w.setStyleSheet(f"color: {color}; background: transparent;")
            w.setWordWrap(True)
            return w

        lay.addWidget(_lbl("◈  REMOTE ACCESS", 12, True))
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER}; margin: 1px 0;")
        lay.addWidget(sep)

        # ── QR code ───────────────────────────────────────────────────────────
        self._qr_label = QLabel()
        self._qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._qr_label.setFixedSize(176, 176)
        self._qr_label.setStyleSheet(
            "background: white; border-radius: 10px; padding: 4px;"
        )
        qr_row = QHBoxLayout()
        qr_row.addStretch()
        qr_row.addWidget(self._qr_label)
        qr_row.addStretch()
        lay.addLayout(qr_row)

        self._update_qr(auto_login_url)

        lay.addWidget(_lbl("Scan with phone camera to connect instantly", 8, color=C.TEXT_DIM))

        # THE ONE FAILURE THAT LOOKS LIKE THE SERVER BEING OFF.
        #
        # Windows writes a BLOCK rule for an executable when its "Allow access?"
        # prompt is dismissed, and a block overrides every allow rule there is —
        # including the port rule this app carefully creates. The phone then
        # reports "refused to connect" while the server is running perfectly.
        #
        # It is invisible from the HUD, which is where the person scanning the
        # QR code is looking, and it is per-EXECUTABLE: the shortcut runs
        # pythonw.exe while an editor runs python.exe, so it can block one launch
        # method and not the other on the same machine. That difference is
        # unguessable without being told, so it is said here.
        # Whatever is stopping this from working, say it HERE — beside the QR
        # code, where the person about to scan it is looking. A dashboard that
        # cannot be reached and does not explain why is the single most
        # frustrating failure this app has.
        if bind_error:
            lay.addWidget(_lbl("⚠  " + bind_error, 8, color="#f4b942"))

        try:
            from dashboard.server import blocking_firewall_rules
            _blocked = blocking_firewall_rules()
        except Exception:
            _blocked = []
        if _blocked:
            warn = _lbl(
                "⚠  Windows is blocking incoming connections to this copy of "
                "Python, so your phone cannot reach this page. Restart JARVIS "
                "and accept the Windows prompt, or remove the rules named "
                + ", ".join(sorted({n for n, _ in _blocked}))
                + " under Windows Defender Firewall → Inbound Rules.",
                8, color="#f4b942")
            lay.addWidget(warn)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"color: {C.BORDER}; margin: 1px 0;")
        lay.addWidget(sep2)

        lay.addWidget(_lbl("Or enter manually:", 7, color=C.TEXT_DIM,
                           align=Qt.AlignmentFlag.AlignLeft))

        self._url_lbl = QLabel(self._manual_url)
        self._url_lbl.setFont(hud_font(8))
        self._url_lbl.setStyleSheet(f"color: {C.PRI_DIM}; background: transparent;")
        self._url_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._url_lbl.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self._url_lbl)

        self._key_lbl = QLabel(key)
        self._key_lbl.setFont(hud_font(28, QFont.Weight.Bold))
        self._key_lbl.setStyleSheet(f"""
            color: {C.ACC};
            background: {C.PANEL2};
            border: 1px solid {C.BORDER_B};
            border-radius: 8px;
            padding: 6px 4px;
            letter-spacing: 10px;
        """)
        self._key_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._key_lbl)

        self._timer_lbl = QLabel()
        self._timer_lbl.setFont(hud_font(8))
        self._timer_lbl.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
        self._timer_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._timer_lbl)

        btn_row = QHBoxLayout(); btn_row.setSpacing(8)
        new_btn = QPushButton("NEW KEY")
        new_btn.setFixedHeight(32)
        new_btn.setFont(hud_font(8, QFont.Weight.Bold))
        new_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        new_btn.setStyleSheet(f"""
            QPushButton {{
                background: {C.PANEL}; color: {C.PRI};
                border: 1px solid {C.PRI_DIM}; border-radius: 5px;
            }}
            QPushButton:hover {{ background: {C.PRI_GHO}; border: 1px solid {C.PRI}; }}
        """)
        new_btn.clicked.connect(self._refresh_key)
        btn_row.addWidget(new_btn)

        close_btn = QPushButton("DISMISS")
        close_btn.setFixedHeight(32)
        close_btn.setFont(hud_font(8, QFont.Weight.Bold))
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 5px;
            }}
            QPushButton:hover {{ color: {C.TEXT}; border: 1px solid {C.BORDER_B}; }}
        """)
        close_btn.clicked.connect(self._do_close)
        btn_row.addWidget(close_btn)
        lay.addLayout(btn_row)

        self._ctimer = QTimer(self)
        self._ctimer.timeout.connect(self._tick)
        self._ctimer.start(1000)
        self._tick()

    def set_new_key_callback(self, fn) -> None:
        self._on_new_key = fn

    def _update_qr(self, url: str) -> None:
        if not url:
            self._qr_label.setText("—")
            return
        try:
            import qrcode as _qrmod
            from io import BytesIO
            qr = _qrmod.QRCode(
                box_size=5, border=2,
                error_correction=_qrmod.constants.ERROR_CORRECT_M,
            )
            qr.add_data(url)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            buf = BytesIO()
            img.save(buf, format="PNG")
            px = QPixmap()
            px.loadFromData(buf.getvalue())
            self._qr_label.setPixmap(
                px.scaled(170, 170,
                          Qt.AspectRatioMode.KeepAspectRatio,
                          Qt.TransformationMode.SmoothTransformation)
            )
        except ImportError:
            self._qr_label.setText("pip install\nqrcode[pil]")
            self._qr_label.setFont(hud_font(8))
            self._qr_label.setStyleSheet(
                "color: #888; background: white; border-radius: 10px; padding: 4px;"
            )
        except Exception:
            self._qr_label.setText(url[:28])
            self._qr_label.setFont(hud_font(7))
            self._qr_label.setStyleSheet(
                f"color: {C.PRI}; background: white; border-radius: 10px; padding: 4px;"
            )

    def _tick(self):
        remaining = max(0, int(self._expiry - time.time()))
        m, s = divmod(remaining, 60)
        self._timer_lbl.setText(f"Key expires in  {m:02d}:{s:02d}")
        if remaining == 0:
            self._do_close()

    def mark_connected(self) -> None:
        """Call from any thread when a phone successfully connects."""
        self._ctimer.stop()
        self._key_lbl.setText("CONNECTED")
        self._key_lbl.setStyleSheet(f"""
            color: {C.GREEN};
            background: rgba(34,197,94,0.08);
            border: 2px solid rgba(34,197,94,0.4);
            border-radius: 8px;
            padding: 6px 4px;
            letter-spacing: 4px;
        """)
        self._qr_label.setText("✓")
        self._qr_label.setFont(hud_font(54, QFont.Weight.Bold))
        self._qr_label.setStyleSheet(
            "color: #00ff88; background: #001a0d; border-radius: 10px;"
        )
        self._timer_lbl.setText("Phone connected — JARVIS ready")
        self._timer_lbl.setStyleSheet(f"color: {C.GREEN}; background: transparent;")

    def _refresh_key(self):
        if self._on_new_key:
            result = self._on_new_key()
            if result:
                url    = result[0]
                key    = result[1]
                auto   = result[2] if len(result) >= 3 else ""
                manual = result[3] if len(result) >= 4 else url
                self._manual_url     = manual or url
                self._url_lbl.setText(self._manual_url)
                self._key_lbl.setText(key)
                self._auto_login_url = auto
                self._update_qr(auto or url)
                self._expiry = time.time() + 600
                self._key_lbl.setStyleSheet(f"""
                    color: {C.ACC};
                    background: {C.PANEL2};
                    border: 1px solid {C.BORDER_B};
                    border-radius: 8px;
                    padding: 6px 4px;
                    letter-spacing: 10px;
                """)
                self._timer_lbl.setStyleSheet(
                    f"color: {C.TEXT_MED}; background: transparent;"
                )
                self._ctimer.start(1000)
                self._tick()

    def _do_close(self):
        self._ctimer.stop()
        self.hide()
        self.closed.emit()




def _local_ip() -> str:
    """Best LAN-facing IPv4 address (same trick as dashboard/server.py).

    No traffic is sent — a UDP connect only asks the OS which interface a
    packet would leave by. Used so the overlay can show the PC's IP + the
    dashboard URL the phone browser opens.
    """
    for probe in ("8.8.8.8", "1.1.1.1", "192.168.1.1"):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0.5)
            s.connect((probe, 80))
            ip = s.getsockname()[0]
            s.close()
            if not ip.startswith("127."):
                return ip
        except Exception:
            pass
    try:
        ip = socket.gethostbyname(socket.gethostname())
        if not ip.startswith("127."):
            return ip
    except Exception:
        pass
    return ""


class JarvisLinkOverlay(QWidget):
    """Floating overlay — QR code that pairs THIS PC with the phone Jarvis app.

    The QR carries ``jarvis-pair://<mark_id>/<code>[/<secret>]`` for the Jarvis
    backend relay (core/jarvis_link.py), so the phone can reach this machine
    from any internet — not just the local Wi-Fi the dashboard QR uses.

    Everything the overlay shows is read on the Qt thread (a 1 s QTimer polls
    the link object); the link's own threads never touch a widget.
    """

    closed = pyqtSignal()
    _render_done = pyqtSignal(str)   # worker thread -> Qt thread: deploy result

    _OW, _OH = 440, 730

    def __init__(self, link, parent=None):
        super().__init__(parent)
        self._link = link
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            JarvisLinkOverlay {{
                background: rgba(0, 4, 12, 0.95);
                border: 1px solid {C.BORDER_B};
                border-radius: 14px;
            }}
        """)
        self._shown_code = ""
        self._marked = False
        # Last Render deploy message + when it was set: _tick (1 s) would
        # otherwise overwrite the deploy result with the pairing status at
        # once, so it keeps showing this instead for a while (see _tick).
        self._render_msg = ""
        self._render_msg_at = 0.0
        self._render_done.connect(self._on_render_done)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 16, 24, 16)
        lay.setSpacing(5)

        def _lbl(txt, fs=9, bold=False, color=C.PRI,
                 align=Qt.AlignmentFlag.AlignCenter):
            w = QLabel(txt)
            w.setAlignment(align)
            w.setFont(hud_font(fs,
                            QFont.Weight.Bold if bold else QFont.Weight.Normal))
            w.setStyleSheet(f"color: {color}; background: transparent;")
            w.setWordWrap(True)
            return w

        lay.addWidget(_lbl("📱  JARVIS LINK", 12, True))
        lay.addWidget(_lbl("Phone Jarvis app diye scan koro — ei PC phone "
                           "theke cholbe, jekono internet-e", 8, color=C.TEXT_DIM))
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER}; margin: 1px 0;")
        lay.addWidget(sep)

        self._qr_label = QLabel()
        self._qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._qr_label.setFixedSize(220, 220)
        self._qr_label.setStyleSheet(
            "background: white; border-radius: 10px; padding: 4px;"
        )
        qr_row = QHBoxLayout()
        qr_row.addStretch()
        qr_row.addWidget(self._qr_label)
        qr_row.addStretch()
        lay.addLayout(qr_row)

        self._code_lbl = QLabel("…")
        self._code_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._code_lbl.setFont(hud_font(28, QFont.Weight.Bold))
        self._code_lbl.setStyleSheet(f"""
            color: {C.ACC};
            background: {C.PANEL2};
            border: 1px solid {C.BORDER_B};
            border-radius: 8px;
            padding: 6px 4px;
            letter-spacing: 10px;
        """)
        lay.addWidget(self._code_lbl)

        # Mark ID — QR scan na cholle manual pairing-er jonno lagbe.
        self._mark_lbl = _lbl("Mark ID: …", 8, color=C.TEXT_DIM)
        lay.addWidget(self._mark_lbl)

        # PC IP + dashboard URL — user jante chailo "code diye ki kore connect
        # korbo": QR-er pasapasi IP + dashboard + step gulo ekhanei dekhabe.
        self._ip = ""
        self._ip_lbl = _lbl("🌐 PC IP: …", 9, True, color=C.PRI)
        lay.addWidget(self._ip_lbl)
        self._dash_lbl = _lbl("🖥️ Dashboard: …", 8, color=C.TEXT_DIM)
        lay.addWidget(self._dash_lbl)
        # Render URL + browser token (Chrome extension) — read from
        # plugin_config["jarvis_link"] in _tick; the Render line stays hidden
        # until a render_url is actually configured, to save space.
        self._render_lbl = _lbl("", 8, color=C.TEXT_DIM)
        lay.addWidget(self._render_lbl)
        self._browser_lbl = _lbl(
            "🔑 Browser token: dashboard start hole toiri hobe",
            7, color=C.TEXT_DIM)
        lay.addWidget(self._browser_lbl)
        lay.addWidget(_lbl(
            "কানেক্ট করবে যেভাবে:\n"
            "1️⃣ Phone-e Jarvis kholo → Settings → PC Pairing → Scan PC QR\n"
            "2️⃣ QR na cholle: oi screen-er niche Mark ID + Code bosiye Pair koro\n"
            "3️⃣ Dashboard: phone browser-e oporer link-ta kholo (certificate warning asle Proceed/Advanced → Continue)",
            8, color=C.TEXT_DIM))

        self._status_lbl = _lbl("QR asche…", 8, color=C.TEXT_DIM)
        lay.addWidget(self._status_lbl)

        self._e2e_lbl = _lbl("", 8, color=C.GREEN)
        lay.addWidget(self._e2e_lbl)

        btn_row = QHBoxLayout()
        new_btn = QPushButton("🔄  NOTUN CODE")
        new_btn.setStyleSheet(
            f"color: {C.PRI}; background: {C.PANEL2}; border-radius: 8px; padding: 6px;")
        new_btn.clicked.connect(self._on_new_code)
        btn_row.addWidget(new_btn)
        unpair_btn = QPushButton("🔓  UNPAIR")
        unpair_btn.setStyleSheet(
            f"color: #f4b942; background: {C.PANEL2}; border-radius: 8px; padding: 6px;")
        unpair_btn.clicked.connect(self._on_unpair)
        btn_row.addWidget(unpair_btn)
        self._render_btn = QPushButton("🌐  CONNECT RENDER")
        self._render_btn.setStyleSheet(
            f"color: {C.PRI}; background: {C.PANEL2}; border-radius: 8px; padding: 6px;")
        self._render_btn.clicked.connect(self._on_render_deploy)
        btn_row.addWidget(self._render_btn)
        lay.addLayout(btn_row)

        close_btn = QPushButton("✕  BONDHO KORO")
        close_btn.setStyleSheet(
            f"color: {C.TEXT_DIM}; background: transparent; padding: 4px;")
        close_btn.clicked.connect(self._do_close)
        lay.addWidget(close_btn)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)
        self._tick()

    # ── QR ───────────────────────────────────────────────────────────────────

    def _update_qr(self) -> None:
        try:
            img = self._link.qr_image(280)
        except Exception:
            img = None
        if img is None:
            self._qr_label.setText("QR aseni\npip install qrcode")
            self._qr_label.setFont(hud_font(8))
            self._qr_label.setStyleSheet(
                "color: #888; background: white; border-radius: 10px; padding: 4px;")
            return
        try:
            from io import BytesIO
            buf = BytesIO()
            img.save(buf, format="PNG")
            px = QPixmap()
            px.loadFromData(buf.getvalue())
            self._qr_label.setPixmap(
                px.scaled(214, 214,
                          Qt.AspectRatioMode.KeepAspectRatio,
                          Qt.TransformationMode.SmoothTransformation))
        except Exception:
            self._qr_label.setText("QR")
            self._qr_label.setFont(hud_font(7))

    def _on_new_code(self) -> None:
        try:
            self._link.refresh_code()
        except Exception:
            pass
        self._marked = False
        self._render_msg = ""
        self._tick()

    def _on_unpair(self) -> None:
        try:
            self._link.unpair()
        except Exception:
            pass
        self._marked = False
        self._render_msg = ""
        self._tick()

    # ── 🌐 Render deploy (one click) ─────────────────────────────────────────

    def _resolve_render_deploy(self):
        """The deploy function main.py defines (render_deploy_sync) — the
        exact code the render_deploy tool runs. main.py runs as __main__, so
        take it from there first; only if this module is ever imported some
        other way fall back to importing main (which would load a second copy
        of the module — never in the real app). Returns None when unreachable."""
        try:
            mod = sys.modules.get("__main__")
            fn = getattr(mod, "render_deploy_sync", None) if mod is not None else None
            if callable(fn):
                return fn
        except Exception:
            pass
        try:
            from main import render_deploy_sync as _fn
            return _fn
        except Exception:
            return None

    def _on_render_deploy(self) -> None:
        """Qt thread: disable the button, show "deploy hochhe", and run the
        deploy on a worker thread — the Qt thread never blocks on the network.
        The result comes back through the _render_done signal (Qt thread)."""
        self._render_btn.setEnabled(False)
        self._render_msg = "⏳ Deploy hochhe…"
        self._render_msg_at = time.monotonic()
        self._status_lbl.setText(self._render_msg)

        def _work():
            fn = self._resolve_render_deploy()
            if fn is None:
                res = ("Render deploy trigger pelam na — main.py theke "
                       "Mark chalao, tarpor abar try koro.")
            else:
                try:
                    res = fn()
                except Exception as e:
                    res = f"Render deploy-e error: {e}"
            self._render_done.emit(str(res))

        threading.Thread(target=_work, daemon=True,
                         name="mark-render-deploy").start()

    def _on_render_done(self, res: str) -> None:
        """Qt thread (via _render_done): show the result, re-enable the
        button. Success also refreshes the Render URL label from config."""
        try:
            self._render_btn.setEnabled(True)
        except Exception:
            pass
        if res.startswith("⏳ Render deploy shuru holo"):
            try:
                from memory.config_manager import get_plugin_config, load_api_keys
                _jl = get_plugin_config("jarvis_link")
                _url = str(_jl.get("render_url") or
                           load_api_keys().get("render_url") or "").strip()
            except Exception:
                _url = ""
            if _url:
                self._render_msg = "✅ Deploy shuru holo — " + _url
            else:
                self._render_msg = ("✅ Deploy shuru holo — Render URL set korle "
                                    "ekhane dekhabe (Plugin Settings > 📱 JARVIS LINK "
                                    "> Render URL).")
        else:
            # Includes the no-key case, whose message already says exactly
            # where to add it (Plugin Settings > 🔗 CONNECTORS > Render API key).
            self._render_msg = res
        self._render_msg_at = time.monotonic()
        self._tick()  # re-reads the Render URL label + shows _render_msg

    # ── tick (Qt thread only) ────────────────────────────────────────────────

    def _tick(self) -> None:
        try:
            st = self._link.status_dict()
        except Exception:
            return
        code = st.get("pair_code", "") or ""
        if code and code != self._shown_code:
            self._shown_code = code
            self._update_qr()
        elif not code:
            self._shown_code = ""
        elif not st.get("paired") and self._qr_label.pixmap() is None and code:
            # QR age banate pareni (qrcode missing / transient fail) — proti
            # tick-e abar try koro, jate sudhu code dekha na jay.
            self._update_qr()
            self._qr_label.setText("QR\nasche…")
            self._qr_label.setFont(hud_font(8))
        self._code_lbl.setText(code if code else "------")
        self._mark_lbl.setText("Mark ID: " + str(st.get("mark_id", "") or "…"))
        # PC IP + dashboard URL — ekbar ber kore rakho; khali thakle abar try koro.
        if not self._ip:
            self._ip = _local_ip()
        if self._ip:
            self._ip_lbl.setText("🌐 PC IP: " + self._ip)
            self._dash_lbl.setText("🖥️ Dashboard: http://" + self._ip + ":8000")
        else:
            self._ip_lbl.setText("🌐 PC IP: pelam na — Wi-Fi/LAN check koro")
            self._dash_lbl.setText("🖥️ Dashboard: IP na pele khulbe na")
        # Render URL + browser token — config theke poro (Qt thread only);
        # config na thakle / porte na parle overlay jeno na vange.
        try:
            from memory.config_manager import get_plugin_config, load_api_keys
            _jl = get_plugin_config("jarvis_link")
            _render = str(_jl.get("render_url") or
                          load_api_keys().get("render_url") or "").strip()
            _btok = str(_jl.get("browser_token") or "").strip()
        except Exception:
            _render, _btok = "", ""
        if _render:
            self._render_lbl.setText("🌐 Render: " + _render)
            self._render_lbl.setVisible(True)
        else:
            self._render_lbl.setVisible(False)
        if _btok:
            self._browser_lbl.setText("🔑 Browser token: " + _btok)
        else:
            self._browser_lbl.setText(
                "🔑 Browser token: dashboard start hole toiri hobe")
        if st.get("paired"):
            if not self._marked:
                self._marked = True
                self.mark_connected()
            self._status_lbl.setText(
                "✅ Paired — phone: " + str(st.get("install_id", ""))[:8] + "…")
        else:
            self._status_lbl.setText(
                "Phone-e Jarvis khule Settings > PC Pairing > Scan PC QR")
        # A fresh deploy message outranks the pairing status, so the user
        # actually sees the deploy result instead of it vanishing on the
        # next 1 s tick; after 90 s the normal status comes back.
        if self._render_msg and (time.monotonic() - self._render_msg_at) < 90.0:
            self._status_lbl.setText(self._render_msg)
        elif self._render_msg:
            self._render_msg = ""
        self._e2e_lbl.setText(
            "🔒 E2E ON — command encrypted jachhe" if st.get("e2e")
            else "Plaintext — cryptography thakle E2E chalu hobe")

    def mark_connected(self) -> None:
        """Call from the Qt thread when pairing completes."""
        self._qr_label.setText("✓")
        self._qr_label.setFont(hud_font(54, QFont.Weight.Bold))
        self._qr_label.setStyleSheet(
            "color: #00ff88; background: #001a0d; border-radius: 10px;")
        self._status_lbl.setText("Phone connected — JARVIS ready")
        self._status_lbl.setStyleSheet(f"color: {C.GREEN}; background: transparent;")

    def _do_close(self) -> None:
        self._timer.stop()
        self.hide()
        self.closed.emit()


# ── 🔍 FEATURES registry adapter + 💬 ASK MUSE helper ───────────────────────
# The 13,700,000-feature registry (core/feature_registry.py) landed
# 2026-11-17 as 1,000,000 (Volume 1), grew to 3,000,000 the same day
# (Volume 2: numbers 1,000,001-3,000,000) and to 4,000,000 with Volume 3
# (numbers 3,000,001-4,000,000), then to 6,700,000 with Volume 4
# (numbers 4,000,001-4,700,000) and Volume 5 (numbers 4,700,001-6,700,000),
# and to 13,700,000 with Volume 6 (numbers 6,700,001-13,700,000;
# combinatorial resolve/search). The adapter below
# builds against its contract — resolve(number)->dict, search(query, limit)->
# list[dict], list_category(cidx, offset, limit)->list[dict],
# counts()->{total, WORKING, NEEDS-KEY, NEEDS-DEVICE, PLANNED},
# set_enabled(number, on), is_enabled(number). The old 20,000-feature JSON
# (data/features.json) was deleted 2026-11-17 and the _feat_records()
# fallback below is dead code (plugins/jarvis_features._load_registry no
# longer exists; it returns [], {} and is never reached while the resolver
# loads). Enable/disable state falls back to config
# plugin_config["features"]["disabled"] (a list of numbers) when the
# resolver has no set_enabled/is_enabled. Nothing here ever raises; every
# helper returns an empty/neutral value on failure. Coverage is always
# computed from the registry that actually loaded, so the counter reads
# the live total — never a hard-coded total.

_MAX_FEATURE_NUMBER = 13_700_000   # run-by-number accepts 1–13,700,000


def _feat_registry():
    """core.feature_registry when the sibling worker has delivered it."""
    try:
        import core.feature_registry as _fr  # noqa: F401
        return _fr
    except Exception:
        return None


def _feat_records():
    """(records, by_number) from the 20,000-feature JSON registry."""
    try:
        from plugins import jarvis_features as _jf
        return _jf._load_registry()
    except Exception:
        return [], {}


def _feat_normalise(rec):
    """One registry record -> the dict the HUD/dashboard render. Never raises."""
    try:
        rec = dict(rec or {})
        n = int(rec.get("number") or 0)
        out = {
            "number": n,
            "volume": int(rec.get("volume") or 1),
            "name": str(rec.get("name") or f"Feature #{n}"),
            "category": str(rec.get("category") or ""),
            "category_index": int(rec.get("category_index") or 0),
            "target": str(rec.get("target") or ""),
            "pattern": str(rec.get("pattern") or ""),
            "description": str(rec.get("description") or ""),
            "status": str(rec.get("status") or "PLANNED"),
            "tool": rec.get("tool"),
            "requires": str(rec.get("requires") or ""),
        }
        out["enabled"] = _feat_is_enabled(n)
        return out
    except Exception:
        return {"number": 0, "name": "?", "category": "", "category_index": 0,
                "target": "", "pattern": "", "description": "", "status": "PLANNED",
                "tool": None, "requires": "", "enabled": True}


def _feat_resolve(number):
    try:
        n = int(number)
    except (TypeError, ValueError):
        return None
    if n < 1 or n > _MAX_FEATURE_NUMBER:
        return None
    fr = _feat_registry()
    if fr is not None and hasattr(fr, "resolve"):
        try:
            rec = fr.resolve(n)
            # The resolver returns {"error": ...} (not None) on bad input
            # or a missing structure file — treat that as "not found".
            if isinstance(rec, dict) and rec.get("error"):
                return None
            return _feat_normalise(rec) if rec else None
        except Exception:
            pass
    _records, by_number = _feat_records()
    rec = by_number.get(n)
    return _feat_normalise(rec) if rec else None


def _feat_search(query, limit=20):
    """Token/phrase search over name+description+category+target+status."""
    try:
        limit = max(1, min(100, int(limit or 20)))
    except Exception:
        limit = 20
    q = str(query or "").strip().lower()
    if not q:
        # Empty query = browse from the top (the resolver's search
        # returns [] on an empty query by design).
        return _feat_first(limit)
    fr = _feat_registry()
    if fr is not None and hasattr(fr, "search"):
        try:
            return [_feat_normalise(r) for r in (fr.search(q, limit) or [])]
        except Exception:
            pass
    records, _by = _feat_records()
    import re as _re
    tokens = [t for t in _re.split(r"\s+", q) if t]
    scored = []
    for rec in records:
        text = " ".join([str(rec.get("name") or ""),
                         str(rec.get("description") or ""),
                         str(rec.get("category") or ""),
                         str(rec.get("target") or ""),
                         str(rec.get("status") or "")]).lower()
        hits = sum(1 for t in tokens if t in text)
        if not hits:
            continue
        scored.append((hits + (2 if q in text else 0), rec.get("number") or 0, rec))
    scored.sort(key=lambda s: (-s[0], s[1]))
    return [_feat_normalise(r) for _s, _n, r in scored[:limit]]


def _feat_list_category(cidx, offset=0, limit=20):
    try:
        cidx, offset, limit = int(cidx), max(0, int(offset or 0)), max(1, min(100, int(limit or 20)))
    except Exception:
        return []
    fr = _feat_registry()
    if fr is not None and hasattr(fr, "list_category"):
        try:
            return [_feat_normalise(r) for r in (fr.list_category(cidx, offset, limit) or [])]
        except Exception:
            pass
    records, _by = _feat_records()
    items = [r for r in records if r.get("category_index") == cidx]
    return [_feat_normalise(r) for r in items[offset:offset + limit]]


def _feat_first(limit=20):
    """First `limit` features by number — the default browse view."""
    try:
        limit = max(1, min(100, int(limit or 20)))
    except Exception:
        limit = 20
    out = []
    for n in range(1, limit + 1):
        rec = _feat_resolve(n)
        if rec:
            out.append(rec)
    return out


def _feat_categories():
    """[(index, name)] for all 100 categories, index order."""
    fr = _feat_registry()
    if fr is not None and hasattr(fr, "list_categories"):
        try:
            cats = [(int(c["index"]), str(c["name"]))
                    for c in (fr.list_categories() or [])]
            if cats:
                return cats
        except Exception:
            pass
    if fr is not None and hasattr(fr, "list_category"):
        # Fallback: probe the 100 known indices.
        cats = []
        for i in range(1, 101):
            try:
                rows = fr.list_category(i, 0, 1) or []
            except Exception:
                rows = []
            if rows:
                cats.append((i, str(rows[0].get("category") or f"Category {i}")))
        if cats:
            return cats
    records, _by = _feat_records()
    cats = {}
    for rec in records:
        try:
            cats[int(rec.get("category_index") or 0)] = str(rec.get("category") or "")
        except Exception:
            pass
    return [(i, cats[i]) for i in sorted(cats) if i]


def _feat_counts():
    """{total, WORKING, NEEDS-KEY, NEEDS-DEVICE, PLANNED} from the live registry."""
    fr = _feat_registry()
    if fr is not None and hasattr(fr, "counts"):
        try:
            c = dict(fr.counts() or {})
            return {"total": int(c.get("total") or 0),
                    "WORKING": int(c.get("WORKING") or 0),
                    "NEEDS-KEY": int(c.get("NEEDS-KEY") or 0),
                    "NEEDS-DEVICE": int(c.get("NEEDS-DEVICE") or 0),
                    "PLANNED": int(c.get("PLANNED") or 0)}
        except Exception:
            pass
    records, _by = _feat_records()
    out = {"total": len(records), "WORKING": 0, "NEEDS-KEY": 0,
           "NEEDS-DEVICE": 0, "PLANNED": 0}
    for rec in records:
        st = str(rec.get("status") or "")
        if st in out:
            out[st] += 1
    return out


def _feat_disabled_numbers():
    """Numbers the user switched off, from config plugin_config["features"]."""
    try:
        from memory.config_manager import get_plugin_config
        raw = (get_plugin_config("features") or {}).get("disabled", []) or []
        return {int(n) for n in raw if str(n).isdigit()}
    except Exception:
        return set()


def _feat_is_enabled(number):
    try:
        n = int(number)
    except (TypeError, ValueError):
        return True
    fr = _feat_registry()
    if fr is not None and hasattr(fr, "is_enabled"):
        try:
            return bool(fr.is_enabled(n))
        except Exception:
            pass
    return n not in _feat_disabled_numbers()


def _feat_set_enabled(number, on):
    """Persist an enable/disable toggle. Returns True on success. Never raises."""
    try:
        n = int(number)
    except (TypeError, ValueError):
        return False
    fr = _feat_registry()
    if fr is not None and hasattr(fr, "set_enabled"):
        try:
            fr.set_enabled(n, bool(on))
            return True
        except Exception:
            pass
    try:
        from memory.config_manager import get_plugin_config, save_plugin_config
        disabled = _feat_disabled_numbers()
        if on:
            disabled.discard(n)
        else:
            disabled.add(n)
        save_plugin_config("features", {"disabled": sorted(disabled)})
        return True
    except Exception:
        return False


def _feat_run(number):
    """Enqueue a feature run through core/action_queue.py — the same path
    the HUD quick actions use. Returns (queue_id, record) or ("", None)."""
    rec = _feat_resolve(number)
    if rec is None:
        return "", None
    try:
        from core.action_queue import enqueue
        qid = enqueue("features", {"action": "run", "number": str(rec["number"])})
    except Exception:
        qid = ""
    return qid or "", rec


def ask_muse_about_current_work():
    """💬 ASK MUSE — queue what Mark is currently working on to Muse Bridge.

    instruction = Mark's current_task + last_response (core/mark_status);
    tried = the currently-working agents (REGISTRY.snapshot). Calls
    core/muse_bridge.create_task (fast config write, no network — safe on
    the Qt thread). Returns (task_id or "", message). Never raises.
    core/muse_bridge.py landed 2026-11-17 (verified live: create -> seen
    -> done round-trips); when it is missing the message says so instead
    of crashing."""
    try:
        from core.mark_status import snapshot as _ms
        ms = _ms() or {}
        cur = str(ms.get("current_task") or "").strip()
        last = str(ms.get("last_response") or "").strip()
    except Exception:
        cur, last = "", ""
    try:
        snap = REGISTRY.snapshot()
        working = [a for a in snap if a.get("status") == "working"]
        tried = "; ".join(
            f"{a.get('icon', '')}{a.get('name', '?')}: "
            f"{str(a.get('current_task') or a.get('job') or '')[:80]}"
            for a in working) or "No worker agent currently working."
    except Exception:
        tried = "Worker agent status unavailable."
    instruction = ("Mark is working on: "
                   + (cur or "nothing specific right now (idle)"))
    if last:
        instruction += f"\nMark's last reply: {last}"
    instruction += ("\nHelp Mark finish this — do the work, or explain "
                    "exactly what is missing (key, device, permission) so "
                    "Mark can ask the user.")
    try:
        from core import muse_bridge as _mb
        tid = _mb.create_task(instruction, tried=tried,
                              context="Mark-LVII HUD — Ask Muse")
    except Exception as e:
        return "", f"⚠️ Muse-ke task pathate parlam na: {e}"
    if not tid:
        return "", "⚠️ Muse-ke task pathate parlam na — bridge khali id dilo na."
    return str(tid), f"💬 Muse-ke task pathano holo (id {tid})"


class FeaturesOverlay(QWidget):
    """Floating overlay — 🔍 FEATURES: browse the feature registry.

    Search-as-you-type (number + name + status per hit), a category
    dropdown (100 categories), a status filter, run-by-number (1–13,700,000;
    ▶ RUN enqueues through core/action_queue.py — the same path the HUD
    quick actions use — and shows "queued — Mark will run it"), an
    enable/disable toggle per feature, and a coverage counter from
    counts(). Follows the AgentsOverlay pattern exactly: _lbl helper,
    closed pyqtSignal, QTimer poll on the Qt thread, WA_StyledBackground,
    palette colours only, hud_font/mono_font. Nothing here ever raises
    out of a slot — a failed registry read shows as a status line.
    """

    closed = pyqtSignal()

    _OW, _OH = 520, 700
    _PAGE = 30   # rows shown per refresh

    _DOT = {
        "WORKING": C.GREEN,
        "NEEDS-KEY": C.ACC2,
        "NEEDS-DEVICE": C.ACC,
        "PLANNED": C.TEXT_DIM,
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            FeaturesOverlay {{
                background: rgba(0, 4, 12, 0.95);
                border: 1px solid {C.BORDER_B};
                border-radius: 14px;
            }}
        """)
        self._results: list[dict] = []
        self._total_shown = 0

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 16, 24, 16)
        lay.setSpacing(5)

        def _lbl(txt, fs=9, bold=False, color=C.PRI,
                 align=Qt.AlignmentFlag.AlignCenter):
            w = QLabel(txt)
            w.setAlignment(align)
            w.setFont(hud_font(fs,
                            QFont.Weight.Bold if bold else QFont.Weight.Normal))
            w.setStyleSheet(f"color: {color}; background: transparent;")
            w.setWordWrap(True)
            return w

        lay.addWidget(_lbl("🔍  FEATURES — sob feature ek jaigai", 12, True))
        lay.addWidget(_lbl("Search koro, category dekho, number diye chalao — "
                           "Mark queue theke chalabe", 8, color=C.TEXT_DIM))
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER}; margin: 1px 0;")
        lay.addWidget(sep)

        self._coverage_lbl = _lbl("", 9, True, color=C.GREEN)
        lay.addWidget(self._coverage_lbl)

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Search features…  jemon 'YouTube upload'")
        self._search_input.setFont(hud_font(9))
        self._search_input.setFixedHeight(30)
        self._search_input.setStyleSheet(f"""
            QLineEdit {{
                background: #000d12; color: {C.TEXT};
                border: 1px solid {C.BORDER}; border-radius: 3px; padding: 4px 8px;
            }}
            QLineEdit:focus {{ border: 1px solid {C.PRI}; }}
        """)
        self._search_input.textChanged.connect(lambda _t: self._refresh())
        lay.addWidget(self._search_input)

        _combo_css = (
            f"QComboBox {{ background: #000d12; color: {C.TEXT}; "
            f"border: 1px solid {C.BORDER}; border-radius: 3px; padding: 4px 8px; }}"
            f"QComboBox:hover {{ border-color: {C.BORDER_B}; }}"
            f"QComboBox QAbstractItemView {{ background: #000d12; color: {C.TEXT}; "
            f"selection-background-color: {C.PRI_GHO}; border: 1px solid {C.BORDER}; }}"
        )
        filt_row = QHBoxLayout(); filt_row.setSpacing(6)
        self._cat_box = QComboBox()
        self._cat_box.setFont(hud_font(8))
        self._cat_box.setFixedHeight(30)
        self._cat_box.setStyleSheet(_combo_css)
        self._cat_box.addItem("All categories", 0)
        for idx, name in _feat_categories():
            self._cat_box.addItem(f"{idx}. {name}", idx)
        self._cat_box.currentIndexChanged.connect(lambda _i: self._refresh())
        filt_row.addWidget(self._cat_box, 2)
        self._status_box = QComboBox()
        self._status_box.setFont(hud_font(8))
        self._status_box.setFixedHeight(30)
        self._status_box.setStyleSheet(_combo_css)
        for label, val in [("All statuses", ""), ("WORKING", "WORKING"),
                           ("NEEDS-KEY", "NEEDS-KEY"),
                           ("NEEDS-DEVICE", "NEEDS-DEVICE"),
                           ("PLANNED", "PLANNED")]:
            self._status_box.addItem(label, val)
        self._status_box.currentIndexChanged.connect(lambda _i: self._refresh())
        filt_row.addWidget(self._status_box, 1)
        lay.addLayout(filt_row)

        # Scrollable results — rebuilt on every filter change.
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet("background: transparent; border: none;")
        self._list_widget = QWidget()
        self._list_widget.setStyleSheet("background: transparent;")
        self._list_lay = QVBoxLayout(self._list_widget)
        self._list_lay.setContentsMargins(0, 0, 0, 0)
        self._list_lay.setSpacing(4)
        self._list_lay.addStretch()
        self._scroll.setWidget(self._list_widget)
        lay.addWidget(self._scroll, 1)

        self._shown_lbl = _lbl("", 8, color=C.TEXT_DIM)
        lay.addWidget(self._shown_lbl)

        # Run by number.
        run_row = QHBoxLayout(); run_row.setSpacing(6)
        run_row.addWidget(_lbl("RUN BY NUMBER", 8, color=C.TEXT_DIM,
                               align=Qt.AlignmentFlag.AlignLeft))
        self._num_input = QLineEdit()
        self._num_input.setPlaceholderText("1 – 13700000")
        self._num_input.setFont(mono_font(9))
        self._num_input.setFixedHeight(30)
        self._num_input.setStyleSheet(f"""
            QLineEdit {{
                background: #000d12; color: {C.TEXT};
                border: 1px solid {C.BORDER}; border-radius: 3px; padding: 4px 8px;
            }}
            QLineEdit:focus {{ border: 1px solid {C.PRI}; }}
        """)
        self._num_input.returnPressed.connect(self._on_run_number)
        run_row.addWidget(self._num_input, 1)
        run_btn = QPushButton("▶  RUN")
        run_btn.setFixedHeight(30)
        run_btn.setFont(hud_font(9, QFont.Weight.Bold))
        run_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        run_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.PRI};
                border: 1px solid {C.PRI_DIM}; border-radius: 3px; padding: 4px 14px;
            }}
            QPushButton:hover {{ background: {C.PRI_GHO}; border: 1px solid {C.PRI}; }}
        """)
        run_btn.clicked.connect(self._on_run_number)
        run_row.addWidget(run_btn)
        lay.addLayout(run_row)

        self._status_lbl = _lbl("", 8, color=C.GREEN)
        lay.addWidget(self._status_lbl)

        close_btn = QPushButton("✕  BONDHO KORO")
        close_btn.setStyleSheet(
            f"color: {C.TEXT_DIM}; background: transparent; padding: 4px;")
        close_btn.clicked.connect(self._do_close)
        lay.addWidget(close_btn)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(2000)
        self._refresh()

    # ── actions (Qt thread only; registry reads are in-memory) ─────────────

    def _on_toggle(self, number: int, btn: QPushButton) -> None:
        try:
            on = not _feat_is_enabled(number)
            if _feat_set_enabled(number, on):
                self._style_toggle(btn, on)
                self._status_lbl.setText(
                    f"#{number} {'ON korlam' if on else 'OFF korlam'}.")
            else:
                self._status_lbl.setText(f"⚠️ #{number} toggle korte parlam na.")
        except Exception:
            self._status_lbl.setText("⚠️ Toggle korte parlam na.")

    def _on_run_row(self, number: int, name: str, status: str) -> None:
        try:
            qid, _rec = _feat_run(number)
        except Exception:
            qid = ""
        if qid:
            note = (" — PLANNED/NEEDS-DEVICE hole Mark ki missing seta bolbe."
                    if status in ("PLANNED", "NEEDS-DEVICE") else "")
            self._status_lbl.setText(
                f"✅ #{number} {name}: queued — Mark will run it (#{qid}).{note}")
        else:
            self._status_lbl.setText(
                f"⚠️ #{number}: queue-te dite parlam na — abar try koro.")

    def _on_run_number(self) -> None:
        raw = self._num_input.text().strip()
        try:
            n = int(raw)
        except (TypeError, ValueError):
            self._status_lbl.setText("⚠️ Number dao — 1 theke 13700000-er modhye.")
            return
        if n < 1 or n > _MAX_FEATURE_NUMBER:
            self._status_lbl.setText("⚠️ Number dao — 1 theke 13700000-er modhye.")
            return
        rec = _feat_resolve(n)
        if rec is None:
            total = _feat_counts().get("total") or 0
            self._status_lbl.setText(
                f"⚠️ #{n} registry-te nei — registry-te ekhon {total:,} ta feature.")
            return
        self._on_run_row(n, rec.get("name") or "", rec.get("status") or "")

    # ── build / tick (Qt thread only) ────────────────────────────────────────

    @staticmethod
    def _style_toggle(btn: QPushButton, enabled: bool):
        if enabled:
            btn.setText("ON")
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: #001a08; color: {C.GREEN};
                    border: 1px solid {C.GREEN_D}; border-radius: 3px;
                }}
                QPushButton:hover {{ background: #002010; }}
            """)
        else:
            btn.setText("OFF")
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent; color: {C.TEXT_DIM};
                    border: 1px solid {C.BORDER}; border-radius: 3px;
                }}
                QPushButton:hover {{ color: {C.TEXT}; border-color: {C.BORDER_B}; }}
            """)

    def _clear_list(self):
        while self._list_lay.count():
            item = self._list_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()
                w.deleteLater()

    def _refresh(self) -> None:
        """Rebuild the result rows from the current filters. Never raises."""
        try:
            q = self._search_input.text().strip()
            cidx = int(self._cat_box.currentData() or 0)
            status = str(self._status_box.currentData() or "")
            if q:
                items = _feat_search(q, 100)
            elif cidx:
                items = _feat_list_category(cidx, 0, 100)
            else:
                items = _feat_first(100)
            if cidx:
                items = [r for r in items if r.get("category_index") == cidx]
            if status:
                items = [r for r in items if r.get("status") == status]
            self._total_shown = len(items)
            self._results = items[: self._PAGE]
            self._clear_list()
            if not self._results:
                empty = QLabel("Kono feature milche na — search ba filter bodle dekho.")
                empty.setWordWrap(True)
                empty.setFont(hud_font(8))
                empty.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
                self._list_lay.addWidget(empty)
            for rec in self._results:
                self._list_lay.addWidget(self._build_row(rec))
            self._list_lay.addStretch()
            self._shown_lbl.setText(
                f"Showing {len(self._results)} of {self._total_shown} match"
                + ("es" if self._total_shown != 1 else ""))
        except Exception:
            pass
        self._update_coverage()

    def _build_row(self, rec: dict) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(f"""
            QFrame {{
                background: {C.PANEL2};
                border: 1px solid {C.BORDER};
                border-radius: 8px;
            }}
        """)
        flay = QHBoxLayout(frame)
        flay.setContentsMargins(10, 6, 10, 6)
        flay.setSpacing(6)

        n = int(rec.get("number") or 0)
        st = str(rec.get("status") or "PLANNED")
        dot = QLabel("●")
        dot.setFont(hud_font(9))
        dot.setStyleSheet(
            f"color: {self._DOT.get(st, C.TEXT_DIM)}; background: transparent;")
        flay.addWidget(dot)

        name = QLabel(f"#{n}  {rec.get('name') or ''}")
        name.setFont(hud_font(9, QFont.Weight.Bold))
        name.setStyleSheet(
            f"color: {C.TEXT if rec.get('enabled', True) else C.TEXT_DIM};"
            " background: transparent;")
        name.setWordWrap(False)
        fm = name.fontMetrics()
        name.setText(fm.elidedText(f"#{n}  {rec.get('name') or ''}",
                                   Qt.TextElideMode.ElideRight, 260))
        name.setToolTip(f"{rec.get('name') or ''} [{st}] — "
                        f"{rec.get('category') or ''}")
        flay.addWidget(name, 1)

        badge = QLabel(st)
        badge.setFont(hud_font(7, QFont.Weight.Bold))
        badge.setStyleSheet(
            f"color: {self._DOT.get(st, C.TEXT_DIM)}; background: transparent;")
        flay.addWidget(badge)

        tog = QPushButton()
        tog.setFixedSize(52, 24)
        tog.setFont(hud_font(7, QFont.Weight.Bold))
        tog.setCursor(Qt.CursorShape.PointingHandCursor)
        self._style_toggle(tog, bool(rec.get("enabled", True)))
        tog.clicked.connect(lambda _c, num=n, b=tog: self._on_toggle(num, b))
        flay.addWidget(tog)

        run_b = QPushButton("▶ RUN")
        run_b.setFixedSize(52, 24)
        run_b.setFont(hud_font(7, QFont.Weight.Bold))
        run_b.setCursor(Qt.CursorShape.PointingHandCursor)
        run_b.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.PRI};
                border: 1px solid {C.PRI_DIM}; border-radius: 3px;
            }}
            QPushButton:hover {{ background: {C.PRI_GHO}; }}
        """)
        run_b.clicked.connect(
            lambda _c, num=n, nm=rec.get("name") or "", s=st:
                self._on_run_row(num, nm, s))
        flay.addWidget(run_b)
        return frame

    def _update_coverage(self) -> None:
        try:
            c = _feat_counts()
            total = int(c.get("total") or 0)
            working = int(c.get("WORKING") or 0)
            self._coverage_lbl.setText(
                f"{working:,} / {total:,} working"
                f"   •   NEEDS-KEY {int(c.get('NEEDS-KEY') or 0):,}  •  "
                f"NEEDS-DEVICE {int(c.get('NEEDS-DEVICE') or 0):,}  •  "
                f"PLANNED {int(c.get('PLANNED') or 0):,}")
        except Exception:
            pass

    def _tick(self) -> None:
        """2 s poll: coverage only — the list rebuilds on filter change."""
        self._update_coverage()

    def _do_close(self) -> None:
        self._timer.stop()
        self.hide()
        self.closed.emit()


class AgentsOverlay(QWidget):
    """Floating overlay — the 7 worker agents, live: what each is doing,
    its status, how long it has been working, how much is done.

    Reads core.agents.REGISTRY.snapshot() on a 1 s QTimer on the Qt thread
    (same pattern as JarvisLinkOverlay._tick); worker threads never touch
    these widgets. core.agents imports no Qt.
    """

    closed = pyqtSignal()

    _OW, _OH = 460, 640

    # Status dot colours — all from the C palette. The palette has no grey,
    # so idle uses the dimmest text colour (TEXT_DIM) as its "off" grey.
    _DOT = {
        "idle": C.TEXT_DIM,
        "working": C.PRI,
        "done": C.GREEN,
        "error": C.RED,
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            AgentsOverlay {{
                background: rgba(0, 4, 12, 0.95);
                border: 1px solid {C.BORDER_B};
                border-radius: 14px;
            }}
        """)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 16, 24, 16)
        lay.setSpacing(5)

        def _lbl(txt, fs=9, bold=False, color=C.PRI,
                 align=Qt.AlignmentFlag.AlignCenter):
            w = QLabel(txt)
            w.setAlignment(align)
            w.setFont(hud_font(fs,
                            QFont.Weight.Bold if bold else QFont.Weight.Normal))
            w.setStyleSheet(f"color: {color}; background: transparent;")
            w.setWordWrap(True)
            return w

        lay.addWidget(_lbl("🤖  AGENTS — Mark-er 7 worker", 12, True))
        lay.addWidget(_lbl("Ke ki korche, kotokkhon dhore, kotota sesh — live",
                           8, color=C.TEXT_DIM))
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER}; margin: 1px 0;")
        lay.addWidget(sep)

        # One row per agent, built from AGENT_DEFS order so the panel and
        # the registry can never drift apart.
        from core.agents import AGENT_DEFS
        self._rows = {}
        for a in AGENT_DEFS:
            frame = QFrame()
            frame.setStyleSheet(f"""
                QFrame {{
                    background: {C.PANEL2};
                    border: 1px solid {C.BORDER};
                    border-radius: 8px;
                }}
            """)
            flay = QVBoxLayout(frame)
            flay.setContentsMargins(10, 6, 10, 6)
            flay.setSpacing(2)

            top = QHBoxLayout()
            top.setSpacing(6)
            dot = QLabel("●")
            dot.setFont(hud_font(10))
            dot.setStyleSheet(
                f"color: {self._DOT['idle']}; background: transparent;")
            top.addWidget(dot)
            name = QLabel(f"{a['icon']}  {a['name']}")
            name.setFont(hud_font(10, QFont.Weight.Bold))
            name.setStyleSheet(f"color: {C.PRI}; background: transparent;")
            top.addWidget(name)
            top.addStretch()
            elapsed = QLabel("00:00")
            elapsed.setFont(mono_font(9))
            elapsed.setStyleSheet(
                f"color: {C.TEXT_MED}; background: transparent;")
            top.addWidget(elapsed)
            count = QLabel("✓ 0")
            count.setFont(hud_font(9, QFont.Weight.Bold))
            count.setStyleSheet(f"color: {C.GREEN}; background: transparent;")
            top.addWidget(count)
            flay.addLayout(top)

            task = QLabel(a["job"])
            task.setFont(hud_font(8))
            task.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
            task.setWordWrap(False)
            flay.addWidget(task)

            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(0)
            bar.setTextVisible(False)
            bar.setFixedHeight(7)
            bar.setStyleSheet(f"""
                QProgressBar {{
                    background: {C.BAR_BG};
                    border: 1px solid {C.BORDER};
                    border-radius: 3px;
                }}
                QProgressBar::chunk {{
                    background: {C.PRI};
                    border-radius: 3px;
                }}
            """)
            flay.addWidget(bar)

            lay.addWidget(frame)
            self._rows[a["id"]] = {
                "dot": dot, "name": name, "elapsed": elapsed,
                "count": count, "task": task, "bar": bar,
                "job": a["job"],
            }

        lay.addStretch()

        close_btn = QPushButton("✕  BONDHO KORO")
        close_btn.setStyleSheet(
            f"color: {C.TEXT_DIM}; background: transparent; padding: 4px;")
        close_btn.clicked.connect(self._do_close)
        lay.addWidget(close_btn)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)
        self._tick()

    # ── tick (Qt thread only) ────────────────────────────────────────────────

    @staticmethod
    def _fmt_elapsed(seconds: float) -> str:
        total = max(0, int(seconds))
        return f"{total // 60:02d}:{total % 60:02d}"

    def _tick(self) -> None:
        try:
            snap = REGISTRY.snapshot()
        except Exception:
            return
        for a in snap:
            row = self._rows.get(a["id"])
            if row is None:
                continue
            status = a.get("status", "idle")
            row["dot"].setStyleSheet(
                f"color: {self._DOT.get(status, C.TEXT_DIM)};"
                " background: transparent;")
            if not a.get("enabled", True):
                row["name"].setStyleSheet(
                    f"color: {C.TEXT_DIM}; background: transparent;")
                row["task"].setText("Disabled in Settings")
            else:
                row["name"].setStyleSheet(
                    f"color: {C.PRI}; background: transparent;")
                task = (a.get("current_task") or "").strip()
                if status == "working" and task:
                    shown = task
                elif status == "done":
                    shown = "✓ " + (task or row["job"])
                elif status == "error":
                    shown = "⚠ " + (task or row["job"])
                else:
                    shown = row["job"]
                fm = row["task"].fontMetrics()
                row["task"].setText(
                    fm.elidedText(shown, Qt.TextElideMode.ElideRight, 400))
            row["elapsed"].setText(self._fmt_elapsed(a.get("elapsed_s", 0.0)))
            row["count"].setText(f"✓ {int(a.get('completed_count', 0))}")
            row["bar"].setValue(max(0, min(100, int(a.get("progress", 0)))))

    def _do_close(self) -> None:
        self._timer.stop()
        self.hide()
        self.closed.emit()


# ── ⚡ AUTOMATION + 🧠 MAIN AGENT overlays ───────────────────────────────────
# Both follow the AgentsOverlay pattern exactly: Qt widgets only on the Qt
# thread, a QTimer poll reads thread-safe state (ENGINE / REGISTRY /
# mark_status / action_queue), and every slow call (run-now, template
# create, phone/PC screen fetch, location request) runs on a worker thread
# and reports back through a pyqtSignal. Nothing here ever raises out of
# a slot — a failed engine call shows as a status line, never a crash.
# Edit of a task happens on the dashboard page (/automation form) — this
# HUD has no edit dialog, by design.

_TEMPLATES = [
    ("morning_briefing", "🌅 Morning briefing"),
    ("daily_backup", "💾 Daily backup"),
    ("evening_upload", "🌆 Evening upload"),
    ("weekly_drive_sync", "☁️ Weekly Drive sync"),
    ("social_post_fixed_time", "📣 Social post (fixed time)"),
]


def _trigger_text(trigger: dict) -> str:
    """One short line for a trigger dict. Never raises."""
    try:
        trig = dict(trigger or {})
        ttype = str(trig.get("type") or "?").strip().lower()
        if ttype == "time":
            kind = str(trig.get("kind") or "")
            when = str(trig.get("time") or "")
            extra = ""
            if kind == "once":
                extra = f" {trig.get('date') or trig.get('at') or ''}"
            elif kind == "weekly":
                extra = f" weekday {trig.get('weekday')}"
            return f"🕐 {kind or 'time'} {when}{extra}".strip()
        if ttype == "interval":
            return f"🔁 every {trig.get('every')} {trig.get('unit') or 'minutes'}"
        if ttype == "keyword":
            return f"💬 keyword '{trig.get('phrase')}'"
        if ttype == "event":
            return f"⚡ event '{trig.get('name')}'"
        if ttype == "webhook":
            return "🌐 webhook (dashboard only)"
        return ttype or "?"
    except Exception:
        return "?"


def _countdown(next_run) -> str:
    """hh:mm:ss until next_run (ISO), or '—' when there is none / it passed."""
    try:
        from datetime import datetime
        if not next_run:
            return "—"
        nxt = datetime.fromisoformat(str(next_run))
        delta = (nxt - datetime.now()).total_seconds()
        if delta <= 0:
            return "due now"
        total = int(delta)
        return f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"
    except Exception:
        return "—"


class AutomationOverlay(QWidget):
    """Floating overlay — ⚡ AUTOMATION: the task engine's visual flow view.

    Each task card shows Trigger block → Action blocks (step tool names in
    order) → Condition badge, next-run countdown, last-run result from
    ENGINE.history(), an enable/disable toggle, a run-now button and a
    delete button. Recipe templates below create a real task in one click.
    Edit lives on the dashboard page (/automation form) — no edit dialog
    here. Polls ENGINE on a 2 s QTimer; the card list rebuilds only when
    the task/history fingerprint changes, so buttons never flicker.
    """

    closed = pyqtSignal()
    _run_done = pyqtSignal(str)   # worker thread -> Qt thread: run result

    _OW, _OH = 460, 640

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            AutomationOverlay {{
                background: rgba(0, 4, 12, 0.95);
                border: 1px solid {C.BORDER_B};
                border-radius: 14px;
            }}
        """)
        self._fingerprint = None
        self._status_msg = ""
        self._status_at = 0.0
        self._run_done.connect(self._on_run_done)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 16, 24, 16)
        lay.setSpacing(5)

        def _lbl(txt, fs=9, bold=False, color=C.PRI,
                 align=Qt.AlignmentFlag.AlignCenter):
            w = QLabel(txt)
            w.setAlignment(align)
            w.setFont(hud_font(fs,
                            QFont.Weight.Bold if bold else QFont.Weight.Normal))
            w.setStyleSheet(f"color: {color}; background: transparent;")
            w.setWordWrap(True)
            return w

        lay.addWidget(_lbl("⚡  AUTOMATION — scheduled tasks", 12, True))
        lay.addWidget(_lbl("Trigger → steps → condition — live, dashboard-e edit koro",
                           8, color=C.TEXT_DIM))
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER}; margin: 1px 0;")
        lay.addWidget(sep)

        self._summary_lbl = _lbl("", 8, color=C.TEXT_DIM)
        lay.addWidget(self._summary_lbl)

        # Scrollable task list — rebuilt only when the fingerprint changes.
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet(
            f"background: transparent; border: none;")
        self._list_widget = QWidget()
        self._list_widget.setStyleSheet("background: transparent;")
        self._list_lay = QVBoxLayout(self._list_widget)
        self._list_lay.setContentsMargins(0, 0, 0, 0)
        self._list_lay.setSpacing(6)
        self._list_lay.addStretch()
        self._scroll.setWidget(self._list_widget)
        lay.addWidget(self._scroll, 1)

        lay.addWidget(_lbl("🍳  RECIPE TEMPLATES — ek click-e task banao",
                           9, True, color=C.PRI))
        tpl_row = QHBoxLayout()
        tpl_row.setSpacing(4)
        for key, label in _TEMPLATES:
            b = QPushButton(label)
            b.setFont(hud_font(7))
            b.setStyleSheet(
                f"color: {C.PRI}; background: {C.PANEL2}; "
                f"border: 1px solid {C.BORDER}; border-radius: 8px; padding: 5px")
            b.clicked.connect(lambda _c, k=key: self._on_template(k))
            tpl_row.addWidget(b)
        lay.addLayout(tpl_row)

        self._status_lbl = _lbl("", 8, color=C.GREEN)
        lay.addWidget(self._status_lbl)

        close_btn = QPushButton("✕  BONDHO KORO")
        close_btn.setStyleSheet(
            f"color: {C.TEXT_DIM}; background: transparent; padding: 4px;")
        close_btn.clicked.connect(self._do_close)
        lay.addWidget(close_btn)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(2000)
        self._tick()

    # ── actions (Qt thread starts them; slow work on a worker thread) ───────

    def _on_toggle(self, task_id: str, on: bool) -> None:
        try:
            from core.automation import ENGINE
            ok = ENGINE.set_enabled(task_id, on)
            self._show_status(
                f"{'✅ Task on korlam' if on else '⏸️ Task off korlam'}"
                if ok else "⚠️ Task-ta pelam na.")
        except Exception:
            self._show_status("⚠️ Toggle korte parlam na.")
        self._tick(force=True)

    def _on_run_now(self, task_id: str, name: str) -> None:
        self._show_status(f"⏳ '{name}' cholche…")

        def _work():
            try:
                from core.automation import ENGINE
                res = ENGINE.run_task_now(task_id)
            except Exception as e:
                res = f"Run korte parlam na: {e}"
            self._run_done.emit(str(res)[:300])

        threading.Thread(target=_work, daemon=True,
                         name="automation-run-now").start()

    def _on_delete(self, task_id: str, name: str) -> None:
        try:
            from core.automation import ENGINE
            ok = ENGINE.delete_task(task_id)
            self._show_status(
                f"🗑️ '{name}' delete korlam." if ok
                else "⚠️ Task-ta pelam na.")
        except Exception:
            self._show_status("⚠️ Delete korte parlam na.")
        self._tick(force=True)

    def _on_template(self, key: str) -> None:
        self._show_status(f"⏳ Template '{key}' theke task banachhi…")

        def _work():
            try:
                from core.automation import ENGINE
                tid = ENGINE.create_from_template(key)
                res = (f"✅ Template '{key}' theke task toiri (id {tid})."
                       if tid else f"⚠️ Template '{key}' chinlam na.")
            except Exception as e:
                res = f"Template banate parlam na: {e}"
            self._run_done.emit(res)

        threading.Thread(target=_work, daemon=True,
                         name="automation-template").start()

    def _on_run_done(self, res: str) -> None:
        """Qt thread (via _run_done): show the worker result, refresh."""
        self._show_status(res)
        self._tick(force=True)

    def _show_status(self, msg: str) -> None:
        self._status_msg = str(msg or "")[:300]
        self._status_at = time.monotonic()
        self._status_lbl.setText(self._status_msg)

    # ── build / tick (Qt thread only) ────────────────────────────────────────

    def _build_card(self, task: dict, last: dict | None) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(f"""
            QFrame {{
                background: {C.PANEL2};
                border: 1px solid {C.BORDER};
                border-radius: 8px;
            }}
        """)
        flay = QVBoxLayout(frame)
        flay.setContentsMargins(10, 6, 10, 6)
        flay.setSpacing(3)

        def _l(txt, fs=9, bold=False, color=C.PRI,
               align=Qt.AlignmentFlag.AlignLeft):
            w = QLabel(txt)
            w.setAlignment(align)
            w.setFont(hud_font(fs,
                            QFont.Weight.Bold if bold else QFont.Weight.Normal))
            w.setStyleSheet(f"color: {color}; background: transparent;")
            w.setWordWrap(True)
            return w

        top = QHBoxLayout()
        name = _l(f"{'🟢' if task.get('enabled') else '⚪'}  "
                  f"{task.get('name') or '?'}", 10, True)
        top.addWidget(name, 1)
        nxt = _l("⏭ " + _countdown(task.get("next_run")), 8,
                 color=C.TEXT_MED)
        top.addWidget(nxt)
        flay.addLayout(top)

        # Visual flow: Trigger block → Action blocks → Condition badge.
        steps = [str(s.get("tool") or "?") for s in (task.get("steps") or [])]
        flow = _trigger_text(task.get("trigger") or {})
        flow += "  ➜  " + ("  ➜  ".join(steps) if steps else "no steps")
        cond = task.get("condition") or {}
        if cond:
            ctype = str(cond.get("type") or "?")
            extra = (f" {cond.get('minutes')} min"
                     if ctype == "idle" and cond.get("minutes") else "")
            flow += f"   [only if: {ctype}{extra}]"
        flay.addWidget(_l(flow, 8, color=C.TEXT_DIM))

        last_txt = "last run: —"
        if last:
            st = str(last.get("status") or "?")
            when = str(last.get("finished_at") or last.get("started_at") or "")
            note = str(last.get("note") or "")[:80]
            last_txt = (f"last run: {'✅' if st == 'ok' else '❌'} {st} {when}"
                        + (f" — {note}" if note else ""))
        flay.addWidget(_l(last_txt, 8, color=C.TEXT_MED))

        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)

        def _btn(txt, color=C.PRI):
            b = QPushButton(txt)
            b.setFont(hud_font(8))
            b.setStyleSheet(
                f"color: {color}; background: {C.PANEL2}; "
                f"border: 1px solid {C.BORDER}; border-radius: 6px; padding: 4px")
            return b

        tid = str(task.get("id") or "")
        tname = str(task.get("name") or "?")
        tog = _btn("⏸ OFF" if task.get("enabled") else "▶ ON",
                   C.GREEN if not task.get("enabled") else C.TEXT_MED)
        tog.clicked.connect(
            lambda _c, i=tid, on=not bool(task.get("enabled")):
            self._on_toggle(i, on))
        btn_row.addWidget(tog)
        run_b = _btn("▶ RUN NOW", C.ACC)
        run_b.clicked.connect(lambda _c, i=tid, n=tname: self._on_run_now(i, n))
        btn_row.addWidget(run_b)
        del_b = _btn("🗑 DELETE", C.RED)
        del_b.clicked.connect(lambda _c, i=tid, n=tname: self._on_delete(i, n))
        btn_row.addWidget(del_b)
        btn_row.addStretch()
        flay.addLayout(btn_row)
        return frame

    def _tick(self, force: bool = False) -> None:
        try:
            from core.automation import ENGINE
            tasks = ENGINE.list_tasks()
            hist = ENGINE.history()
        except Exception:
            return
        try:
            last_by_task = {}
            for h in hist:
                last_by_task[h.get("task_id")] = h
            import json as _json
            fp = _json.dumps(
                [(t.get("id"), t.get("name"), t.get("enabled"),
                  t.get("next_run"), _trigger_text(t.get("trigger") or {}),
                  [s.get("tool") for s in (t.get("steps") or [])],
                  t.get("condition")) for t in tasks]
                + [(h.get("task_id"), h.get("status"), h.get("finished_at"))
                   for h in hist[-10:]],
                sort_keys=True, default=str)
            if not force and fp == self._fingerprint:
                # Same tasks — only the countdowns age: update the summary
                # line (cheap) and leave the cards alone.
                self._update_summary(tasks)
                return
            self._fingerprint = fp
            # Rebuild the list (drop the trailing stretch, re-add after).
            while self._list_lay.count():
                item = self._list_lay.takeAt(0)
                w = item.widget()
                if w is not None:
                    w.deleteLater()
            if not tasks:
                empty = QLabel("Kono automation task nei ekhono.\n"
                               "Nicher template theke ekta banao, ba dashboard-e "
                               "/automation khule notun task likho.")
                empty.setFont(hud_font(8))
                empty.setStyleSheet(
                    f"color: {C.TEXT_DIM}; background: transparent;")
                empty.setWordWrap(True)
                self._list_lay.addWidget(empty)
            for t in tasks:
                self._list_lay.addWidget(
                    self._build_card(t, last_by_task.get(t.get("id"))))
            self._list_lay.addStretch()
            self._update_summary(tasks)
        except Exception:
            return

    def _update_summary(self, tasks: list) -> None:
        try:
            on = sum(1 for t in tasks if t.get("enabled"))
            nxts = [t.get("next_run") for t in tasks
                    if t.get("enabled") and t.get("next_run")]
            nxt_txt = "—"
            if nxts:
                nxt_txt = "⏭ " + _countdown(min(nxts))
            self._summary_lbl.setText(
                f"{len(tasks)} task ({on} on) • next run {nxt_txt} • "
                "edit: dashboard /automation")
        except Exception:
            pass

    def _do_close(self) -> None:
        self._timer.stop()
        self.hide()
        self.closed.emit()


class MainAgentOverlay(QWidget):
    """Floating overlay — 🧠 MAIN AGENT: Mark's master screen.

    Sections: (1) Mark's live status (core/mark_status.py — current task,
    last reply, queue length); (2) one-line summary of all 7 agents
    (REGISTRY.snapshot) + all automation tasks (ENGINE counts + next run);
    (3) PHONE SCREEN — memory/phone_screen.jpg, re-polled every 4 s, with
    a Refresh button (worker thread calls link.fetch_phone_screen);
    (4) PC SCREEN — this PC's own screen via mss (the same capture helper
    jarvis_link uses for the phone's screen_req — no duplicate code), with
    a Refresh button; (5) LOCATION — last-known phone location + Find phone
    button; (6) quick actions — every button ENQUEUES through
    core/action_queue.py and shows "queued — Mark will run it" (main.py
    drains the queue at integration; the HUD never calls a tool directly).
    Polls on a 1 s QTimer; screens re-poll every 4 s.
    """

    closed = pyqtSignal()
    _worker_done = pyqtSignal(str, str)   # (kind, message) -> Qt thread

    _OW, _OH = 520, 700

    # Quick actions: (button label, tool name, args). All go through the
    # action queue — nothing here calls a tool directly.
    _QUICK_ACTIONS = [
        ("📱 Open app", "open_app", {"app": "Calculator"}),
        ("🎬 Upload video", "youtube_upload",
         {"file_path": "", "title": "Today's video"}),
        ("💬 Send WhatsApp", "whatsapp_send",
         {"to": "", "message": ""}),
        ("💾 Backup", "drive_upload",
         {"filename": "mark-lvii-backup.txt",
          "content": "Mark-LVII backup note"}),
        ("📍 Find phone", "phone_location", {"refresh": True}),
        ("🖥️ Screenshot PC", "screen_process", {"action": "screenshot"}),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            MainAgentOverlay {{
                background: rgba(0, 4, 12, 0.95);
                border: 1px solid {C.BORDER_B};
                border-radius: 14px;
            }}
        """)
        self._phone_mtime = -1.0
        self._pc_mtime = -1.0
        self._tick_count = 0
        self._worker_done.connect(self._on_worker_done)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 16, 24, 16)
        outer.setSpacing(5)

        def _lbl(txt, fs=9, bold=False, color=C.PRI,
                 align=Qt.AlignmentFlag.AlignCenter):
            w = QLabel(txt)
            w.setAlignment(align)
            w.setFont(hud_font(fs,
                            QFont.Weight.Bold if bold else QFont.Weight.Normal))
            w.setStyleSheet(f"color: {color}; background: transparent;")
            w.setWordWrap(True)
            return w

        outer.addWidget(_lbl("🧠  MAIN AGENT — Mark-er master screen", 12, True))
        outer.addWidget(_lbl("Mark + 7 agent + automation + phone/PC screen + location — sob ek jaigai",
                             8, color=C.TEXT_DIM))
        # 👤 Guest mode — shown when core.cat09_security says it is on;
        # read on the tick so it follows a Settings change. Never raises.
        self._guest_lbl = _lbl("", 8, True, color=C.ACC2)
        outer.addWidget(self._guest_lbl)
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER}; margin: 1px 0;")
        outer.addWidget(sep)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background: transparent; border: none;")
        body = QWidget()
        body.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        def _section(title: str):
            lay.addWidget(_lbl(title, 10, True, align=Qt.AlignmentFlag.AlignLeft))

        def _txt(fs=9, color=C.PRI):
            w = QLabel("")
            w.setFont(hud_font(fs))
            w.setStyleSheet(f"color: {color}; background: transparent;")
            w.setWordWrap(True)
            w.setAlignment(Qt.AlignmentFlag.AlignLeft)
            return w

        # (1) Mark live status
        _section("🧠  Mark — live status")
        self._mark_lbl = _txt(9)
        lay.addWidget(self._mark_lbl)

        # (2) Agents + automation, one line each
        _section("🤖  7 worker agent + ⚡ automation")
        self._agents_lbl = _txt(8, C.TEXT_DIM)
        lay.addWidget(self._agents_lbl)
        self._auto_lbl = _txt(8, C.TEXT_DIM)
        lay.addWidget(self._auto_lbl)

        # (3) Phone screen
        _section("📱  PHONE SCREEN (still image, 4 s-e refresh)")
        self._phone_img = QLabel("Phone screen ekhono ashe ni — Refresh chapo.")
        self._phone_img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._phone_img.setFont(hud_font(8))
        self._phone_img.setStyleSheet(
            f"color: {C.TEXT_DIM}; background: {C.PANEL2}; "
            f"border: 1px solid {C.BORDER}; border-radius: 8px; padding: 8px;")
        self._phone_img.setMinimumHeight(120)
        lay.addWidget(self._phone_img)
        row = QHBoxLayout()
        b = QPushButton("🔄  Refresh phone screen")
        b.setFont(hud_font(8))
        b.setStyleSheet(
            f"color: {C.PRI}; background: {C.PANEL2}; border-radius: 8px; padding: 5px;")
        b.clicked.connect(self._on_refresh_phone)
        row.addWidget(b)
        row.addStretch()
        lay.addLayout(row)

        # (4) PC screen
        _section("🖥️  PC SCREEN (ei PC-r screen)")
        self._pc_img = QLabel("PC screenshot ekhono neoa hoy ni — Refresh chapo.")
        self._pc_img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._pc_img.setFont(hud_font(8))
        self._pc_img.setStyleSheet(
            f"color: {C.TEXT_DIM}; background: {C.PANEL2}; "
            f"border: 1px solid {C.BORDER}; border-radius: 8px; padding: 8px;")
        self._pc_img.setMinimumHeight(120)
        lay.addWidget(self._pc_img)
        row = QHBoxLayout()
        b = QPushButton("🔄  Refresh PC screen")
        b.setFont(hud_font(8))
        b.setStyleSheet(
            f"color: {C.PRI}; background: {C.PANEL2}; border-radius: 8px; padding: 5px;")
        b.clicked.connect(self._on_refresh_pc)
        row.addWidget(b)
        row.addStretch()
        lay.addLayout(row)

        # (5) Location
        _section("📍  LOCATION — phone kothay")
        self._loc_lbl = _txt(9)
        lay.addWidget(self._loc_lbl)
        row = QHBoxLayout()
        b = QPushButton("📍  Find phone")
        b.setFont(hud_font(8))
        b.setStyleSheet(
            f"color: {C.PRI}; background: {C.PANEL2}; border-radius: 8px; padding: 5px;")
        b.clicked.connect(self._on_find_phone)
        row.addWidget(b)
        row.addStretch()
        lay.addLayout(row)

        # (6) Quick actions — all through the action queue.
        _section("⚡  QUICK ACTIONS — queue-te jabe, Mark chalabe")
        grid = QGridLayout()
        grid.setSpacing(4)
        for i, (label, tool, args) in enumerate(self._QUICK_ACTIONS):
            b = QPushButton(label)
            b.setFont(hud_font(8))
            b.setStyleSheet(
                f"color: {C.PRI}; background: {C.PANEL2}; "
                f"border: 1px solid {C.BORDER}; border-radius: 8px; padding: 6px")
            b.clicked.connect(
                lambda _c, t=tool, a=args, l=label: self._on_quick(l, t, a))
            grid.addWidget(b, i // 3, i % 3)
        lay.addLayout(grid)

        # 💬 ASK MUSE — Mark ja korche seta Muse-ke task hisebe pathao
        # (core/muse_bridge.create_task — fast config write, no network).
        ask_btn = QPushButton("💬  ASK MUSE — ei kaj-ta Muse-ke dao")
        ask_btn.setFont(hud_font(9, QFont.Weight.Bold))
        ask_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        ask_btn.setStyleSheet(f"""
            QPushButton {{
                color: {C.PRI}; background: {C.PANEL2};
                border: 1px solid {C.PRI_DIM}; border-radius: 8px; padding: 8px;
            }}
            QPushButton:hover {{ background: {C.PRI_GHO}; border: 1px solid {C.PRI}; }}
        """)
        ask_btn.clicked.connect(self._on_ask_muse)
        lay.addWidget(ask_btn)

        self._status_lbl = _lbl("", 8, color=C.GREEN)
        lay.addWidget(self._status_lbl)

        lay.addStretch()
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        close_btn = QPushButton("✕  BONDHO KORO")
        close_btn.setStyleSheet(
            f"color: {C.TEXT_DIM}; background: transparent; padding: 4px;")
        close_btn.clicked.connect(self._do_close)
        outer.addWidget(close_btn)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)
        self._tick()

    # ── worker results (Qt thread via _worker_done) ──────────────────────────

    def _on_worker_done(self, kind: str, msg: str) -> None:
        self._status_lbl.setText(str(msg or "")[:300])
        if kind == "phone_screen":
            self._load_phone_img(force=True)
        elif kind == "pc_screen":
            self._load_pc_img(force=True)
        elif kind == "location":
            self._tick()

    # ── actions ──────────────────────────────────────────────────────────────

    def _on_refresh_phone(self) -> None:
        self._status_lbl.setText("⏳ Phone-ke screen-er jonno bolchi…")

        def _work():
            try:
                from core import jarvis_link
                link = jarvis_link.LINK
                if link is None or not link.paired:
                    res = "📱 Phone pair kora nei — age QR scan koro."
                else:
                    res = link.fetch_phone_screen()
            except Exception as e:
                res = f"Phone screen ante parlam na: {e}"
            self._worker_done.emit("phone_screen", str(res)[:300])

        threading.Thread(target=_work, daemon=True,
                         name="main-agent-phone-screen").start()

    def _on_refresh_pc(self) -> None:
        self._status_lbl.setText("⏳ PC screen nichhi…")

        def _work():
            res = self._capture_pc_screen_sync()
            self._worker_done.emit(
                "pc_screen",
                "🖥️ PC screen nilam." if res else
                "PC screenshot not available — mss/ImageGrab konotai cholche na.")

        threading.Thread(target=_work, daemon=True,
                         name="main-agent-pc-screen").start()

    @staticmethod
    def _capture_pc_screen_sync() -> str:
        """Capture the PC screen to memory/pc_screen.jpg. Reuses the
        jarvis_link capture helper when the link is attached (the same
        helper the phone's screen_req uses); otherwise mss directly.
        Returns the path or ''. Never raises. (Worker thread only.)"""
        try:
            from core import jarvis_link
            link = jarvis_link.LINK
            if link is not None:
                return link.capture_pc_screen()
        except Exception:
            pass
        try:
            import io
            import mss
            from pathlib import Path as _Path
            from PIL import Image
            with mss.mss() as sct:
                shot = sct.grab(sct.monitors[1])
            img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
            img.thumbnail((1280, 1280))
            p = _Path(__file__).resolve().parent.parent / "memory" / "pc_screen.jpg"
            p.parent.mkdir(parents=True, exist_ok=True)
            img.save(str(p), format="JPEG", quality=80)
            return str(p)
        except Exception:
            return ""

    def _on_find_phone(self) -> None:
        self._status_lbl.setText("⏳ Phone-er location khujchi…")

        def _work():
            try:
                from core import jarvis_link
                link = jarvis_link.LINK
                if link is None or not link.paired:
                    res = "location unavailable — phone pair kora nei."
                else:
                    res = link.request_phone_location(timeout=30.0)
            except Exception as e:
                res = f"Location ante parlam na: {e}"
            self._worker_done.emit("location", str(res)[:300])

        threading.Thread(target=_work, daemon=True,
                         name="main-agent-find-phone").start()

    def _on_quick(self, label: str, tool: str, args: dict) -> None:
        try:
            from core.action_queue import enqueue
            qid = enqueue(tool, dict(args or {}))
        except Exception:
            qid = ""
        if qid:
            self._status_lbl.setText(
                f"✅ {label}: queued — Mark will run it (#{qid}).")
        else:
            self._status_lbl.setText(
                f"⚠️ {label}: queue-te dite parlam na — abar try koro.")

    def _on_ask_muse(self) -> None:
        """💬 ASK MUSE — queue Mark's current work to Muse Bridge.

        create_task is a fast config write (no network), so this runs on
        the Qt thread. Never raises — a missing bridge reports as a status
        line, never a crash."""
        try:
            _tid, msg = ask_muse_about_current_work()
        except Exception as e:
            msg = f"⚠️ Muse-ke task pathate parlam na: {e}"
        self._status_lbl.setText(str(msg or "")[:300])

    # ── tick (Qt thread only) ────────────────────────────────────────────────

    def _load_phone_img(self, force: bool = False) -> None:
        try:
            from pathlib import Path
            p = Path(__file__).resolve().parent.parent / "memory" / "phone_screen.jpg"
            if not p.is_file():
                return
            mtime = p.stat().st_mtime
            if not force and mtime == self._phone_mtime:
                return
            self._phone_mtime = mtime
            px = QPixmap(str(p))
            if px.isNull():
                return
            self._phone_img.setPixmap(px.scaled(
                460, 300, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
        except Exception:
            pass

    def _load_pc_img(self, force: bool = False) -> None:
        try:
            from pathlib import Path
            p = Path(__file__).resolve().parent.parent / "memory" / "pc_screen.jpg"
            if not p.is_file():
                return
            mtime = p.stat().st_mtime
            if not force and mtime == self._pc_mtime:
                return
            self._pc_mtime = mtime
            px = QPixmap(str(p))
            if px.isNull():
                return
            self._pc_img.setPixmap(px.scaled(
                460, 300, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
        except Exception:
            pass

    def _tick(self) -> None:
        self._tick_count += 1
        # (1) Mark live status
        try:
            from core.mark_status import snapshot as _mark_snapshot
            ms = _mark_snapshot()
            self._mark_lbl.setText(
                "• Current: " + str(ms.get("current_task") or "Idle") + "\n"
                "• Last reply: " + (str(ms.get("last_response") or "—")[:160])
                + "\n• Queue: " + str(ms.get("queue_len", 0)) + " pending"
                + (f"  •  updated {ms.get('updated_at')}"
                   if ms.get("updated_at") else ""))
        except Exception:
            pass
        # (2) Agents + automation, one line each
        try:
            snap = REGISTRY.snapshot()
            working = [a for a in snap if a.get("status") == "working"]
            done = sum(int(a.get("completed_count") or 0) for a in snap)
            self._agents_lbl.setText(
                "🤖 " + ", ".join(
                    f"{a.get('icon', '')}{a.get('name', '?')}: "
                    f"{a.get('status', 'idle')}"
                    + (f" ({str(a.get('current_task') or '')[:40]})"
                       if a.get("status") == "working" else "")
                    for a in snap)
                + f"  •  {len(working)} working • {done} done total")
        except Exception:
            pass
        try:
            from core.automation import ENGINE
            tasks = ENGINE.list_tasks()
            on = sum(1 for t in tasks if t.get("enabled"))
            nxts = [t.get("next_run") for t in tasks
                    if t.get("enabled") and t.get("next_run")]
            self._auto_lbl.setText(
                f"⚡ {len(tasks)} automation task ({on} on)"
                + (f" • next run ⏭ {_countdown(min(nxts))}"
                   if nxts else " • next run —"))
        except Exception:
            pass
        # 👤 Guest mode — read fresh each tick; never raises.
        try:
            from core.cat09_security import guest_mode_enabled as _gm
            self._guest_lbl.setText("👤 Guest mode ON" if _gm() else "")
        except Exception:
            pass
        # (5) Location — last-known fix (never faked)
        try:
            from core.phone_location import last_fix
            fix = last_fix()
            if fix:
                self._loc_lbl.setText(
                    f"📍 Lat {fix.get('lat')}, Lng {fix.get('lon')} "
                    f"({fix.get('at') or ''})  •  "
                    f"🗺️ google.com/maps?q={fix.get('lat')},{fix.get('lon')}")
            else:
                self._loc_lbl.setText(
                    "📍 Phone-er location jani na ekhono — 'Find phone' chapo; "
                    "phone GPS + Location permission ON thakte hobe.")
        except Exception:
            pass
        # (3)+(4) Screens re-poll every 4 s (tick is 1 s).
        if self._tick_count % 4 == 0:
            self._load_phone_img()
            self._load_pc_img()

    def _do_close(self) -> None:
        self._timer.stop()
        self.hide()
        self.closed.emit()
