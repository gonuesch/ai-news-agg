import os
import feedparser
import requests
import google.generativeai as genai
from datetime import datetime, timedelta, timezone
from textwrap import dedent
import time

# --------------------------------------------------------------------------
# Konfiguration (API-Schlüssel)
# --------------------------------------------------------------------------

try:
    GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
    TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
    TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
except KeyError as e:
    print(f"FEHLER: Umgebungsvariable {e} nicht gefunden.")
    print("Bitte stelle sicher, dass GEMINI_API_KEY, TELEGRAM_BOT_TOKEN und TELEGRAM_CHAT_ID gesetzt sind.")
    exit(1) # Beendet das Skript, wenn Schlüssel fehlen

# --------------------------------------------------------------------------
# Feed-Quellen
# --------------------------------------------------------------------------
FEEDS = {
    "KI Allgemein (Global)": [
        "https://techcrunch.com/category/artificial-intelligence/feed/",
        "https://arstechnica.com/ai/feed/",
        "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
        "https://www.wired.com/feed/category/artificial-intelligence/rss",
        "https://www.zdnet.com/topic/artificial-intelligence/rss.xml",
        "https://www.technologyreview.com/topic/artificial-intelligence/feed/",
    ],
    "KI Allgemein (DACH)": [
        "https://www.heise.de/thema/kuenstliche-intelligenz/rss.xml",
        "https://kiupdate.podigee.io/feed/mp3", # Podcast
        "https://rss.golem.de/rss.php?feed=ATOM1.0", # Alle Golem News
        "https://t3n.de/rss/ressort/software-ki.xml",
    ],
    "KI Forschung (Primärquelle)": [
        "https://openai.com/feed.xml?format=xml",
        "https://research.google/blog/rss/",
        "https://deepmind.google/blog/rss/",
        "https://news.mit.edu/topic/mitartificial-intelligence2-rss.xml",
        "https://ai.stanford.edu/blog/feed.xml",
        "https://developer.nvidia.com/blog/feed/",
    ],
    "Fokus: Gemini": [
        "https://blog.google/rss/", # Haupt-Google-Blog
        "https://blog.google/technology/developers/rss/",
        "https://workspaceupdates.googleblog.com/atom.xml",
    ],
    "Fokus: Medienbranche": [
        "https://www.niemanlab.org/feed/",
        "https://www.poynter.org/feed/",
        "https://www.aidataanalytics.network/rss/categories/data-science-ai",
        "https://www.artificialintelligence-news.com/feed/rss/",
        "https://www.artificial-intelligence.blog/ai-news/category/entertainment?format=rss",
        "https://feeds.megaphone.fm/marketingai", # Podcast
    ]
}

# --------------------------------------------------------------------------
# FUNKTION 1: News sammeln und filtern
# --------------------------------------------------------------------------
def get_recent_news():
    """
    Ruft alle Feeds ab und filtert Artikel der letzten 24 Stunden.
    """
    now = datetime.now(timezone.utc)
    twenty_four_hours_ago = now - timedelta(days=1)
    
    rohtext_snippets = []
    
    print(f"Starte News-Sammlung... (Filter: nach {twenty_four_hours_ago.isoformat()})")

    for category, urls in FEEDS.items():
        print(f"\n--- Verarbeite Kategorie: {category} ---")
        for url in urls:
            try:
                feed = feedparser.parse(url)
                
                for entry in feed.entries:
                    published_date = None
                    if hasattr(entry, 'published_parsed') and entry.published_parsed:
                        published_date = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                    elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                         # Fallback auf "updated_parsed" (z.B. für Google Workspace)
                        published_date = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)

                    if published_date and published_date > twenty_four_hours_ago:
                        print(f"  -> GEFUNDEN: {entry.title[:50]}...")
                        
                        title = entry.get('title', 'Kein Titel')
                        link = entry.get('link', 'Kein Link')
                        summary = entry.get('summary', 'Keine Zusammenfassung')
                        
                        snippet = (
                            f"[KATEGORIE]: {category}\n"
                            f"[TITEL]: {title}\n"
                            f"[LINK]: {link}\n"
                            f"[ZUSAMMENFASSUNG]: {summary}\n"
                            f"----------------------------------------\n\n"
                        )
                        rohtext_snippets.append(snippet)
                        
            except Exception as e:
                print(f"!! FEHLER beim Abrufen von {url}: {e}")

    print("\nSammlung abgeschlossen.")
    return "".join(rohtext_snippets)

