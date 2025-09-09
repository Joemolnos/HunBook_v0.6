![License](https://img.shields.io/badge/license-MIT-green)

# Groqbook: Generate entire books in seconds using Groq and Llama3
 
Groqbook is a streamlit app that scaffolds the creation of books from a one-line prompt using Llama3 on Groq. It works well on nonfiction books and generates each chapter within seconds. The app mixes Llama3-8b and Llama3-70b, utilizing the larger model for generating the structure and the smaller of the two for creating the content. Currently, the model only uses the context of the section title to generate the chapter content. In the future, this will be expanded to the fuller context of the book to allow groqbook to generate quality fiction books as well.

---

## Quickstart

### Run locally

1) Set Groq API key (opcionális, de ajánlott):
```
$env:GROQ_API_KEY = 'gsk_...'
```

2) Telepítés:
```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

3) (Windows) GTK runtime lehet szükséges WeasyPrint-hez:
https://github.com/tschoonj/GTK-for-Windows-Runtime-Environment-Installer

4) Indítás:
```
python -m streamlit run main.py
```

## Architecture

- `main.py`: Streamlit belépési pont, UI logika és gombok.
- `ui.py`: Stílus és téma-injektálás (`inject_styles()`).
- `generation.py`: Könyvgenerálás folyamata (`generate_book()`).
- `llm.py`: Groq API hívások (`generate_book_structure()`, `generate_section()`).
- `book.py`: Könyvmodell, tartalom-megjelenítés és Markdown összefűzés.
- `stats.py`: Token/idő statisztikák (összegzés, sebesség).
- `exporting.py`: Export eszközök (TXT/Markdown, PDF WeasyPrint-tel).
- `config.py`: Környezeti változók és Groq kliens inicializálás.
