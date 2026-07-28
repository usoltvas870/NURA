# NURA PWA вЂ” Agent Rules

## Sources

> **STATUS: SUPERSEDED — ARCHIVED**
>
> Preserved only as the pre-migration damaged navigation snapshot.

- Primary visual source: `docs/pwa/PWA_NORTH_STAR_DESIGN.md`.
- UX contracts: `docs/pwa/PWA_PAGE_CONTRACTS.md`.
- Implementation rules: `docs/pwa/PWA_IMPLEMENTATION_RULES.md`.
- Target direction: **NURA Soft Ritual Tarot Premium**, light theme.

Р•СЃР»Рё РґРѕРєСѓРјРµРЅС‚ РѕС‚СЃСѓС‚СЃС‚РІСѓРµС‚, РЅРµ РѕС‚СЃР»РµР¶РёРІР°РµС‚СЃСЏ Git РёР»Рё СЂР°СЃС…РѕРґРёС‚СЃСЏ СЃ РєРѕРґРѕРј, СЃРѕРѕР±С‰Рё РѕР± СЌС‚РѕРј РґРѕ РёР·РјРµРЅРµРЅРёСЏ РїРѕРІРµРґРµРЅРёСЏ.

## Scope and safety

- РќРµ РёСЃРїРѕР»СЊР·СѓР№ dark occult РєР°Рє С†РµР»РµРІРѕРµ РЅР°РїСЂР°РІР»РµРЅРёРµ.
- РќРµ РјРµРЅСЏР№ РЅРµСЃРєРѕР»СЊРєРѕ PWA-СЃС‚СЂР°РЅРёС† Р·Р° РѕРґРЅСѓ РёС‚РµСЂР°С†РёСЋ Р±РµР· РїСЂСЏРјРѕРіРѕ Р·Р°РїСЂРѕСЃР°.
- РЎРѕС…СЂР°РЅСЏР№ `id`, `data-*`, global functions Рё JS hooks.
- Р’ РІРёР·СѓР°Р»СЊРЅРѕР№ Р·Р°РґР°С‡Рµ РЅРµ РјРµРЅСЏР№ auth, payment РёР»Рё install logic.
- РќРµ РІС‹РІРѕРґРё РїРѕР»СЊР·РѕРІР°С‚РµР»СЊСЃРєРёР№ РІРІРѕРґ С‡РµСЂРµР· `innerHTML`; РёСЃРїРѕР»СЊР·СѓР№ Р±РµР·РѕРїР°СЃРЅС‹Рµ DOM APIs Рё escaping.
- Prototype СЃРѕР·РґР°РІР°Р№ С‚РѕР»СЊРєРѕ РІ РёР·РѕР»РёСЂРѕРІР°РЅРЅРѕР№ РґРёСЂРµРєС‚РѕСЂРёРё Рё РЅРµ РїРѕРґРєР»СЋС‡Р°Р№ Рє production Р±РµР· РѕС‚РґРµР»СЊРЅРѕР№ Р·Р°РґР°С‡Рё.
- Manifest Рё service worker Р·Р°С‰РёС‰РµРЅС‹ root approval matrix.

## Required QA after PWA changes

- Viewports: `360Г—800`, `390Г—844`, `430Г—932`.
- Horizontal overflow: РѕС‚СЃСѓС‚СЃС‚РІСѓРµС‚.
- Console errors Рё 404 resources: РѕС‚СЃСѓС‚СЃС‚РІСѓСЋС‚.
- Tabbar, safe-area Рё sticky/fixed СЌР»РµРјРµРЅС‚С‹: РЅРµ РїРµСЂРµРєСЂС‹РІР°СЋС‚ РєРѕРЅС‚РµРЅС‚.
- Mobile keyboard/composer: РїСЂРѕРІРµСЂРёС‚СЊ, РµСЃР»Рё РїСЂРёРјРµРЅРёРјРѕ.
- Guest/full/subscriber states: РїСЂРѕРІРµСЂРёС‚СЊ РІСЃРµ Р·Р°С‚СЂРѕРЅСѓС‚С‹Рµ СЃРѕСЃС‚РѕСЏРЅРёСЏ.
- JS hooks: РїРѕРґС‚РІРµСЂРґРёС‚СЊ СЃРѕС…СЂР°РЅРЅРѕСЃС‚СЊ СЃСЂР°РІРЅРµРЅРёРµРј РґРѕ/РїРѕСЃР»Рµ.

## Image generation

- РЎР»РѕР¶РЅС‹Рµ РґРµРєРѕСЂР°С‚РёРІРЅС‹Рµ РІРёР·СѓР°Р»С‹ РјРѕР¶РЅРѕ РіРµРЅРµСЂРёСЂРѕРІР°С‚СЊ С‡РµСЂРµР· ImageGen С‚РѕР»СЊРєРѕ РїРѕ СЏРІРЅРѕР№ Р·Р°РґР°С‡Рµ.
- РљРЅРѕРїРєРё, layout, РѕР±С‹С‡РЅС‹Рµ РєР°СЂС‚РѕС‡РєРё Рё Р±Р°Р·РѕРІС‹Рµ РёРєРѕРЅРєРё РЅРµ РїСЂРµРІСЂР°С‰Р°Р№ РІ СЂР°СЃС‚СЂРѕРІС‹Рµ РёР·РѕР±СЂР°Р¶РµРЅРёСЏ.
- Generated assets СЃРЅР°С‡Р°Р»Р° СЃРѕС…СЂР°РЅСЏР№ РІ staging/prototype scope.
- РќРµ РґРѕР±Р°РІР»СЏР№ generated assets РІ production Р±РµР· РІРёР·СѓР°Р»СЊРЅРѕРіРѕ СѓС‚РІРµСЂР¶РґРµРЅРёСЏ.