# --------------------------------------------------------------------------
# FUNKTION 2: Mit Gemini zusammenfassen
# --------------------------------------------------------------------------
def summarize_with_gemini(raw_text):
    """
    Sendet den Rohtext an die Gemini API und bittet um eine saubere Zusammenfassung.
    """
    if not raw_text:
        print("Kein Rohtext zum Zusammenfassen vorhanden.")
        return "Es gab heute keine nennenswerten AI-News."

    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel('gemini-2.5-flash')

        # === VERBESSERTER PROMPT ===
        # Dieser Prompt zwingt Gemini zu einer besseren Struktur
        # mit Überschriften und Aufzählungspunkten für die Links.
        prompt = dedent(f"""
        Hallo. Du bist ein Redakteur für ein tägliches AI-Briefing.

        AUFGABE:
        Analysiere die folgenden Artikel-Snippets.
        1.  Identifiziere die 3 bis 5 wichtigsten Themen des Tages.
        2.  Schreibe für jedes Thema eine *zusammenfassende Überschrift in Fett*.
        3.  Schreibe darunter eine kurze, neutrale Zusammenfassung (2-3 Sätze).
        4.  Liste *danach* die relevanten Quell-Links als Markdown-Aufzählungspunkte (z.B. `* [Titel des Artikels](URL)`).
        5.  Trenne die einzelnen Themenblöcke mit einer Leerzeile (wichtig für die spätere Aufteilung).

        Formatiere die gesamte Ausgabe als sauberes Telegram-Markdown.
        Beginne direkt mit der ersten Überschrift.

        Beispiel-Format für ein Thema:
        *Neues KI-Modell von Google veröffentlicht*
        Google hat heute Modell "XYZ" vorgestellt, das besser als GPT-4 ist. Es ist multimodal und...
        * [Google Blog: Das neue Modell](https://link.com/1)
        * [TechCrunch: Analyse von XYZ](https://link.com/2)
        
        (Hier wäre eine Leerzeile zum nächsten Thema)

        HIER SIND DIE HEUTIGEN ROHDATEN:
        ---
        {raw_text}
        ---
        """)

        print("Sende Rohtext an Gemini API...")
        response = model.generate_content(prompt)
        
        print("Antwort von Gemini erhalten.")
        return response.text

    except Exception as e:
        print(f"!! FEHLER bei der Gemini API: {e}")
        return f"Fehler bei der Erstellung der Zusammenfassung: {e}"

