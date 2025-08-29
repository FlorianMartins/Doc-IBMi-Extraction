# Doc-IBMi
Documentation for IBMi Dev for GitHub Copilot on VsCode

# IBM i 7.5 Offline Docs (Markdown + PDF)

Pipeline pour extraire la doc IBM i 7.5 (RPG, CL, DDS, SQL) via HTML → Markdown → PDF.

## Usage rapide

- Installer pandoc et wkhtmltopdf
- python -m venv .venv && source .venv/bin/activate
- pip install -r requirements.txt
- make scrape
- Ouvrir outputs/INDEX.md dans VS Code
  EOF
