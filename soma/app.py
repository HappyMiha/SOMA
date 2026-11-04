"""Native setup, life widget and tray. No task console or application tools."""

import argparse
from dataclasses import replace
import os
from pathlib import Path
import sys
import threading
import time

from PySide6.QtCore import QLockFile, QObject, QRect, QRectF, QThread, QTimer, Qt, Signal
from PySide6.QtGui import QAction, QColor, QCloseEvent, QFontDatabase, QIcon, QImage, QPainter, QPen, QPixmap
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog,
    QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMenu, QMessageBox, QPushButton, QSizePolicy, QSpinBox, QSystemTrayIcon, QVBoxLayout, QWidget)

from soma import __version__
from soma.config import (ModelConfig, app_data_dir, detect_local_brain, get_api_key,
                         grounding_space, set_api_key)


class SetupDialog(QDialog):
    def __init__(self, data_dir, config, parent=None):
        super().__init__(parent)
        self.data_dir, self.config = data_dir, config
        self.setWindowTitle("SOMA — обчислювальний мозок")
        self.setMinimumWidth(510)
        form = QFormLayout(self)
        description = QLabel("Модель отримує знімки екрана для мислення.\n"
            "Мешканці SOMA, їхні особистість і пам’ять залишаються на цьому ПК.\n"
            "Налаштуйте multimodal OpenAI-compatible endpoint із JSON-відповідями.")
        description.setWordWrap(True)
        form.addRow(description)
        self.mode = QComboBox()
        for title, value in [("Віддалена", "remote"), ("Локальна", "local"), ("Віддалена + локальний резерв", "hybrid")]:
            self.mode.addItem(title, value)
        self.mode.setCurrentIndex(max(0, self.mode.findData(config.mode)))
        self.remote_api = QComboBox()
        for title, value in [("OpenAI-сумісний API (ключ)", "openai"), ("Codex — вхід ChatGPT", "codex"),
                             ("Claude Code — вхід Claude", "claude")]:
            self.remote_api.addItem(title, value)
        self.remote_api.setCurrentIndex(max(0, self.remote_api.findData(config.remote_api)))
        self.remote_api.setToolTip("Codex і Claude Code використовують ваш наявний вхід у їхніх CLI, "
                                   "з вимкненими інструментами; endpoint і ключ не потрібні")
        self.endpoint = QLineEdit(config.endpoint)
        self.endpoint.setPlaceholderText("https://provider.example/v1")
        self.model = QLineEdit(config.model)
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText("Новий ключ; порожнє поле зберігає наявний")
        self.local_endpoint = QLineEdit(config.local_endpoint)
        self.local_model = QLineEdit(config.local_model)
        self.local_model.setPlaceholderText("Назва завантаженої vision-моделі")
        self.rate = QSpinBox()
        self.rate.setRange(1, 60)
        self.rate.setValue(config.requests_per_minute)
        self.timeout = QSpinBox()
        self.timeout.setRange(5, 900)
        self.timeout.setSuffix(" с")
        self.timeout.setToolTip("Локальна модель на CPU може думати кілька хвилин над одним кадром")
        self.timeout.setValue(config.timeout_seconds)
        self.budget = QSpinBox()
        self.budget.setRange(0, 1_000_000)
        self.budget.setSpecialValueText("без ліміту")
        self.budget.setToolTip("Скільки платних запитів до віддаленої моделі мешканці SOMA можуть зробити за добу")
        self.budget.setValue(config.daily_request_budget)
        self.consent = QCheckBox("Дозволяю надсилати пікселі екрана налаштованій моделі")
        self.consent.setChecked(bool(config.endpoint or config.local_model))
        for title, widget in [("Режим", self.mode), ("Віддалений мозок", self.remote_api),
                ("Віддалений endpoint", self.endpoint),
                ("Віддалена модель", self.model), ("Ключ у сховищі ОС", self.key),
                ("Локальний endpoint", self.local_endpoint), ("Локальна модель", self.local_model),
                ("Запитів / хвилину", self.rate), ("Час на відповідь", self.timeout),
                ("Віддалених запитів / добу", self.budget)]:
            form.addRow(title, widget)
        form.addRow(self.consent)
        self.error = QLabel()
        self.error.setStyleSheet("color: #b42318")
        self.error.setWordWrap(True)
        form.addRow(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def save(self):
        try:
            if not self.consent.isChecked():
                raise ValueError("Потрібна згода на передачу знімків вибраній моделі")
            mode, local_model = self.mode.currentData(), self.local_model.text().strip()
            remote_api = self.remote_api.currentData()
            cli = remote_api != "openai"
            # Keep settings this dialog does not show; adapt grounding to the brain.
            config = replace(self.config, mode=mode, endpoint=self.endpoint.text().strip(),
                model=self.model.text().strip(), local_endpoint=self.local_endpoint.text().strip(),
                local_model=local_model, requests_per_minute=self.rate.value(),
                # Remote providers answer in seconds, and capable remote models
                # read finer screenshots and may spend tokens on reasoning.
                remote_api=remote_api,
                timeout_seconds=(min(self.timeout.value(), 120) if mode == "remote" and not cli
                                 else self.timeout.value()),
                image_long_edge=max(self.config.image_long_edge, 1600) if mode != "local" else self.config.image_long_edge,
                # Subscription CLIs budget their own output; a local fallback must fit its context.
                max_output_tokens=4096 if mode != "local" and not cli else self.config.max_output_tokens,
                daily_request_budget=self.budget.value(),
                # The local brain can carry the routine only beside a remote one.
                routine_on_local=self.config.routine_on_local and mode == "hybrid",
                # The 0..1000 grid suits CLI brains and a Qwen-VL fallback alike.
                coordinate_space=("per_mille" if cli and mode != "local" else
                                  grounding_space(local_model if mode == "local" else self.model.text())))
            config.validate()
            if self.key.text() and not cli:
                set_api_key(config.endpoint, self.key.text())
            config.save(self.data_dir)
            self.config = config
            self.accept()
        except Exception as exc:
            self.error.setText(str(exc) if isinstance(exc, ValueError) else
                               "Не вдалося зберегти налаштування або ключ у сховищі ОС")


PASSWORD_PLACE_TITLES = [("У сховищі SOMA (набирається клавіатурою)", "vault"),
                         ("Збережено в браузері (автозаповнення)", "browser"), ("Невідомо", "unknown")]


class AccountEditDialog(QDialog):
    """One of an inhabitant's accounts, as the owner sets it right."""

    def __init__(self, accounts, account=None, parent=None, name="SOMIK"):
        from soma.accounts import STATUSES
        super().__init__(parent)
        self.accounts, self.account = accounts, account or {}
        self.setWindowTitle(f"Акаунт {name}")
        self.setMinimumWidth(460)
        form = QFormLayout(self)
        self.service = QLineEdit(self.account.get("service", ""))
        self.login = QLineEdit(self.account.get("login", ""))
        self.status = QComboBox()
        for status in STATUSES:
            self.status.addItem(status, status)
        self.status.setCurrentIndex(max(0, self.status.findData(self.account.get("status", "active"))))
        self.place = QComboBox()
        for title, value in PASSWORD_PLACE_TITLES:
            self.place.addItem(title, value)
        self.place.setCurrentIndex(max(0, self.place.findData(self.account.get("password_in", "unknown"))))
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("Новий пароль у сховище; порожнє поле нічого не змінює")
        self.note = QLineEdit(self.account.get("note", ""))
        for title, widget in [("Сервіс", self.service), ("Логін / e-mail", self.login), ("Стан", self.status),
                              ("Де пароль", self.place), ("Пароль", self.password), ("Примітка", self.note)]:
            form.addRow(title, widget)
        self.error = QLabel()
        self.error.setStyleSheet("color: #b42318")
        form.addRow(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def save(self):
        try:
            service, login = self.service.text().strip(), self.login.text().strip()
            if not service or not login:
                raise ValueError("Потрібні сервіс і логін")
            place = self.place.currentData()
            if place == "vault" and not self.password.text() and self.account.get("password_in") != "vault":
                raise ValueError("Щоб пароль був у сховищі, введіть його")
            account_id = self.accounts.record(service, login, status=self.status.currentData(),
                                              note=self.note.text().strip() or None,
                                              password_in=None if place == "vault" else place,
                                              account_id=self.account.get("id"), by="owner")
            if self.password.text():
                self.accounts.set_secret(account_id, self.password.text(), by="owner")
            self.accept()
        except Exception as exc:
            self.error.setText(str(exc) if isinstance(exc, ValueError) else type(exc).__name__)


class AccountsDialog(QDialog):
    """An inhabitant's accounts for the owner: logins, status and passwords, to set
    right what the inhabitant cannot. While it is open the inhabitant neither looks nor acts."""

    def __init__(self, accounts, parent=None, name="SOMIK"):
        from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableWidget
        super().__init__(parent)
        self.accounts, self.name = accounts, name
        self.setWindowTitle(f"{name} — мої акаунти")
        self.setMinimumSize(760, 320)
        layout = QVBoxLayout(self)
        note = QLabel(f"Поки це вікно відкрите, {name} не дивиться на екран і нічого не робить. "
                      "Паролі — у сховищі облікових даних Windows; жоден мозок їх не бачить.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Сервіс", "Логін", "Стан", "Пароль", "Примітка"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.doubleClicked.connect(self.edit)
        layout.addWidget(self.table)
        row = QHBoxLayout()
        for title, handler in [("Показати пароль", self.reveal), ("Змінити…", self.edit),
                               ("Додати…", self.add), ("Закрити", self.accept)]:
            button = QPushButton(title)
            button.clicked.connect(handler)
            row.addWidget(button)
        layout.addLayout(row)
        self._hide = QTimer(self)
        self._hide.setSingleShot(True)
        self._hide.timeout.connect(self.refresh)
        self.refresh()

    def refresh(self):
        from PySide6.QtWidgets import QTableWidgetItem
        places = {value: title for title, value in PASSWORD_PLACE_TITLES}
        self.rows = self.accounts.list()
        self.table.setRowCount(len(self.rows))
        for index, account in enumerate(self.rows):
            place = account.get("password_in", "unknown")
            for column, text in enumerate([account.get("service", ""), account.get("login", ""),
                                           account.get("status", ""),
                                           "••••••••" if place == "vault" else places.get(place, place),
                                           account.get("note", "")]):
                self.table.setItem(index, column, QTableWidgetItem(text))
        self.table.resizeColumnsToContents()

    def selected(self):
        index = self.table.currentRow()
        return self.rows[index] if 0 <= index < len(self.rows) else None

    def reveal(self):
        from PySide6.QtWidgets import QTableWidgetItem
        account = self.selected()
        if account is None:
            return
        if account.get("password_in") != "vault":
            QMessageBox.information(self, "Пароль", "Цього пароля немає у сховищі SOMA. Якщо він збережений у "
                                    "браузері — Firefox: about:logins. Його можна внести сюди через «Змінити…».")
            return
        secret = self.accounts.secret(account["id"]) or "(у сховищі порожньо)"
        self.table.setItem(self.table.currentRow(), 3, QTableWidgetItem(secret))
        self._hide.start(30_000)  # Hidden again after half a minute.

    def edit(self):
        account = self.selected()
        if account is not None and AccountEditDialog(self.accounts, account, self, self.name).exec():
            self.refresh()

    def add(self):
        if AccountEditDialog(self.accounts, None, self, self.name).exec():
            self.refresh()


TRUST_TITLES = [("Підтверджено", "confirmed"), ("Лише заявлено", "claimed"), ("Невідомо", "unknown")]
OWNER_SAYS = "my owner said so"


class PersonEditDialog(QDialog):
    """Someone an inhabitant knows, as the owner sets it right; what the owner says here counts as confirmed."""

    def __init__(self, people, person=None, parent=None, name="SOMIK"):
        from PySide6.QtWidgets import QPlainTextEdit
        super().__init__(parent)
        self.people, self.person = people, person or {}
        self.setWindowTitle(f"Людина, яку знає {name}")
        self.setMinimumWidth(480)
        form = QFormLayout(self)
        self.name = QLineEdit(self.person.get("name", ""))
        self.relation = QLineEdit(self.person.get("relation", ""))
        self.relation.setPlaceholderText("напр. мій власник, Міха / син Міхи")
        self.trust = QComboBox()
        for title, value in TRUST_TITLES:
            self.trust.addItem(title, value)
        self.trust.setCurrentIndex(max(0, self.trust.findData(self.person.get("trust", "confirmed" if not person
                                                                                    else "unknown"))))
        self.accounts = QPlainTextEdit("\n".join(f"{a['service']}: {a['handle']}" for a in self.person.get("accounts", [])))
        self.accounts.setPlaceholderText("Discord: some_handle\nTelegram: …")
        self.accounts.setFixedHeight(72)
        self.note = QLineEdit()
        self.note.setPlaceholderText("Нова нотатка від вас (необов'язково)")
        for title, widget in [("Ім'я", self.name), (f"Хто це для {name}", self.relation), ("Довіра", self.trust),
                              ("Акаунти (по рядку: сервіс: нік)", self.accounts), ("Нотатка", self.note)]:
            form.addRow(title, widget)
        self.error = QLabel()
        self.error.setStyleSheet("color: #b42318")
        form.addRow(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def save(self):
        try:
            accounts = []
            for line in self.accounts.toPlainText().splitlines():
                if line.strip():
                    service, _, handle = line.partition(":")
                    if not service.strip() or not handle.strip():
                        raise ValueError("Акаунт пишіть так: сервіс: нік")
                    accounts.append({"service": " ".join(service.split()), "handle": handle.strip()})
            update = {"name": self.name.text().strip() or None, "relation": self.relation.text().strip() or None,
                      "trust": self.trust.currentData(), "note": self.note.text().strip() or None}
            if self.person.get("id"):
                update["person"] = self.person["id"]
            if update["trust"] == "confirmed":
                update["evidence"] = OWNER_SAYS
            person_id = self.people.record({key: value for key, value in update.items() if value is not None},
                                           by="owner")
            if accounts != self.person.get("accounts", []):
                self.people.set_accounts(person_id, accounts, by="owner")
            self.accept()
        except Exception as exc:
            self.error.setText(str(exc) if isinstance(exc, ValueError) else type(exc).__name__)


class PeopleDialog(QDialog):
    """The people an inhabitant knows and the inhabitant's notes about them, for the owner to read and set right."""

    def __init__(self, people, parent=None, name="SOMIK"):
        from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QListWidget, QTableWidget
        super().__init__(parent)
        self.people, self.name = people, name
        self.setWindowTitle(f"{name} — люди, яких я знаю")
        self.setMinimumSize(780, 460)
        layout = QVBoxLayout(self)
        note = QLabel(f"Кого знає {name}, хто вони одне одному, їхні акаунти й нотатки {name} про них. "
                      f"Ваші зміни тут вважаються підтвердженими. Поки вікно відкрите, {name} не дивиться на екран.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Ім'я", "Хто це", "Довіра", "Акаунти"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.doubleClicked.connect(self.edit)
        self.table.itemSelectionChanged.connect(self.show_notes)
        layout.addWidget(self.table, 3)
        heading = QLabel("Нотатки")
        heading.setStyleSheet("font-weight: 700")
        layout.addWidget(heading)
        self.notes = QListWidget()
        layout.addWidget(self.notes, 2)
        row = QHBoxLayout()
        for title, handler in [("Змінити…", self.edit), ("Додати людину…", self.add),
                               ("Прибрати нотатку", self.forget), ("Закрити", self.accept)]:
            button = QPushButton(title)
            button.clicked.connect(handler)
            row.addWidget(button)
        layout.addLayout(row)
        self.refresh()

    def refresh(self):
        from PySide6.QtWidgets import QTableWidgetItem
        from soma.people import latest_news
        trust = {value: title for title, value in TRUST_TITLES}
        self.rows = sorted(self.people.list(), key=latest_news, reverse=True)
        self.table.setRowCount(len(self.rows))
        for index, person in enumerate(self.rows):
            accounts = ", ".join(f"{a['service']}: {a['handle']}" for a in person.get("accounts", []))
            for column, text in enumerate([person.get("name", ""), person.get("relation", ""),
                                           trust.get(person.get("trust", "unknown"), ""), accounts]):
                self.table.setItem(index, column, QTableWidgetItem(text))
        self.table.resizeColumnsToContents()
        self.show_notes()

    def selected(self):
        index = self.table.currentRow()
        return self.rows[index] if 0 <= index < len(self.rows) else None

    def show_notes(self):
        from PySide6.QtWidgets import QListWidgetItem
        self.notes.clear()
        person = self.selected()
        for note in (person or {}).get("notes", []):
            item = QListWidgetItem(f"{note.get('at', '')[:10]}  {note['note']}" + ("  (від вас)" if note.get("by") == "owner" else ""))
            item.setData(Qt.ItemDataRole.UserRole, note["id"])
            self.notes.addItem(item)

    def edit(self):
        person = self.selected()
        if person is not None and PersonEditDialog(self.people, person, self, self.name).exec():
            self.refresh()

    def add(self):
        if PersonEditDialog(self.people, None, self, self.name).exec():
            self.refresh()

    def forget(self):
        item = self.notes.currentItem()
        person = self.selected()
        if item is not None and person is not None:
            self.people.record({"person": person["id"], "forget_note": item.data(Qt.ItemDataRole.UserRole)}, by="owner")
            self.refresh()


def own_windows():
    """Physical-pixel frames of SOMA's visible Qt windows, and whether one is active.

    Covers the widget, tray menu, setup and file dialogs: every dialog here is a
    Qt widget (no native dialogs), so the product shell is fully known to Qt."""
    rectangles = []
    for window in QApplication.topLevelWidgets():
        if not window.isVisible() or window.isMinimized():
            continue
        frame, screen = window.frameGeometry(), window.screen()
        ratio, origin = screen.devicePixelRatio(), screen.geometry().topLeft()
        # Qt keeps each screen's native origin; offsets inside it are scaled.
        left = origin.x() + round((frame.left() - origin.x()) * ratio)
        top = origin.y() + round((frame.top() - origin.y()) * ratio)
        rectangles.append((left, top, left + round(frame.width() * ratio), top + round(frame.height() * ratio)))
    # The widget itself never takes keyboard focus (WindowDoesNotAcceptFocus), so
    # keystrokes can only land in SOMA's shell through a dialog or the tray menu.
    active = QApplication.activeWindow()
    keyboard = (QApplication.activeModalWidget() is not None or QApplication.activePopupWidget() is not None
                or isinstance(active, QDialog))
    return rectangles, keyboard


def own_looks():
    """How SOMA's visible Qt windows look now, with their physical frames, so her hand can tell
    her own window from something else lying in front of it (pixels only, of her own windows)."""
    looks = []
    for window in QApplication.topLevelWidgets():
        if not window.isVisible() or window.isMinimized():
            continue
        frame, screen = window.frameGeometry(), window.screen()
        ratio, origin = screen.devicePixelRatio(), screen.geometry().topLeft()
        left = origin.x() + round((frame.left() - origin.x()) * ratio)
        top = origin.y() + round((frame.top() - origin.y()) * ratio)
        image = window.grab().toImage().convertToFormat(QImage.Format.Format_RGBX8888)
        rectangle = (left, top, left + round(frame.width() * ratio), top + round(frame.height() * ratio))
        looks.append((rectangle, image.width(), image.height(),
                      bytes(image.constBits())[:image.bytesPerLine() * image.height()]))
    return looks


SHELL_DIALOG = QFileDialog.Option.DontUseNativeDialog


def vision_selftest(report: Path) -> int:
    """Packaging check: the bundled OCR reads a rendered line (no screen, no input)."""
    import json
    from io import BytesIO
    from PIL import Image, ImageDraw, ImageFont
    from soma.core import ScreenFrame
    from soma.vision import ScreenReader
    image = Image.new("RGB", (900, 160), "white")
    ImageDraw.Draw(image).text((30, 50), "Write a message", fill="black", font=ImageFont.load_default(48))
    buffer = BytesIO()
    image.save(buffer, "PNG")
    started = time.monotonic()
    reader = ScreenReader()
    lines = reader.read(ScreenFrame(buffer.getvalue(), 900, 160)) if reader.available else []
    passed = any("message" in line["text"].lower() for line in lines)
    report.write_text(json.dumps({"passed": passed, "available": reader.available,
                                  "lines": [line["text"] for line in lines],
                                  "seconds": round(time.monotonic() - started, 2)}), "utf-8")
    return 0 if passed else 1


def wait_for_exit(pid: int, seconds: float) -> bool:
    """Wait until SOMA's own previous process (its PID from SOMA's lock file) is gone."""
    if pid <= 0 or pid == os.getpid():
        return True
    if sys.platform == "win32":
        import ctypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = ctypes.c_void_p
        handle = kernel32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE only
        if not handle:
            return True  # Already gone.
        try:
            return kernel32.WaitForSingleObject(ctypes.c_void_p(handle), int(seconds * 1000)) == 0
        finally:
            kernel32.CloseHandle(ctypes.c_void_p(handle))
    deadline = time.monotonic() + seconds
    while Path(f"/proc/{pid}").exists():
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.1)
    return True


class Signals(QObject):
    status = Signal(dict)
    stopped = Signal()
    failed = Signal(str)
    make_way = Signal()
    health = Signal(object)


STEP_ASIDE_MS = 3 * 60 * 1000  # how long the widget stays out of her way before it goes back


def soma_icon():
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#6d5ce7"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(4, 4, 56, 56)
    painter.setBrush(QColor("#ffffff"))
    painter.drawEllipse(19, 24, 7, 7)
    painter.drawEllipse(38, 24, 7, 7)
    painter.end()
    return QIcon(pixmap)


# Fluent-like, opaque cards for light and dark Windows themes.
WIDGET_THEMES = {
    "light": {"card": "#fdfcff", "border_ref": "00E6DFEB", "text": "#16131f", "muted": "#6e6880",
              "hover": "#f1edf8", "pressed": "#e6e0f3", "accent": "#5b3df5", "accent_hover": "#4c2fe6",
              "accent_pressed": "#3f22d1", "on_accent": "#ffffff", "disabled": "#ebe7f3"},
    "dark": {"card": "#1b1924", "border_ref": "00403646", "text": "#f4f1fb", "muted": "#a9a3bb",
             "hover": "#2a2735", "pressed": "#353141", "accent": "#8c74ff", "accent_hover": "#9d88ff",
             "accent_pressed": "#7a60f5", "on_accent": "#ffffff", "disabled": "#2a2735"},
}
FEELING_COLORS = {"calm": "#0ea5e9", "dreamy": "#6366f1", "curious": "#0891b2", "joyful": "#eab308",
                  "excited": "#f97316", "focused": "#2563eb", "tired": "#64748b", "sad": "#3b82f6",
                  "confused": "#8b5cf6", "proud": "#d97706", "lonely": "#64748b", "playful": "#ec4899",
                  "anxious": "#ef4444", "grateful": "#16a34a"}
AVATAR_SIZE = (304, 144)     # the card's full inner width: 228×108 art pixels at 150 %
STOP_DELAY = 3.0             # seconds before "Все, продовжуй" answers, so a second click cannot end a showing
TEACH_ICON = "👁"
INTENTION_LINES = 4          # what she does, on the compact card; all of it under "•••"
# The world's self-diagnosis (soma.health): a dot per part, its colour how it works.
HEALTH_COLORS = {"ok": "#22c55e", "busy": "#3b82f6", "idle": "#9ca3af", "warn": "#f59e0b", "problem": "#ef4444"}
ACTIVITY_WORDS = {"thinking": "думає", "acting": "діє", "resting": "відпочиває", "learning": "вчиться",
                  "asleep": "спить", "recovering": "відновлюється", "waking": "прокидається"}
# Feelings named as nouns: her words about herself are hers to choose.
FEELING_WORDS = {"calm": "спокій", "dreamy": "мрійливість", "curious": "цікавість", "joyful": "радість",
                 "excited": "захват", "focused": "зосередженість", "tired": "втома", "sad": "смуток",
                 "confused": "розгубленість", "proud": "гордість", "lonely": "самотність",
                 "playful": "грайливість", "anxious": "тривога", "grateful": "вдячність"}


class LifeWidget(QWidget):
    """SOMA's widget: the world's own card on its screen, showing the inhabitant who
    holds its body now (SOMIK). data_dir is the world's folder (soma.world)."""

    def __init__(self, data_dir, *, smoke_seconds=0, smoke_life=False):
        super().__init__()
        from soma.world import World
        self.data_dir = data_dir
        self.world = World(data_dir)
        self.inhabitant, self.home = None, None
        self.kernel = None
        self.worker = None
        self.store = None
        self.accounts = None
        self.people = None
        self._quitting = False
        self._restart = False
        self._restore_archive = None
        self.signals = Signals()
        self.signals.status.connect(self.update_status)
        self.signals.stopped.connect(self.worker_stopped)
        self.signals.failed.connect(self.show_failure)
        self.signals.make_way.connect(self.step_aside)
        self.signals.health.connect(self.show_health)
        self.health = None
        self.setWindowTitle("SOMA")
        self.setWindowIcon(soma_icon())
        # Her own small card on her screen: frameless, opaque, rounded. A status
        # window must never steal the keyboard from the program SOMA (or a
        # human) is typing into; its buttons work with the mouse alone.
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint |
                            Qt.WindowType.WindowDoesNotAcceptFocus)
        # Fully opaque (crisp ClearType text); Windows 11 rounds its corners natively.
        # Compact by default: SOMA lives on this same screen, and at 150 %
        # scaling the old 390×230 panel covered a third of the screen's height
        # over the page she was reading. Details open with "•••".
        self.setFixedWidth(332)
        self.appearance = None
        from soma.avatar import AvatarView
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 12)
        layout.setSpacing(6)
        # Her avatar is the widget: the painting of her in her world across the
        # whole card. Her owner found it the wrong way round before — a 72-pixel
        # square for her mood and actions, half the card for a button he never
        # used — so showing her something is now a small eye beside "•••".
        self.avatar = AvatarView(self, *AVATAR_SIZE)
        layout.addWidget(self.avatar)
        header = QHBoxLayout()
        header.setSpacing(6)
        self.name = QLabel("SOMIK")
        self.name.setObjectName("name")
        header.addWidget(self.name)
        header.addStretch()
        self.teach = QPushButton(TEACH_ICON)
        self.teach.setObjectName("teach")
        self.teach.setToolTip("SOMIK, дивись, я тобі покажу")
        self.teach.setAccessibleName("SOMIK, дивись, я тобі покажу")
        self.teach.setFixedSize(34, 26)
        self.teach.setEnabled(False)
        self.teach.clicked.connect(self.toggle_teaching)
        header.addWidget(self.teach)
        self.more = QPushButton("•••")
        self.more.setObjectName("more")
        self.more.setFixedSize(34, 26)
        self.more.setToolTip("Подробиці")
        self.more.clicked.connect(lambda: self.set_expanded(not self._expanded))
        header.addWidget(self.more)
        layout.addLayout(header)
        line = QHBoxLayout()
        line.setSpacing(6)
        self.state_label = QLabel("Перший запуск")
        self.state_label.setObjectName("chip")
        self.feeling = QLabel()
        self.feeling.setObjectName("chip")
        self.feeling.hide()
        for chip in (self.state_label, self.feeling):
            chip.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)  # capsules, never stretched
            line.addWidget(chip)
        line.addStretch(1)
        layout.addLayout(line)
        # What she is doing, across the card under the chips: up to INTENTION_LINES lines on the
        # compact card, all of it in the details. Live, one line beside the chips cut almost every
        # intention ("Keep my hands off Miha's w…") and her owner could not read what she did.
        self.intention = QLabel()
        self.intention.setObjectName("intention")
        self.intention.setTextFormat(Qt.TextFormat.PlainText)
        self.intention.setWordWrap(True)
        layout.addWidget(self.intention)
        # What works right now, one dot per part of the world; every part in full in the details.
        self.health_line = QLabel()
        self.health_line.setObjectName("health")
        self.health_line.setTextFormat(Qt.TextFormat.RichText)
        self.health_line.setWordWrap(True)
        self.health_line.hide()
        layout.addWidget(self.health_line)
        self._intention_text = "Налаштуйте модель, щоб я могла досліджувати свій ПК."
        self.sections = []
        def section(title):
            heading = QLabel(title)
            heading.setObjectName("overline")
            body = QLabel()
            body.setTextFormat(Qt.TextFormat.PlainText)
            body.setWordWrap(True)
            layout.addWidget(heading)
            layout.addWidget(body)
            self.sections.append((heading, body))
            return body
        self.health_full = section("ЩО ПРАЦЮЄ")
        self.health_full.setTextFormat(Qt.TextFormat.RichText)
        self.identity_label = section("ХТО Я")
        self.identity_label.setText("Одна особистість · неперервна історія")
        self.world_theme = section("МІЙ СВІТ")  # her theme; self.world is SOMA itself
        self.world_theme.setObjectName("quote")
        self.feeling_words = section("ЩО ВІДЧУВАЮ")
        self.feeling_words.setObjectName("quote")
        self.detail = QLabel()
        self.detail.setWordWrap(True)
        self.detail.setTextFormat(Qt.TextFormat.PlainText)
        self.detail.setObjectName("small")
        layout.addWidget(self.detail)
        self.sensitive = QCheckBox("Приватний крок — не записувати екран і клавіші")
        self.sensitive.hide()
        self.sensitive.toggled.connect(lambda value: self.kernel and self.kernel.set_sensitive(value))
        layout.addWidget(self.sensitive)
        self.metrics = QLabel()
        self.metrics.setObjectName("small")
        layout.addWidget(self.metrics)
        self.apply_theme()
        QApplication.styleHints().colorSchemeChanged.connect(lambda *_: self.apply_theme())
        self._drag = None
        self._expanded = True
        self.set_expanded(False)
        # The widget is how a human shows SOMA something, not a control panel.
        # Product housekeeping lives in the tray menu, out of her way.
        self.tray = QSystemTrayIcon(soma_icon(), self)
        menu = QMenu()
        self._inhabitant_actions = {}  # titled with the inhabitant's name once the world is settled
        for key, title, handler in [("show", "Показати SOMA", self.showNormal), ("model", "Мозки SOMA…", self.setup),
                                    ("accounts", "Акаунти SOMIK…", self.show_accounts),
                                    ("people", "Люди SOMIK…", self.show_people),
                                    ("backup", "Резервна копія SOMIK…", self.backup),
                                    ("restore", "Відновити SOMIK із копії…", self.restore),
                                    ("quit", "Зберегти стан і завершити", self.shutdown)]:
            action = QAction(title, self)
            action.triggered.connect(handler)
            menu.addAction(action)
            self._inhabitant_actions[key] = action
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: self.showNormal() if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
        self.tray.show()
        from soma.body import OwnInterface
        self.own_interface = OwnInterface()
        # Timers keep firing inside modal dialogs' nested event loops.
        self._own_timer = QTimer(self)
        self._own_timer.timeout.connect(lambda: self.own_interface.publish(*own_windows()))
        self._own_timer.start(250)
        self._look_timer = QTimer(self)
        self._look_timer.timeout.connect(lambda: self.own_interface.publish_looks(own_looks()))
        self._look_timer.start(1000)
        if smoke_seconds:
            # A packaged UI smoke probe: no model, hooks, screenshots or input.
            self.state_label.setText("UI smoke test · без введення")
            if smoke_life:
                QTimer.singleShot(0, self.bootstrap)
            QTimer.singleShot(smoke_seconds * 1000, self.shutdown)
        else:
            QTimer.singleShot(0, self.bootstrap)

    def set_expanded(self, expanded):
        """Compact (her painting and one status line) or with what she does in full,
        who she is, her world, her feeling, details and metrics."""
        if expanded == self._expanded:
            return
        # Grow or shrink from the bottom edge it sits on (see resizeEvent);
        # taken first, because showing a label already resizes the window.
        if self.isVisible():
            frame = self.frameGeometry()
            self._anchor = (frame.bottom(), frame.height() - self.height())  # edge, title-bar height
        self._expanded = expanded
        for label in (self.detail, self.metrics):
            label.setVisible(expanded)
        self._show_sections()
        self.more.setText("—" if expanded else "•••")
        self.show_intention(self._intention_text)
        self.adjustSize()

    def _show_sections(self):
        for heading, body in self.sections:
            visible = self._expanded and bool(body.text())
            heading.setVisible(visible)
            body.setVisible(visible)

    def showEvent(self, event):
        super().showEvent(event)
        if sys.platform == "win32":
            # Windows 11 rounds the corners of SOMA's own card and draws its hairline border.
            try:
                import ctypes
                handle = int(self.winId())
                rounded, border = ctypes.c_int(2), ctypes.c_int(int(self._colors["border_ref"], 16))
                ctypes.windll.dwmapi.DwmSetWindowAttribute(handle, 33, ctypes.byref(rounded), 4)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(handle, 34, ctypes.byref(border), 4)
            except Exception:
                pass  # Square corners on older systems; the card stays the same.

    def apply_theme(self):
        """Light or dark with Windows, in the Fluent manner; always opaque."""
        dark = QApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
        self._colors = WIDGET_THEMES["dark" if dark else "light"]
        c = self._colors
        families = set(QFontDatabase.families())
        text = "Segoe UI Variable Text" if "Segoe UI Variable Text" in families else "Segoe UI"
        display = "Segoe UI Variable Display" if "Segoe UI Variable Display" in families else text
        self.setStyleSheet(f"""
            QWidget {{ font-family: '{text}'; font-size: 13px; color: {c['text']}; }}
            QLabel#name {{ font-family: '{display}'; font-size: 20px; font-weight: 700; letter-spacing: 0.5px; }}
            QLabel#intention {{ font-size: 13px; color: {c['text']}; }}
            QLabel#chip {{ border-radius: 9px; padding: 1px 7px; font-size: 11px; font-weight: 700; }}
            QLabel#overline {{ color: {c['muted']}; font-size: 10px; font-weight: 700; letter-spacing: 1.2px;
                               margin-top: 2px; }}
            QLabel#quote {{ font-family: '{display}'; font-size: 14px; font-weight: 600; }}
            QLabel#small {{ color: {c['muted']}; font-size: 11px; }}
            QLabel#health {{ color: {c['muted']}; font-size: 11px; }}
            QPushButton#more {{ border: none; color: {c['muted']}; font-size: 12px; font-weight: 800;
                                border-radius: 13px; background: {c['hover']}; }}
            QPushButton#more:hover {{ background: {c['pressed']}; }}
            QPushButton#teach {{ border: none; color: {c['muted']}; font-size: 14px; border-radius: 13px;
                                 background: {c['hover']}; padding: 0; }}
            QPushButton#teach:hover {{ background: {c['pressed']}; color: {c['accent']}; }}
            QPushButton#teach:disabled {{ color: {c['disabled']}; }}
            QPushButton#teach[recording="true"] {{ background: #e11d48; color: #ffffff; padding: 0 12px;
                                                   font-family: '{display}'; font-size: 13px; font-weight: 700; }}
            QCheckBox {{ color: {c['muted']}; font-size: 11px; }}""")
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(self._colors["card"]))
        painter.end()

    def _chip(self, label, color: str):
        """A bold capsule: the colour itself as text on a soft tint of it."""
        tint = QColor(color)
        background = f"rgba({tint.red()},{tint.green()},{tint.blue()},0.16)"
        text = tint.darker(135).name() if self._colors is WIDGET_THEMES["light"] else tint.lighter(135).name()
        label.setStyleSheet(f"background: {background}; color: {text};")

    def step_aside(self):
        """Move to the other side of the screen for a few minutes, out of her way: live, page
        banners' "Close" buttons lay under the widget and her clicks could not reach them."""
        screen = self.screen().availableGeometry() if self.screen() else None
        if screen is None or getattr(self, "_aside_from", None) is not None:
            return
        frame = self.frameGeometry()
        self._aside_from = frame.topLeft()
        on_right = frame.center().x() > screen.center().x()
        x = screen.left() + 12 if on_right else screen.right() - frame.width() - 12
        self._anchor = None
        self.move(x, frame.top())
        self._aside_at = self.pos()
        QTimer.singleShot(STEP_ASIDE_MS, self.step_back)

    def step_back(self):
        origin, self._aside_from = getattr(self, "_aside_from", None), None
        if origin is not None and self.pos() == getattr(self, "_aside_at", None):
            self.move(origin)  # her owner did not move it meanwhile: back to where it was put

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self._drag is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self._anchor = None  # Her owner placed it: it stays where it was put.
            self.move(event.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, event):
        self._drag = None

    def resizeEvent(self, event):
        super().resizeEvent(event)
        anchor = getattr(self, "_anchor", None)
        if anchor is not None:
            # The current height: a queued resize event can carry a stale size.
            bottom, decoration = anchor
            self.move(self.frameGeometry().left(), bottom + 1 - self.height() - decoration)

    def show_look(self):
        """Her avatar, her feeling in a word and, in the details, her world and self in her words."""
        if self.appearance is None:
            return
        try:
            look = self.appearance.current()
        except Exception:
            return  # Her memory is closing; the avatar keeps its last look.
        self.avatar.set_look(look)
        feeling = look.get("feeling")
        self.feeling.setVisible(feeling in FEELING_WORDS)
        if feeling in FEELING_WORDS:
            self.feeling.setText(FEELING_WORDS[feeling])
            self._chip(self.feeling, FEELING_COLORS[feeling])
            self.feeling.setToolTip(look.get("feeling_words", ""))
        self.world_theme.setText(look.get("theme", ""))
        self.feeling_words.setText(look.get("feeling_words", ""))
        if look.get("description"):
            self.identity_label.setText(look["description"])
        self._show_sections()
        self.show_intention(self._intention_text)  # the feeling chip took or gave back room

    def show_intention(self, text):
        self._intention_text = text or ""
        self.intention.setToolTip(self._intention_text)
        shown = self._intention_text if self._expanded else self._fit_lines(self._intention_text, INTENTION_LINES)
        if shown != self.intention.text():
            if self.isVisible():
                frame = self.frameGeometry()
                self._anchor = (frame.bottom(), frame.height() - self.height())  # grow from its corner
            self.intention.setText(shown)
            self.adjustSize()

    def _fit_lines(self, text, lines):
        """The text wrapped across the card, cut with "…" after the given number of lines."""
        self.intention.ensurePolished()  # measured in the card's own font, not the default one
        metrics = self.intention.fontMetrics()
        def height(candidate):
            return metrics.boundingRect(QRect(0, 0, AVATAR_SIZE[0], 10_000), Qt.TextFlag.TextWordWrap,
                                        candidate).height()
        limit = metrics.lineSpacing() * lines + 1
        if height(text) <= limit:
            return text
        words = text.split(" ")
        low, high = 0, len(words)
        while low < high:  # the most words that still fit with the ellipsis
            middle = (low + high + 1) // 2
            if height(" ".join(words[:middle]) + "…") <= limit:
                low = middle
            else:
                high = middle - 1
        return " ".join(words[:low]).rstrip(" ,.;:—-") + "…"

    def show_failure(self, message):
        self.state_label.setText("Потрібне відновлення")
        self.detail.setText(message)
        self.set_expanded(True)  # A failure is shown, not folded away.

    def settle_world(self):
        """The world in shape and the inhabitant who holds its body (SOMIK) known."""
        self.inhabitant = self.world.settle()
        self.home = self.world.home(self.inhabitant)
        name = self.inhabitant["name"]
        self.name.setText(name)
        for key, title in (("accounts", f"Акаунти {name}…"), ("people", f"Люди {name}…"),
                           ("backup", f"Резервна копія {name}…"), ("restore", f"Відновити {name} із копії…")):
            self._inhabitant_actions[key].setText(title)
        self._teach_hint = f"{name}, дивись, я тобі покажу"
        if self.teach.property("recording") is not True:
            self.teach.setToolTip(self._teach_hint)
            self.teach.setAccessibleName(self._teach_hint)

    def bootstrap(self):
        try:
            self.settle_world()
        except Exception as exc:
            # Nothing was changed that is not finished on the next start; the folder is kept as it is.
            self.show_failure("Не вдалося влаштувати мешканця у світі SOMA: " + str(exc)[:200])
            return
        try:
            if not (self.data_dir / "model.json").exists():
                # Installed and started: find a brain already on this PC first.
                detected = detect_local_brain()
                if detected:
                    detected.save(self.data_dir)
            config = ModelConfig.load(self.data_dir)
            config.validate()
        except Exception:
            self.setup()
            return
        self.start_life(config)

    def setup(self):
        if self.kernel:
            self.detail.setText("Для зміни моделі зберігаю поточний стан…")
            self._restart = True
            self.kernel.stop()
            return
        try:
            config = ModelConfig.load(self.data_dir)
        except Exception:
            config = ModelConfig()
        dialog = SetupDialog(self.data_dir, config, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.start_life(dialog.config)

    def start_life(self, config):
        try:
            from soma.body import HumanInterfacePort
            from soma.demonstration import DemonstrationRecorder
            from soma.kernel import LifeKernel
            from soma.memory import MemoryStore
            from soma.provider import ModelProvider
            if self.home is None:
                self.settle_world()
            self.store = MemoryStore(self.home, name=self.inhabitant["name"])
            identity = self.store.identity()
            if identity["persona_id"] != self.inhabitant["id"]:
                # A restored backup of another identity now lives in this home.
                self.inhabitant = self.world.update(self.inhabitant["id"], id=identity["persona_id"])
            self.identity_label.setText(f"{self.inhabitant['name']} · мешканець SOMA · " + identity["persona_id"][:8])
            key = get_api_key(config.endpoint) if config.mode in {"remote", "hybrid"} else ""
            # The world lends its brains and its thinking budget to whoever lives in it.
            provider = ModelProvider(config, key, budget_path=self.data_dir / "thinking-budget.json")
            provider.persona_name = self.inhabitant["name"]
            port = HumanInterfacePort(self.own_interface)
            recorder = DemonstrationRecorder(self.store, port)
            from soma.accounts import Accounts
            from soma.appearance import Appearance
            from soma.imaging import Imaging
            from soma.people import People
            from soma.vision import ScreenReader
            self.accounts = Accounts(self.store, self._vault())
            self.people = People(self.store)
            self.appearance = Appearance(self.store)
            self.show_look()
            provider.scrub = self.accounts.scrub  # No brain ever receives one of her passwords.
            from soma.provider import ollama_root
            from soma.reflex import Reflex
            # The hands' reflex lives in the same local Ollama as the brain (when there is one).
            reflex = (Reflex(ollama_root(config.local_endpoint), config.reflex_model)
                      if config.mode in {"local", "hybrid"} and config.local_api != "openai" else None)
            self.kernel = LifeKernel(self.store, port, provider, recorder, self.signals.status.emit,
                                     reader=ScreenReader(), accounts=self.accounts, appearance=self.appearance,
                                     imaging=Imaging(), people=self.people, reflex=reflex)
            self.kernel.make_way = self.signals.make_way.emit  # the widget steps aside from her hand
            from soma.brain_host import OllamaHost
            from soma.health import Health
            # The world watches its own parts and says plainly what works (and mends a lost GPU).
            self.health = Health(self.data_dir, provider, imaging=self.kernel.imaging, kernel=self.kernel,
                                 host=OllamaHost(), publish=self.signals.health.emit,
                                 journal=self.store.append_event)
            self.health.start()
            if hasattr(self, "lifecycle") and (self.lifecycle.signals.locked or self.lifecycle.signals.sleeping):
                self.kernel.suspend()
            self.worker = threading.Thread(target=self.run_life, name="soma-life", daemon=False)
            self.worker.start()
            self.teach.setEnabled(True)
        except Exception as exc:
            if self.store:
                self.store.close()
                self.store = None
            self.show_failure("Не вдалося запустити: " + type(exc).__name__ + ". Перевірте модель і графічний сеанс.")

    def _vault(self):
        from soma.accounts import KeyringVault
        return KeyringVault(self.inhabitant["id"], shared=self.inhabitant.get("vault") == "shared")

    def run_life(self):
        try:
            self.kernel.run()
        except Exception as exc:
            self.signals.failed.emit("Пам’ять збережена; запуск зупинено: " + type(exc).__name__)
        finally:
            self.signals.stopped.emit()

    def worker_stopped(self):
        if self.health is not None:
            self.health.stop()
            self.health = None
        self.kernel = None
        self.worker = None
        self.appearance = None  # Her memory closes; the avatar keeps its last look.
        if self.store:
            self.store.close()
            self.store = None
        self.teach.setEnabled(False)
        if self._quitting:
            QApplication.instance().quit()
        elif self._restore_archive:
            self.apply_restore()
        elif self._restart:
            self._restart = False
            self.setup()

    def update_status(self, status):
        teaching = status["state"] == "OBSERVE_AND_LEARN"
        activity = ("learning" if teaching else "asleep" if status["state"] == "ASLEEP"
                    else status.get("activity") or "waking")
        from soma.avatar import ACTIVITY_COLORS
        self._chip(self.state_label, ACTIVITY_COLORS.get(activity, "#a78bfa"))
        self.state_label.setText("● " + ("вчиться · запис" if teaching else ACTIVITY_WORDS.get(activity, activity)))
        self.avatar.set_activity(activity, status.get("focus"))
        self.show_look()
        self.show_intention(status["intention"])
        self.detail.setText(status["detail"])
        if self.teach.property("recording") != teaching:
            # While she watches, the eye becomes the red "that's all" a human must find at once.
            # It answers only after a moment: live, her owner's next click landed on it and
            # ended both demonstrations within 1.6 s, before anything was shown.
            if teaching:
                self._stop_ready_at = time.monotonic() + STOP_DELAY
                QTimer.singleShot(int(STOP_DELAY * 1000) + 50, lambda: self.teach.setEnabled(not self._quitting))
            self.teach.setProperty("recording", teaching)
            self.teach.setText("Все, продовжуй" if teaching else TEACH_ICON)
            self.teach.setToolTip("Все, продовжуй свої справи" if teaching else
                                  getattr(self, "_teach_hint", "SOMIK, дивись, я тобі покажу"))
            self.teach.style().unpolish(self.teach)
            self.teach.style().polish(self.teach)
            width = self.teach.fontMetrics().horizontalAdvance(self.teach.text()) + 28 if teaching else 34
            self.teach.setFixedSize(width, 26)
        self.teach.setEnabled(not self._quitting and (not teaching or
                                                      time.monotonic() >= getattr(self, "_stop_ready_at", 0)))
        if self.sensitive.isHidden() == teaching:
            # The privacy switch comes and goes with a demonstration; the card grows
            # and shrinks from the corner it sits in (see resizeEvent).
            if self.isVisible():
                frame = self.frameGeometry()
                self._anchor = (frame.bottom(), frame.height() - self.height())
            self.sensitive.setVisible(teaching)
            self.adjustSize()
        if not teaching:
            self.sensitive.blockSignals(True)
            self.sensitive.setChecked(False)
            self.sensitive.blockSignals(False)
        data = status["inference"]
        self.metrics.setText(f"Циклів: {status['cycles']} · запитів: {data.get('requests', 0)} · "
            f"{data.get('last_latency_seconds', 0):.1f} с · токенів: "
            f"{data.get('input_tokens', 0) + data.get('output_tokens', 0)} · {data.get('last_route', '')}" +
            (f"\nвіддалених сьогодні: {data.get('remote_today', 0)}/{data.get('remote_budget') or '∞'}"
             if data.get("remote_budget") is not None and data.get("remote_today") else "") +
            (f"\n{data['last_error']}" if data.get("last_error") else ""))

    def show_health(self, report):
        """What works right now (soma.health): a line of dots on the card, every part in the details."""
        from html import escape
        parts, remedy = report["parts"], report.get("remedy", "")
        dot = lambda part: f"<span style='color:{HEALTH_COLORS.get(part.state, '#9ca3af')}'>●</span>"
        # The body's state is the activity chip already; it joins the line only when something is off.
        shown = [part for part in parts if part.key != "body" or part.state not in {"ok", "busy"}]
        line = "&nbsp;&nbsp; ".join(f"{dot(part)}&nbsp;{escape(part.short).replace(' ', '&nbsp;')}" for part in shown)
        full = "<br>".join(f"{dot(part)} <b>{escape(part.title)}</b> — {escape(part.detail)}" for part in parts)
        if remedy:
            full += f"<br><i>{escape(remedy)}</i>"
        if line != self.health_line.text():
            if self.isVisible():
                frame = self.frameGeometry()
                self._anchor = (frame.bottom(), frame.height() - self.height())  # grow from its corner
            self.health_line.setText(line)
            self.health_line.setVisible(bool(line))
            self.health_line.setToolTip("\n".join(f"{part.title}: {part.detail}" for part in parts) +
                                        (f"\n{remedy}" if remedy else ""))
            self.adjustSize()
        if full != self.health_full.text():
            self.health_full.setText(full)
            self._show_sections()

    def toggle_teaching(self):
        if not self.kernel:
            return
        self.teach.setEnabled(False)
        if self.kernel.recorder.active:
            self.kernel.finish_teaching()
        else:
            self.kernel.request_teaching()
            self.detail.setText("Власне введення вже вимкнено; готую видимий запис…")

    def show_accounts(self):
        """The inhabitant's accounts for the owner; the inhabitant's eyes stay closed while they are shown."""
        from soma.accounts import Accounts
        from soma.memory import MemoryStore
        store, own = self.store, False
        if store is None:
            if self.home is None:
                self.settle_world()
            store, own = MemoryStore(self.home), True   # Not living right now: open her memory briefly.
        kernel = self.kernel
        if kernel:
            kernel.close_eyes()
        try:
            AccountsDialog(self.accounts if not own else Accounts(store, self._vault()), self,
                           (self.inhabitant or {}).get("name", "SOMIK")).exec()
        except Exception as exc:
            self.show_failure("Акаунти не відкрито: " + type(exc).__name__)
        finally:
            if kernel:
                kernel.open_eyes()
            if own:
                store.close()

    def show_people(self):
        """The people the inhabitant knows, for the owner to read and set right; the inhabitant's eyes rest meanwhile."""
        from soma.memory import MemoryStore
        from soma.people import People
        store, own = self.store, False
        if store is None:
            if self.home is None:
                self.settle_world()
            store, own = MemoryStore(self.home), True   # Not living right now: open her memory briefly.
        kernel = self.kernel
        if kernel:
            kernel.close_eyes()
        try:
            PeopleDialog(self.people if not own else People(store), self,
                         (self.inhabitant or {}).get("name", "SOMIK")).exec()
        except Exception as exc:
            self.show_failure("Людей не відкрито: " + type(exc).__name__)
        finally:
            if kernel:
                kernel.open_eyes()
            if own:
                store.close()

    def backup(self):
        if not self.store:
            return
        who = (self.inhabitant or {}).get("name", "SOMIK")
        name, _ = QFileDialog.getSaveFileName(self, f"Резервна копія {who}", f"{who}-persona.zip", "ZIP (*.zip)",
                                              options=SHELL_DIALOG)
        if name:
            try:
                self.store.backup(Path(name))
                self.detail.setText("Резервну копію збережено")
            except Exception as exc:
                self.show_failure("Резервну копію не створено: " + type(exc).__name__)

    def restore(self):
        name, _ = QFileDialog.getOpenFileName(self, "Відновити особистість; поточну історію буде збережено поруч", "", "ZIP (*.zip)",
                                              options=SHELL_DIALOG)
        if not name:
            return
        self._restore_archive = Path(name)
        if self.kernel:
            self.kernel.stop()
            self.detail.setText("Зупиняю введення й зберігаю стан перед відновленням…")
        else:
            self.apply_restore()

    def apply_restore(self):
        from soma.memory import MemoryStore
        archive, self._restore_archive = self._restore_archive, None
        try:
            if self.home is None:
                self.settle_world()
            # Into the inhabitant's own home; the world's brains and settings stay as they are.
            previous = MemoryStore.restore_backup(archive, self.home)
            self.detail.setText("Особистість відновлено; попередня історія: " + str(previous or "відсутня"))
            self.bootstrap()
        except Exception as exc:
            self.show_failure("Копія не пройшла перевірку; наявну історію збережено: " + type(exc).__name__)

    def shutdown(self):
        self._quitting = True
        if self.kernel:
            self.kernel.stop()
            self.teach.setEnabled(False)
            self.detail.setText("Зберігаю стан; завершую поточний inference…")
        else:
            QApplication.instance().quit()

    def closeEvent(self, event: QCloseEvent):
        if self._quitting:
            event.accept()
        elif QSystemTrayIcon.isSystemTrayAvailable():
            self.hide()
            event.ignore()
        else:
            event.ignore()
            self.shutdown()


def main():
    parser = argparse.ArgumentParser(description="SOMA, a world on this PC, and its inhabitants (SOMIK first)")
    parser.add_argument("--data-dir", type=Path, default=None, help="Own-product data directory")
    parser.add_argument("--smoke-seconds", type=int, default=0, help="UI-only packaged smoke test")
    parser.add_argument("--smoke-life", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--quit", action="store_true",
                        help="Ask the running SOMA to save its state and exit (used by upgrades)")
    parser.add_argument("--vision-selftest", type=Path, default=None, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.vision_selftest:
        return vision_selftest(args.vision_selftest)
    if args.quit:
        # Installers call this; it must never hang them, whatever Qt or the
        # old process does (one unexplained hang was observed live).
        watchdog = threading.Timer(120, lambda: os._exit(1))
        watchdog.daemon = True
        watchdog.start()
        app = QApplication(sys.argv[:1])
        client = QLocalSocket()
        client.connectToServer("soma-desktop-body")
        if not client.waitForConnected(1000):
            return 0  # Nothing is running.
        lock = QLockFile(str(app_data_dir().parent / "SOMA-runtime" / "desktop-body.lock"))
        running_pid = lock.getLockInfo()[0]
        client.write(b"quit")
        client.waitForBytesWritten(1000)
        client.disconnectFromServer()
        # Saving a checkpoint may wait for an in-flight inference to be cancelled.
        for _ in range(600):
            if lock.tryLock(0):
                lock.unlock()
                # The lock is released before the interpreter has finished
                # exiting; an installer must not replace files a moment early.
                return 0 if wait_for_exit(running_pid, 30) else 1
            QThread.msleep(100)
        return 1
    if not 0 <= args.smoke_seconds <= 60:
        parser.error("smoke-seconds must be 0..60")
    if args.smoke_life and not args.smoke_seconds:
        parser.error("smoke-life requires a bounded smoke-seconds duration")
    app = QApplication(sys.argv[:1])
    app.setApplicationName("SOMA")
    app.setApplicationVersion(__version__)
    app.setQuitOnLastWindowClosed(False)
    data_dir = (args.data_dir or app_data_dir()).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    # One body per account/session, even when an alternate data directory is used.
    lock_dir = app_data_dir().parent / "SOMA-runtime"
    lock_dir.mkdir(parents=True, exist_ok=True)
    body_lock = QLockFile(str(lock_dir / "desktop-body.lock"))
    name = "soma-desktop-body"
    if not body_lock.tryLock(50):
        client = QLocalSocket()
        client.connectToServer(name)
        if client.waitForConnected(300):
            client.write(b"show")
            client.waitForBytesWritten(300)
        return 0
    client = QLocalSocket()
    client.connectToServer(name)
    if client.waitForConnected(300):
        client.write(b"show")
        client.waitForBytesWritten(300)
        return 0
    QLocalServer.removeServer(name)
    server = QLocalServer()
    if not server.listen(name):
        return 1
    widget = LifeWidget(data_dir, smoke_seconds=args.smoke_seconds, smoke_life=args.smoke_life)
    def connected():
        connection = server.nextPendingConnection()
        def received():
            # Only two words exist on this local channel; neither reaches cognition.
            message = bytes(connection.readAll())
            widget.shutdown() if message == b"quit" else widget.showNormal()
        connection.readyRead.connect(received)
        connection.disconnected.connect(connection.deleteLater)
    server.newConnection.connect(connected)
    from soma.session import SessionLifecycle
    lifecycle = SessionLifecycle(widget)
    widget.lifecycle = lifecycle
    app.installNativeEventFilter(lifecycle)
    # Bottom-right corner, out of the way of the programs SOMA and people use.
    area = app.primaryScreen().availableGeometry()
    widget.move(area.right() - widget.frameGeometry().width() - 12,
                area.bottom() - widget.frameGeometry().height() - 12)
    widget.show()
    result = app.exec()
    lifecycle.close()
    server.close()
    return result


if __name__ == "__main__":
    raise SystemExit(main())
