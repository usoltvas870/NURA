# PWA Page Contracts

Этот документ описывает наблюдаемые контракты активных страниц PWA. Визуальные ограничения находятся в [PWA North Star Design](PWA_NORTH_STAR_DESIGN.md), инженерные — в [PWA Implementation Rules](PWA_IMPLEMENTATION_RULES.md).

## Shared shell

Страницы используют бренд/header там, где он присутствует, tabbar с текущими пунктами навигации и общую auth-modal интеграцию. Home, Tarot, Chat и Profile имеют переключатель темы; их markup и CSS-классы могут различаться. Общий контракт — сохранять `data-theme`, текущее поведение переключателя и доступную `aria-label`. Install UI через `pwa-install.js` подключён только на Home и Tarot: в standalone он не показывается; iOS 15+ один раз за сессию открывает `#pwa-ios-modal` через 4 s; Chromium ждёт `beforeinstallprompt`; Opera и unknown показывают закрываемый banner через 2.5 s. Закрытие banner и iOS modal сохраняется только на текущую сессию. Markup не обязан быть одинаковым на всех страницах. Диалоги должны сохранять доступную семантику, активацию с клавиатуры и ожидаемое управление фокусом; loading не открывает защищённые действия. Статусные элементы используют `aria-live` там, где это есть в текущем markup.

## Home

Home отображает четыре Quick Actions в responsive 2×2: Matrix/report, Ask NURA, Daily Tarot и Profile/settings. До завершения загрузки они disabled. Matrix использует существующий route/flow; Ask NURA безопасно передаёт предзаполнение в Chat; Daily ведёт к `tarot.html?open=daily`; Profile ведёт на активную profile route. Точный guest/free/subscriber результат определяется текущими проверками access state; Profile не переименовывается динамически в «Расклады».

## Ask NURA transport

Основной transport — `chat.html?question=...`, fallback — `localStorage.nura_pending_question`. URL question потребляется один раз и удаляется из URL; fallback очищается после consumption. Вопрос только prefill input: автоматического POST, автоматического decrement квоты и дублирующего prefill нет. Отправка требует явного действия пользователя.

## Tarot

Daily deep-link — `tarot.html?open=daily`. После валидного consumption параметр удаляется; daily detail открывается только когда payload карты доступен. Major Arcana используют номера 1–22, Шут — 22. Сохраняется историческое соглашение `08-justice.png` для «Силы» и `11-strength.png` для «Справедливости». Guest/access flow соответствует текущим guards. Страница не предполагает загрузку всех 22 изображений одновременно.

## Chat

Guest state следует активному auth flow. Предзаполненный Ask NURA вопрос не является сообщением, пока пользователь не нажмёт submit. Free/subscriber доступ и квота берутся из текущего response state. При exhausted quota composer блокируется: при сохранённой истории показываются conversation и quota banner, без истории — limit/service panel с действием Premium на `profile.html#subscription`. Контекст карты использует доступную иллюстрацию; для Шута это `22 → 00-fool.png`. Контракт не заявляет удаление истории или завершённую Telegram-интеграцию.

## Profile

Profile остаётся доступной по активной route. Страница показывает loading, guest, account и error состояния на основе `/web/me`; при `401` показывает guest state, при неудачном обновлении использует последнее подтверждённое состояние, если оно есть. Подтверждение Telegram относится к текущему Profile flow, но не меняет контракты других страниц.

## Ошибки и blocked states

На Home ответ session-check `403` включает blocked mode, а `401` — guest flow. На Tarot и Chat `403` перенаправляет на `/app/?blocked=1`; на Tarot `401` возвращает guest state. Profile показывает существующее состояние с кнопкой retry, а Chat использует текущую обработку ошибки отправки и повторной отправки. При ошибке загрузки карты в аутентифицированном Tarot отображаются «Не удалось загрузить карту» и «Попробуй обновить страницу немного позже.»; detail не открывается до валидного payload, отдельной кнопки retry для карты нет. Неаутентифицированный доступ использует отдельный guest/auth flow. Payment/paywall UI, если он присутствует, не должен сообщать доступ, которого нет.

## Accessibility и responsive

Интерактивные элементы активируются клавиатурой; dialogs сохраняют focus containment/restoration, если реализованы. На поддерживаемых mobile widths нет горизонтального overflow; интерактивные цели сохраняют достаточный размер для мобильного использования, а где это закреплено дизайн- или тестовым контрактом — минимум 44 px. Семантика диалогов и имеющиеся `aria-live` не удаляются. Это тестируемые ожидания, но не заявление о formal WCAG certification.
