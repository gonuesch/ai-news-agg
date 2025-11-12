import os
import feedparser
import requests
import google.generativeai as genai
from datetime import datetime, timedelta, timezone
from textwrap import dedent

# --------------------------------------------------------------------------
# SCHRITT 1: Konfiguration (API-Schlüssel)
# --------------------------------------------------------------------------
# Diese liest das Skript aus den "Umgebungsvariablen".
# In GitHub Actions nennst du sie "Secrets".
try:
    GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
    TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
    TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
except KeyError as e:
    print(f"FEHLER: Umgebungsvariable {e} nicht gefunden.")
    print("Bitte stelle sicher, dass GEMINI_API_KEY, TELEGRAM_BOT_TOKEN und TELEGRAM_CHAT_ID gesetzt sind.")
    exit(1) # Beendet das Skript, wenn Schlüssel fehlen

# --------------------------------------------------------------------------
# SCHRITT 2: Deine Feed-Quellen
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
    Sendet den Rohtext an die Gemini API und bittet um eine Zusammenfassung.
    """
    if not raw_text:
        print("Kein Rohtext zum Zusammenfassen vorhanden.")
        return "Es gab heute keine nennenswerten AI-News."

    try:
        genai.configure(api_key=GEMINI_API_KEY)
        # Wir verwenden 'gemini-1.5-flash', da es schnell ist und ein großes
        # Kontextfenster hat, falls du viele Artikel findest.
        model = genai.GenerativeModel('gemini-1.5-flash')

        # Der Prompt ist der wichtigste Teil!
        # dedent() entfernt die Einrückungen aus dem String für einen sauberen Prompt.
        prompt = dedent(f"""
        Hallo. Du bist ein Redakteur für ein tägliches AI-Briefing.

        AUFGABE:
        Analysiere die folgenden Artikel-Snippets, die ich gesammelt habe. Ignoriere Duplikate oder unwichtige Meldungen.
        Die Kategorien (z.B. "[KATEGORIE]: Fokus: Gemini") sind zur Orientierung.

        1.  Identifiziere die 3 bis 5 wichtigsten Themen oder Durchbrüche des Tages.
        2.  Schreibe für jedes Thema eine kurze, neutrale Zusammenfassung (2-3 Sätze).
        3.  Liste unter jeder Zusammenfassung die Links zu den Originalartikeln auf, die dieses Thema behandeln.
        4.  Wenn es keine wichtigen News gibt, schreibe "Es gab heute keine nennenswerten AI-News."

        Formatiere die gesamte Ausgabe als sauberes Telegram-Markdown (verwende *fett*, _kursiv_, [Text](URL), aber keine Markdown-Überschriften #).
        Beginne direkt mit dem ersten Thema.

        HIER SIND DIE HEUTIGEN ROHDATEN:
        ---
        {raw_text}
        ---
        ENDE DER ROHDATEN.
        """)

        print("Sende Rohtext an Gemini API...")
        response = model.generate_content(prompt)
        
        print("Antwort von Gemini erhalten.")
        return response.text

    except Exception as e:
        print(f"!! FEHLER bei der Gemini API: {e}")
        return f"Fehler bei der Erstellung der Zusammenfassung: {e}"

# --------------------------------------------------------------------------
# FUNKTION 3: An Telegram senden
# --------------------------------------------------------------------------
def send_to_telegram(message_text):
    """
    Sendet die finale Nachricht an deine Telegram Chat ID.
    """
    print("Sende Nachricht an Telegram...")
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    
    # Telegram hat ein Limit von 4096 Zeichen pro Nachricht
    if len(message_text) > 4096:
        print("Warnung: Nachricht ist länger als 4096 Zeichen. Kürze...")
        message_text = message_text[:4090] + "\n... (Nachricht gekürzt)"

    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': message_text,
        'parse_mode': 'Markdown', # Wichtig, damit *fett* etc. gerendert wird
        'disable_web_page_preview': True # Mache die Nachricht sauberer
    }
    
    try:
        response = requests.post(url, data=payload)
        if response.status_code == 200:
            print("Nachricht erfolgreich an Telegram gesendet.")
        else:
            print(f"!! FEHLER beim Senden an Telegram: {response.status_code}")
            print(response.json()) # Zeigt die Fehlerantwort von Telegram
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
