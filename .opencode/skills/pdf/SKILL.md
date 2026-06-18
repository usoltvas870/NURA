---
name: pdf
description: Generate and process PDF files using WeasyPrint (NURA stack), pypdf, pdfplumber, and reportlab. Use when creating reports, invoices, or any PDF output.
---

# PDF Processing Guide (NURA)

## NURA Stack
- **WeasyPrint** — генерация PDF из HTML/CSS (основной инструмент)
- **pypdf** — чтение/слияние/разделение PDF
- **pdfplumber** — извлечение текста и таблиц
- **reportlab** — программное создание PDF

## WeasyPrint (основной)

### Генерация из Jinja2 шаблона
```python
from weasyprint import HTML
from jinja2 import Environment, FileSystemLoader

env = Environment(loader=FileSystemLoader("templates/reports"))
template = env.get_template("report.html")
html_content = template.render(data=data)

pdf_bytes = HTML(string=html_content).write_pdf()
```

### Сохранение в файл
```python
HTML(string=html_content).write_pdf("output/report.pdf")
```

### CSS для печати
```css
@page {
    size: A4;
    margin: 20mm 15mm;
    @top-center {
        content: element(header);
    }
    @bottom-center {
        content: counter(page);
    }
}

.page-break {
    page-break-before: always;
}
```

### Изображения и QR-коды
```python
import qrcode
from io import BytesIO
import base64

qr = qrcode.make("https://nura-ai.ru")
buf = BytesIO()
qr.save(buf, format="PNG")
qr_b64 = base64.b64encode(buf.getvalue()).decode()

# В шаблоне: <img src="data:image/png;base64,{{ qr_b64 }}">
```

## pypdf — базовые операции

### Чтение и извлечение текста
```python
from pypdf import PdfReader

reader = PdfReader("document.pdf")
print(f"Pages: {len(reader.pages)}")
text = ""
for page in reader.pages:
    text += page.extract_text()
```

### Слияние PDF
```python
from pypdf import PdfWriter, PdfReader

writer = PdfWriter()
for pdf_file in ["doc1.pdf", "doc2.pdf"]:
    reader = PdfReader(pdf_file)
    for page in reader.pages:
        writer.add_page(page)

with open("merged.pdf", "wb") as output:
    writer.write(output)
```

### Разделение PDF
```python
reader = PdfReader("input.pdf")
for i, page in enumerate(reader.pages):
    writer = PdfWriter()
    writer.add_page(page)
    with open(f"page_{i+1}.pdf", "wb") as output:
        writer.write(output)
```

### Метаданные
```python
reader = PdfReader("document.pdf")
meta = reader.metadata
print(f"Title: {meta.title}, Author: {meta.author}")
```

### Ротация страниц
```python
page = reader.pages[0]
page.rotate(90)
writer.add_page(page)
```

## pdfplumber — текст и таблицы

### Извлечение текста
```python
import pdfplumber

with pdfplumber.open("document.pdf") as pdf:
    for page in pdf.pages:
        text = page.extract_text()
```

### Извлечение таблиц
```python
with pdfplumber.open("document.pdf") as pdf:
    all_tables = []
    for page in pdf.pages:
        tables = page.extract_tables()
        for table in tables:
            if table:
                df = pd.DataFrame(table[1:], columns=table[0])
                all_tables.append(df)
```

## reportlab — создание PDF
```python
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

doc = SimpleDocTemplate("report.pdf", pagesize=A4)
styles = getSampleStyleSheet()
story = [
    Paragraph("Report Title", styles["Title"]),
    Spacer(1, 12),
    Paragraph("Body text", styles["Normal"]),
]
doc.build(story)
```

### Важно: подстрочные/надстрочные символы
```python
# Никогда не используй Unicode ₀₁₂₃ в reportlab — баг с рендерингом
# Используй XML-теги:
chemical = Paragraph("H<sub>2</sub>O", styles["Normal"])
squared = Paragraph("x<super>2</super>", styles["Normal"])
```

## Парольная защита
```python
from pypdf import PdfReader, PdfWriter

reader = PdfReader("input.pdf")
writer = PdfWriter()
for page in reader.pages:
    writer.add_page(page)
writer.encrypt("userpass", "ownerpass")
with open("encrypted.pdf", "wb") as output:
    writer.write(output)
```

## Шпаргалка
| Задача | Инструмент | Код |
|--------|-----------|-----|
| Генерация из HTML | WeasyPrint | `HTML(string=...).write_pdf()` |
| Чтение текста | pypdf | `page.extract_text()` |
| Таблицы | pdfplumber | `page.extract_tables()` |
| Создание с нуля | reportlab | `SimpleDocTemplate().build()` |
| Слияние | pypdf | `PdfWriter().add_page()` |
| Шифрование | pypdf | `writer.encrypt()` |
