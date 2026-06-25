# Accounting (Streamlit Frontend)

This project is a **Streamlit frontend** prototype for an accounting system.

## Run

```bash
python -m venv .venv
# Windows PowerShell:
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app.py
```

## Notes

- Current version focuses on **UI/UX and flow** (upload invoice → choose LLM → prompt → analyze → editable result → optional save → evidence/history).
- Persistence uses a local **SQLite** file (`accounting.db`) as a placeholder.

## supabase
-pip install supabase
-.streamlit/config.toml
[supabase]
url = "https://xxxx.supabase.co"
key = "your-anon-key"
-