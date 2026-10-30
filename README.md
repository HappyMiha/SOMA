# SOMA / SOMIK

Одна цифрова особистість у нативному desktop-застосунку. Зовнішній світ доступний
лише через пікселі монітора та події миші/клавіатури. Windows і Linux/X11;
нативний Wayland ще не підтримується.

Це перевірювана початкова реалізація специфікації, а не підтвердження всіх її
acceptance gates. Фактичні перевірки та відкриті вимоги: [TEST_RESULTS](docs/TEST_RESULTS.md).

## Встановлення

Windows 10 версії 2004 (build 19041) або новіша: запустіть
`SOMA-0.1.0-windows-x64-setup.exe`. Пакет містить runtime,
створює ярлики й пропонує автозапуск після входу. Дані особистості зберігаються в
`%LOCALAPPDATA%\SOMA`; оновлення й видалення застосунку їх не стирає.

Linux: встановіть `SOMA-0.1.0-linux-amd64.deb` штатним менеджером пакетів і відкрийте
SOMA з меню в X11-сеансі. Дані: `$XDG_DATA_HOME/soma` або `~/.local/share/soma`.
Пакет додає XDG autostart для GUI-сеансів. Inference keys використовують системне
сховище; для віддаленого ключа на Linux потрібен доступний Secret Service.

Під час першого запуску віджет пропонує віддалений, локальний або гібридний режим.
Вкажіть OpenAI-compatible multimodal base URL (`.../v1`), назву vision-моделі та
за потреби ключ. Локальна модель має бути завантажена у ваш Ollama/LM Studio або
інший сумісний inference server; додайте `/v1` до base URL. Обидва режими готові,
модельних ваг у пакеті немає. Сумісність конкретного endpoint треба перевірити:
потрібні image messages та `response_format: json_object`.

Після налаштування SOMA сама обирає діяльність. «SOMIK, дивись, я тобі покажу»
починає видимий запис навчальної демонстрації й негайно вимикає її власне введення.
Дочекайтеся статусу **ЗАПИС**. Приватний крок вимикає запис і пікселів, і клавіш.
«Все, продовжуй свої справи» зберігає епізод і повертає автономний цикл. «Модель»
зберігає стан перед зміною provider. «Резервна копія» експортує власну пам’ять.
Закриття віджета ховає його в tray; вихід через tray зберігає стан.

Характер і мотивації моделюються; застосунок не заявляє доведену свідомість.

## Розробка й складання

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e '.[dev]'
.\.venv\Scripts\python -m pytest -q --basetemp=artifacts/test-tmp
.\.venv\Scripts\python -m soma
.\.venv\Scripts\python packaging/build.py --iscc .tools/inno/ISCC.exe
```

Linux: `python3 -m venv .venv`, `.venv/bin/pip install -e '.[dev]'`,
`.venv/bin/python packaging/build.py`. PyInstaller builds the runtime and
`dpkg-deb` builds the installer. Build on the target OS; no cross-compilation claim.

Live opt-in owned-window body probe (moves mouse and types in its own test window):
`python tests/desktop_e2e.py --run-desktop`. It is a device integration test, not evidence
of model intelligence or external correspondence. See its `--help` for output path.

Audit records: [upstreams](docs/UPSTREAM_EVALUATION.md),
[architecture](docs/ADR-001-interface-boundary.md),
[stack decision](docs/ADR-002-stack.md), [licenses](docs/LICENSE_AUDIT.md).
The project owner has not yet chosen a source-code license. Development builds
are unsigned; public release signing and the remaining hardware gates are open.