# --------------------------------------------------------------------------
# FUNKTION 3: An Telegram senden (VERBESSERTE VERSION MIT "CHUNKING")
# --------------------------------------------------------------------------
def send_to_telegram(message_text, chat_id=TELEGRAM_CHAT_ID, bot_token=TELEGRAM_BOT_TOKEN):
    """
    Sendet die finale Nachricht an deine Telegram Chat ID.
    Teilt die Nachricht automatisch in mehrere "Chunks", wenn sie zu lang ist.
    """
    print("Sende Nachricht an Telegram...")
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    
    # Telegrams offizielles Limit
    MAX_LENGTH = 4096
    
    # Header-Text (wird der ersten Nachricht vorangestellt)
    # Hole das Datum (Logik aus der alten 'main'-Funktion hierher verschoben)
    utc_now = datetime.now(timezone.utc)
    try:
        import zoneinfo
        local_tz = zoneinfo.ZoneInfo("Europe/Berlin")
    except ImportError:
        local_tz = timezone(timedelta(hours=1)) # Fallback

    local_time = utc_now.astimezone(local_tz)
    today_date = local_time.strftime("%d. %B %Y")
    
    header = f"🤖 *Dein AI-Briefing für {today_date}*\n\n"
    
    # Füge den Header zur Nachricht hinzu
    full_message = header + message_text

    # --- Die "Chunking"-Logik ---
    
    if len(full_message) <= MAX_LENGTH:
        # Nachricht ist kurz genug, sende sie als Ganzes
        _send_telegram_message(url, full_message, chat_id)
        print("Nachricht (1/1) erfolgreich gesendet.")
        return

    print(f"Nachricht ist zu lang ({len(full_message)} Zeichen). Starte 'Chunking'...")
    
    # Die Nachricht ist zu lang. Wir teilen sie.
    # Wir senden den Header IMMER als separate erste Nachricht.
    _send_telegram_message(url, header, chat_id)
    time.sleep(1) # Kurze Pause, damit die Reihenfolge stimmt
    
    chunks = []
    current_chunk = ""
    
    # Wir teilen die Nachricht an den doppelten Umbrüchen (Themen-Trenner)
    # (Der neue Prompt stellt sicher, dass diese existieren)
    message_blocks = message_text.split('\n\n')
    
    for i, block in enumerate(message_blocks):
        # Prüfen, ob der nächste Block + Umbruch noch in den aktuellen Chunk passt
        if len(current_chunk) + len(block) + 2 <= MAX_LENGTH:
            current_chunk += block + '\n\n'
        else:
            # Der Chunk ist voll. Speichern und einen neuen starten.
            if current_chunk: # Speichere den alten Chunk (kann beim ersten Block leer sein)
                chunks.append(current_chunk)
            
            if len(block) > MAX_LENGTH:
                # Sonderfall: Ein einzelner Block ist zu lang. Hart kürzen.
                print(f"Warnung: Ein einzelner Themenblock ist > {MAX_LENGTH} Zeichen. Kürze...")
                chunks.append(block[:MAX_LENGTH - 10] + "\n...(gekürzt)")
                current_chunk = "" # Starte leer
            else:
                # Starte einen neuen Chunk mit dem aktuellen Block
                current_chunk = block + '\n\n'

    # Füge den letzten verbleibenden Chunk hinzu
    if current_chunk:
        chunks.append(current_chunk)

    # Sende alle Chunks nacheinander
    total_chunks = len(chunks)
    for i, chunk in enumerate(chunks):
        print(f"Sende Chunk {i+1}/{total_chunks}...")
        _send_telegram_message(url, chunk, chat_id)
        time.sleep(1) # Kurze Pause zwischen den Nachrichten

    print("Alle Chunks erfolgreich gesendet.")


def _send_telegram_message(url, message_text, chat_id):
    """
    Private Hilfsfunktion, die die eigentliche Sende-Anfrage durchführt.
    """
    payload = {
        'chat_id': chat_id,
        'text': message_text,
        'parse_mode': 'Markdown',
        'disable_web_page_preview': True
    }
    
    try:
        response = requests.post(url, data=payload)
        if response.status_code != 200:
            print(f"!! FEHLER beim Senden an Telegram: {response.status_code}")
            print(response.json())
    except Exception as e:
        print(f"!! FEHLER bei der Telegram-Anfrage: {e}")

# --------------------------------------------------------------------------
# HAUPTAUSFÜHRUNG (Main Guard)
# --------------------------------------------------------------------------
if __name__ == "__main__":
    print("Starte tägliches AI-Briefing Skript...")
    
    # 1. Sammeln
    raw_news = get_recent_news()
    
    # 2. Zusammenfassen
    summary = summarize_with_gemini(raw_news)
    
    # 3. Senden
    # Füge ein schönes Datum hinzu (Zeitzone D-A-CH)
    # Wichtig: Geht davon aus, dass der Server (GitHub Action) UTC ist.
    utc_now = datetime.now(timezone.utc)
    try:
        # Versuche, die deutsche Zeitzone zu laden
        import zoneinfo
        local_tz = zoneinfo.ZoneInfo("Europe/Berlin")
    except ImportError:
        # Fallback, wenn 'zoneinfo' nicht verfügbar ist (sollte es aber)
        local_tz = timezone(timedelta(hours=1)) # CET (ohne Sommerzeit-Logik)

    local_time = utc_now.astimezone(local_tz)
    today_date = local_time.strftime("%d. %B %Y")
    
    final_message = f"🤖 *Dein AI-Briefing für {today_date}*\n\n{summary}"
    
    send_to_telegram(final_message)
    
    print("Skript-Ausführung beendet.")
