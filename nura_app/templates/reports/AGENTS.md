# NURA Reports — Agent Rules

## Authority

Product target: `docs/product/NURA_1_0_1_5_PRODUCT_SPEC.md`. Current implementation and known text/PDF gaps: `docs/implementation/current-status.md`. Mixed historical report docs не заменяют code/templates/tests.

## Rendering contract

- Каждый шаблон обязан работать в браузере и WeasyPrint.
- Browser QA не заменяет PDF render QA.
- Проверяй поддержку CSS, page breaks, таблицы, длинные строки и optional Jinja blocks.
- Пользовательский текст всегда экранируй.
- В визуальной задаче не меняй report data schema.
- Full report и mini report тестируй отдельно.

## Redesign workflow

1. Static preview.
2. Одна контрольная глава.
3. Browser render.
4. WeasyPrint render.
5. После проверок — полный шаблон.

Светлый Variant B остаётся approved visual direction. Production redesign выполняется только по отдельной явно заданной задаче.
