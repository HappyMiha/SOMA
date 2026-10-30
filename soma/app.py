"""Native setup, life widget and tray. No task console or application tools."""

import argparse
from pathlib import Path
import sys
import threading

from PySide6.QtCore import QLockFile, QObject, QTimer, Qt, Signal
from PySide6.QtGui import QAction, QColor, QCloseEvent, QIcon, QPainter, QPixmap
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog,
    QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMenu, QMessageBox, QPushButton, QSpinBox, QSystemTrayIcon, QVBoxLayout, QWidget)

from soma import __version__
from soma.config import ModelConfig, app_data_dir, get_api_key, set_api_key


class SetupDialog(QDialog):
    def __init__(self, data_dir, config, parent=None):
        super().__init__(parent)
        self.data_dir, self.config = data_dir, config
        self.setWindowTitle("SOMA — обчислювальний мозок")
        self.setMinimumWidth(510)
        form = QFormLayout(self)
        description = QLabel("Модель отримує знімки екрана для мислення.\n"
            "Особистість і пам’ять залишаються на цьому ПК.\n"
            "Налаштуйте multimodal OpenAI-compatible endpoint із JSON-відповідями.")
        description.setWordWrap(True)
        form.addRow(description)
        self.mode = QComboBox()
        for title, value in [("Віддалена", "remote"), ("Локальна", "local"), ("Віддалена + локальний резерв", "hybrid")]:
            self.mode.addItem(title, value)
        self.mode.setCurrentIndex(max(0, self.mode.findData(config.mode)))
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
        self.consent = QCheckBox("Дозволяю надсилати пікселі екрана налаштованій моделі")
        self.consent.setChecked(bool(config.endpoint or config.local_model))
        for title, widget in [("Режим", self.mode), ("Віддалений endpoint", self.endpoint),
                ("Віддалена модель", self.model), ("Ключ у сховищі ОС", self.key),
                ("Локальний endpoint", self.local_endpoint), ("Локальна модель", self.local_model),
                ("Запитів / хвилину", self.rate)]:
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
            config = ModelConfig(mode=self.mode.currentData(), endpoint=self.endpoint.text().strip(),
                model=self.model.text().strip(), local_endpoint=self.local_endpoint.text().strip(),
                local_model=self.local_model.text().strip(), requests_per_minute=self.rate.value())
            config.validate()
            if self.key.text():
                set_api_key(config.endpoint, self.key.text())
            config.save(self.data_dir)
            self.config = config
            self.accept()
        except Exception as exc:
            self.error.setText(str(exc) if isinstance(exc, ValueError) else
                               "Не вдалося зберегти налаштування або ключ у сховищі ОС")


class Signals(QObject):
    status = Signal(dict)
    stopped = Signal()
    failed = Signal(str)


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


