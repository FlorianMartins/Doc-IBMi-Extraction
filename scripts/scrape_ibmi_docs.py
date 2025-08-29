#!/usr/bin/env python3
import os
import re
import time
import subprocess
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup
import yaml
from tqdm import tqdm

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(BASE_DIR, "config", "sources.yaml")
DATA_DIR = os.path.join(BASE_DIR, "data")
RAW_DIR = os.path.join(DATA_DIR, "raw_html")
MD_DIR = os.path.join(DATA_DIR, "md")
MEDIA_DIR = os.path.join(DATA_DIR, "media")
OUT_DIR = os.path.join(BASE_DIR, "outputs")
PDF_DIR = os.path.join(OUT_DIR, "pdf")

IBM_HOST = "www.ibm.com"

HEADERS = {
    "User-Agent": "ibmi-docs-scraper/1.0 (+for personal offline use)"
}

def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return re.sub(r"-+", "-", text).strip("-") or "doc"

def ensure_dirs():
    for d in [RAW_DIR, MD_DIR, MEDIA_DIR, OUT_DIR, PDF_DIR]:
        os.makedirs(d, exist_ok=True)

def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def get_soup(url):
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return BeautifulSoup(r.text, "lxml"), r.text

def is_same_site(url: str) -> bool:
    try:
        return urlparse(url).netloc == IBM_HOST
    except Exception:
        return False

def extract_toc_links(root_url: str) -> list:
    # IBM Docs TOC souvent dans nav ou aside; fallback: tous liens internes avec ?topic=
    soup, html = get_soup(root_url)
    links = set()

    # Chercher les liens de la table des matières
    for nav_sel in ["nav", "aside", "div#toc", "div.ibm--toc", "div.ibm-toc", "ul", "ol"]:
        for nav in soup.select(nav_sel + " a[href]"):
            href = nav.get("href")
            if not href:
                continue
            full = urljoin(root_url, href)
            if is_same_site(full) and "docs/en/i/7.5" in full:
                links.add(full)

    # Fallback: tous les liens internes pertinents
    if not links:
        for a in soup.select("a[href]"):
            href = a.get("href")
            if not href:
                continue
            full = urljoin(root_url, href)
            if is_same_site(full) and "docs/en/i/7.5" in full:
                links.add(full)

    # Toujours inclure la page racine
    links.add(root_url)

    # Normaliser
    return sorted(links)

def rate_limit(delay):
    time.sleep(delay)

def fetch_and_save(url: str, out_path: str, delay: float):
    if os.path.exists(out_path):
        return
    soup, html = get_soup(url)
    # Optionnel: retirer header/footer/navigation pour alléger
    for sel in ["header", "footer", "nav", "aside", "div.ibm-top", "div.ibm-footer"]:
        for node in soup.select(sel):
            node.decompose()
    # Scripts/styles
    for node in soup(["script", "style", "noscript"]):
        node.decompose()
    cleaned_html = str(soup)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(cleaned_html)
    rate_limit(delay)

def run_pandoc_html_to_md(html_path: str, md_path: str, media_dir: str):
    cmd = [
        "pandoc",
        "--from=html",
        "--to=gfm",
        "--extract-media", media_dir,
        "-s", html_path,
        "-o", md_path,
    ]
    subprocess.run(cmd, check=True)

LANG_GUESSES = [
    # heuristiques simples pour marquer les blocs de code
    (re.compile(r"\bDCL\-S|\bDCL\-P|\b/free\b|\bend\-free\b", re.I), "rpg"),
    (re.compile(r"^\s*(A\s|\A\s+R\s|\s+DSPF|\s+PRTF)", re.I | re.M), "dds"),
    (re.compile(r"^\s*(EXEC\s+SQL|SELECT|INSERT|UPDATE|DELETE|DECLARE)\b", re.I | re.M), "sql"),
    (re.compile(r"^\s*(PGM|DCL|RTV|SND|CHG|WRK|ENDPGM)\b", re.I | re.M), "cl"),
]

def annotate_code_blocks(md_text: str) -> str:
    # Transforme ``` -> ```lang si on détecte la langue
    parts = md_text.split("```")  
    if len(parts) < 3:  
        return md_text  
    new = []  
    i = 0  
    while i < len(parts):  
        if i % 2 == 0:  
            new.append(parts[i])  
        else:  
            code = parts[i]  
            lang = ""  
            for rx, guess in LANG_GUESSES:  
                if rx.search(code):  
                    lang = guess  
                    break  
            if lang:  
                new.append(lang + "\n" + code)  
            else:  
                new.append("\n" + code)  
        i += 1  
    return "```".join(new)

def normalize_headings(md_text: str, title: str, source_url: str, version: str) -> str:
    # Ajoute un frontmatter YAML + Titre H1 + lien source
    front = f"""---
title: "{title}"
version: "{version}"
source: "{source_url}"
generated: "{time.strftime('%Y-%m-%d')}"
---

# {title}

> Source: {source_url}

"""
    # Pandoc a parfois des titres H1 en double; on ne supprime pas agressivement ici
    return front + md_text

def compile_section_pdf(md_files: list, out_pdf: str, pdf_engine: str = "wkhtmltopdf"):
    cmd = [
        "pandoc",
        "--toc",
        "--pdf-engine", pdf_engine,
        "-o", out_pdf
    ] + md_files
    subprocess.run(cmd, check=True)

def main():
    ensure_dirs()
    cfg = load_config()
    delay = 1.0 / cfg.get("rate_limit_per_sec", 1.0)

    index_entries = []

    for section in cfg["sections"]:
        key = section["key"]
        title = section["title"]
        root = section["root_url"]
        print(f"[+] Section: {title}")

        sec_raw_dir = os.path.join(RAW_DIR, key)
        sec_md_dir = os.path.join(MD_DIR, key)
        sec_media_dir = os.path.join(MEDIA_DIR, key)
        os.makedirs(sec_raw_dir, exist_ok=True)
        os.makedirs(sec_md_dir, exist_ok=True)
        os.makedirs(sec_media_dir, exist_ok=True)

        # 1) Découvrir les liens
        links = extract_toc_links(root)
        # Filtrer doublons / ancres
        links = sorted(set(u.split("#")[0] for u in links))

        # 2) Télécharger HTML
        for url in tqdm(links, desc=f"fetch:{key}"):
            fname = slugify(urlparse(url).path + "-" + (urlparse(url).query or ""))
            out_html = os.path.join(sec_raw_dir, f"{fname}.html")
            try:
                fetch_and_save(url, out_html, delay)
            except Exception as e:
                print(f"Warn: fail fetch {url}: {e}")

        # 3) Convertir HTML -> MD
        md_files = []
        for html_file in tqdm(sorted(os.listdir(sec_raw_dir)), desc=f"convert:{key}"):
            if not html_file.endswith(".html"):
                continue
            html_path = os.path.join(sec_raw_dir, html_file)
            md_name = os.path.splitext(html_file)[0] + ".md"
            md_path = os.path.join(sec_md_dir, md_name)
            try:
                run_pandoc_html_to_md(html_path, md_path, sec_media_dir)
                # 4) Nettoyage / normalisation
                with open(md_path, "r", encoding="utf-8") as f:
                    txt = f.read()

                # Récupérer un titre raisonnable depuis le nom de fichier (fallback)
                page_title = title
                m = re.search(r"^#\s+(.+)$", txt, re.M)
                if m:
                    page_title = m.group(1).strip()

                txt = annotate_code_blocks(txt)
                txt = normalize_headings(txt, page_title, f"file://{html_path}", cfg["version"])

                with open(md_path, "w", encoding="utf-8") as f:
                    f.write(txt)

                md_files.append(md_path)
            except subprocess.CalledProcessError as e:
                print(f"Warn: pandoc failed for {html_path}: {e}")

        # 5) Compiler PDF de section
        if md_files:
            out_pdf = os.path.join(PDF_DIR, f"{key}.pdf")
            try:
                compile_section_pdf(md_files, out_pdf)
            except subprocess.CalledProcessError as e:
                print(f"Warn: PDF compile failed for {key}: {e}")

        # Index
        rel_md = os.path.relpath(sec_md_dir, OUT_DIR)
        rel_pdf = os.path.relpath(os.path.join(PDF_DIR, f"{key}.pdf"), OUT_DIR)
        index_entries.append((title, rel_md, rel_pdf))

    # 6) Créer INDEX.md
    index_path = os.path.join(OUT_DIR, "INDEX.md")
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(f"# IBM i {cfg['version']} — Documentation hors-ligne (Markdown + PDF)\n\n")
        f.write("Sections:\n\n")
        for title, rel_md, rel_pdf in index_entries:
            f.write(f"- [{title}]({rel_md}) — [PDF]({rel_pdf})\n")
        f.write("\n\nNote: Chaque dossier contient des fichiers `.md` utilisables par GitHub Copilot dans VS Code.\n")

if __name__ == "__main__":
    main()