class LifeWidget(QWidget):
    def __init__(self, data_dir, *, smoke_seconds=0, smoke_life=False):
        super().__init__()
        self.data_dir = data_dir
        self.kernel = None
        self.worker = None
        self.store = None
        self._quitting = False
        self._restart = False
        self._restore_archive = None
        self.signals = Signals()
        self.signals.status.connect(self.update_status)
        self.signals.stopped.connect(self.worker_stopped)
        self.signals.failed.connect(self.show_failure)
        self.setWindowTitle("SOMA / SOMIK")
        self.setWindowIcon(soma_icon())
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        self.resize(390, 310)
        layout = QVBoxLayout(self)
        title = QLabel("SOMA  /  SOMIK")
        title.setStyleSheet("font-size:22px; font-weight:600; color:#6d5ce7")
        layout.addWidget(title)
        self.identity_label = QLabel("Одна особистість · неперервна історія")
        self.identity_label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.identity_label)
        self.state_label = QLabel("Перший запуск")
        self.state_label.setStyleSheet("font-weight:600; margin-top:10px")
        self.intention = QLabel("Налаштуйте модель, щоб я могла досліджувати свій ПК.")
        self.intention.setWordWrap(True)
        self.intention.setTextFormat(Qt.TextFormat.PlainText)
        self.detail = QLabel()
        self.detail.setWordWrap(True)
        self.detail.setTextFormat(Qt.TextFormat.PlainText)
        self.detail.setStyleSheet("color:#667085;font-size:11px")
        for label in (self.state_label, self.intention, self.detail):
            layout.addWidget(label)
        self.teach = QPushButton("SOMIK, дивись, я тобі покажу")
        self.teach.setEnabled(False)
        self.teach.clicked.connect(self.toggle_teaching)
        layout.addWidget(self.teach)
        self.sensitive = QCheckBox("Приватний крок — не записувати екран і клавіші")
        self.sensitive.hide()
        self.sensitive.toggled.connect(lambda value: self.kernel and self.kernel.set_sensitive(value))
        layout.addWidget(self.sensitive)
        self.metrics = QLabel()
        self.metrics.setStyleSheet("font-size:10px;color:#667085")
        layout.addWidget(self.metrics)
        controls = QHBoxLayout()
        settings = QPushButton("Модель")
        settings.clicked.connect(self.setup)
        backup = QPushButton("Резервна копія")
        backup.clicked.connect(self.backup)
        controls.addWidget(settings)
        controls.addWidget(backup)
        layout.addLayout(controls)
        restore = QPushButton("Відновити особистість із копії")
        restore.clicked.connect(self.restore)
        layout.addWidget(restore)
        disclaimer = QLabel("Характер і мотивації — поведінкова модель.")
        disclaimer.setStyleSheet("font-size:10px;color:#667085")
        layout.addWidget(disclaimer)
        self.tray = QSystemTrayIcon(soma_icon(), self)
        menu = QMenu()
        show = QAction("Показати SOMA", self)
        show.triggered.connect(self.showNormal)
        quit_action = QAction("Зберегти стан і завершити", self)
        quit_action.triggered.connect(self.shutdown)
        menu.addAction(show)
        menu.addAction(quit_action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: self.showNormal() if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
        self.tray.show()
        if smoke_seconds:
            # A packaged UI smoke probe: no model, hooks, screenshots or input.
            self.state_label.setText("UI smoke test · без введення")
            if smoke_life:
                QTimer.singleShot(0, self.bootstrap)
            QTimer.singleShot(smoke_seconds * 1000, self.shutdown)
        else:
            QTimer.singleShot(0, self.bootstrap)

    def show_failure(self, message):
        self.state_label.setText("Потрібне відновлення")
        self.detail.setText(message)

    def bootstrap(self):
        try:
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
            self.store = MemoryStore(self.data_dir)
            identity = self.store.identity()
            self.identity_label.setText("Особистість " + identity["persona_id"][:12])
            key = get_api_key(config.endpoint) if config.mode in {"remote", "hybrid"} else ""
            provider = ModelProvider(config, key)
            port = HumanInterfacePort()
            recorder = DemonstrationRecorder(self.store, port)
            self.kernel = LifeKernel(self.store, port, provider, recorder, self.signals.status.emit)
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

    def run_life(self):
        try:
            self.kernel.run()
        except Exception as exc:
            self.signals.failed.emit("Пам’ять збережена; запуск зупинено: " + type(exc).__name__)
        finally:
            self.signals.stopped.emit()

    def worker_stopped(self):
        self.kernel = None
        self.worker = None
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
        self.state_label.setText("SOMA спостерігає та вчиться · ЗАПИС" if teaching else
            "SOMA займається своїми справами" if status["state"] == "AWAKE/AUTONOMOUS" else status["state"])
        self.intention.setText(status["intention"])
        self.detail.setText(status["detail"])
        self.teach.setText("Все, продовжуй свої справи" if teaching else "SOMIK, дивись, я тобі покажу")
        self.teach.setEnabled(not self._quitting)
        self.sensitive.setVisible(teaching)
        if not teaching:
            self.sensitive.blockSignals(True)
            self.sensitive.setChecked(False)
            self.sensitive.blockSignals(False)
        data = status["inference"]
        self.metrics.setText(f"Циклів: {status['cycles']} · запитів: {data.get('requests', 0)} · "
            f"{data.get('last_latency_seconds', 0):.1f} с · токенів: "
            f"{data.get('input_tokens', 0) + data.get('output_tokens', 0)} · {data.get('last_route', '')}")

    def toggle_teaching(self):
        if not self.kernel:
            return
        self.teach.setEnabled(False)
        if self.kernel.recorder.active:
            self.kernel.finish_teaching()
        else:
            self.kernel.request_teaching()
            self.detail.setText("Власне введення вже вимкнено; готую видимий запис…")

    def backup(self):
        if not self.store:
            return
        name, _ = QFileDialog.getSaveFileName(self, "Резервна копія особистості", "SOMA-persona.zip", "ZIP (*.zip)")
        if name:
            try:
                self.store.backup(Path(name))
                self.detail.setText("Резервну копію збережено")
            except Exception as exc:
                self.show_failure("Резервну копію не створено: " + type(exc).__name__)

    def restore(self):
        name, _ = QFileDialog.getOpenFileName(self, "Відновити особистість; поточну історію буде збережено поруч", "", "ZIP (*.zip)")
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
            try:
                config = ModelConfig.load(self.data_dir)
                config.validate()
            except Exception:
                config = None
            previous = MemoryStore.restore_backup(archive, self.data_dir)
            if config:
                config.save(self.data_dir)
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
    parser = argparse.ArgumentParser(description="SOMA / SOMIK native desktop")
    parser.add_argument("--data-dir", type=Path, default=None, help="Own-product data directory")
    parser.add_argument("--smoke-seconds", type=int, default=0, help="UI-only packaged smoke test")
    parser.add_argument("--smoke-life", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
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
    server.newConnection.connect(lambda: (server.nextPendingConnection().deleteLater(), widget.showNormal()))
    from soma.session import SessionLifecycle
    lifecycle = SessionLifecycle(widget)
    widget.lifecycle = lifecycle
    app.installNativeEventFilter(lifecycle)
    widget.show()
    result = app.exec()
    lifecycle.close()
    server.close()
    return result


if __name__ == "__main__":
    raise SystemExit(main())
