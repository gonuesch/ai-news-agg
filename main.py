import os
import feedparser
import requests
import google.generativeai as genai
import time
from datetime import datetime, timedelta, timezone
from textwrap import dedent

# --------------------------------------------------------------------------
# SCHRITT 1: Konfiguration (API-Schlüssel)
# (Keine Änderungen hier)
# --------------------------------------------------------------------------
try:
    GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
    TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
    TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
except KeyError as e:
    print(f"FEHLER: Umgebungsvariable {e} nicht gefunden.")
    exit(1)

# --------------------------------------------------------------------------
# SCHRITT 2: Deine Feed-Quellen
# (Keine Änderungen hier)
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
# FUNKTION 1: News für eine KATEGORIE sammeln
# (Dies ist eine NEUE, modularisierte Funktion)
# --------------------------------------------------------------------------
def collect_news_for_category(urls, category_name):
    """
    Ruft eine Liste von URLs ab und filtert Artikel der letzten 24 Stunden.
    Gibt den Rohtext-String NUR für diese Kategorie zurück.
    """
    now = datetime.now(timezone.utc)
    twenty_four_hours_ago = now - timedelta(days=1)
    
    rohtext_snippets = []
    print(f"\n--- Verarbeite Kategorie: {category_name} ---")

    for url in urls:
        try:
            feed = feedparser.parse(url)
            
            for entry in feed.entries:
                published_date = None
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    published_date = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                    published_date = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)

                if published_date and published_date > twenty_four_hours_ago:
                    print(f"  -> GEFUNDEN: {entry.title[:50]}...")
                    
                    title = entry.get('title', 'Kein Titel')
                    link = entry.get('link', 'Kein Link')
                    summary = entry.get('summary', 'Keine Zusammenfassung')
                    
                    snippet = (
                        f"[TITEL]: {title}\n"
                        f"[LINK]: {link}\n"
                        f"[ZUSAMMENFASSUNG]: {summary}\n"
                        f"----------------------------------------\n\n"
                    )
                    rohtext_snippets.append(snippet)
                    
        except Exception as e:
            print(f"!! FEHLER beim Abrufen von {url}: {e}")

    return "".join(rohtext_snippets)

# --------------------------------------------------------------------------
# FUNKTION 2: Mit Gemini KATEGORIE zusammenfassen (NEUE, STRIKTE VERSION)
# --------------------------------------------------------------------------
def summarize_category_with_gemini(raw_text, category_name):
    """
    Sendet den KATEGORIE-Rohtext an die Gemini API und bittet um eine Zusammenfassung.
    NEU: Mit strikten Längen-Limits, um 4096-Zeichen-Fehler zu vermeiden.
    """
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel('gemini-2.5-flash')

        # === NEUER, STRIKTER PROMPT ===
        # Dieser Prompt zwingt Gemini, sich kurz zu fassen.
        prompt = dedent(f"""
        Hallo Redakteur. Deine Aufgabe ist es, die News-Snippets für die Kategorie "{category_name}" zusammenzufassen.

        WICHTIGE REGELN:
        1.  Die gesamte Antwort MUSS UNTER 3500 ZEICHEN bleiben. Das ist ein hartes technisches Limit.
        2.  Fasse dich extrem kurz. Wähle nur die 1 oder 2 absolut wichtigsten Themen aus.
        3.  Pro Thema, liste MAXIMAL 3-4 der relevantesten Quell-Links auf. Ignoriere alle anderen Links.

        AUFGABE:
        1.  Identifiziere die 1-2 wichtigsten Themen.
        2.  Schreibe für jedes Thema eine *zusammenfassende Überschrift in Fett*.
        3.  Schreibe darunter eine sehr kurze Zusammenfassung (1-2 Sätze).
        4.  Liste *danach* die relevanten Quell-Links (MAXIMAL 3-4 pro Thema) als Markdown-Aufzählungspunkte (`* [Titel](URL)`).
        5.  Wenn es keine wichtigen News gibt, antworte *nur* mit dem Text: "Keine nennenswerten News".

        Formatiere als sauberes Telegram-Markdown. Beginne direkt mit der ersten Überschrift.

        HIER SIND DIE ROHDATEN (kann sehr viel sein, filtere aggressiv):
        ---
        {raw_text[:20000]} 
        ---
        """)
        # WICHTIG: Ich kürze den INPUT-Text auf 20.000 Zeichen, falls du
        # Hunderte von Artikeln findest. Das spart Tokens und verhindert API-Fehler.

        print(f"Sende Rohtext für {category_name} an Gemini API (Input gekürzt auf 20k Zeichen)...")
        response = model.generate_content(prompt)
        
        print("Antwort von Gemini erhalten.")
        return response.text

    except Exception as e:
        print(f"!! FEHLER bei der Gemini API: {e}")
        return f"Fehler bei der Erstellung der Zusammenfassung für {category_name}: {e}"
# --------------------------------------------------------------------------
# FUNKTION 3: An Telegram senden (VERBESSERTE CHUNKING-LOGIK)
# --------------------------------------------------------------------------
def send_to_telegram(message_text, chat_id=TELEGRAM_CHAT_ID, bot_token=TELEGRAM_BOT_TOKEN):
    """
    Sendet die finale Nachricht an deine Telegram Chat ID.
    Teilt die Nachricht automatisch in mehrere "Chunks", wenn sie zu lang ist.
    Behandelt Markdown-Parsing-Fehler bei Kürzungen.
    """
    print("Sende Nachricht an Telegram...")
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    
    MAX_LENGTH = 4096
    full_message = message_text

    if len(full_message) <= MAX_LENGTH:
        # Nachricht ist kurz genug, sende sie als Ganzes mit Markdown
        _send_telegram_message(url, full_message, chat_id, parse_mode='Markdown')
        print("Nachricht (1/1) erfolgreich gesendet.")
        return

    print(f"Nachricht ist zu lang ({len(full_message)} Zeichen). Starte 'Chunking'...")
    
    # Wir erstellen eine Liste von (text, parse_mode) Tupeln
    chunks = []
    current_chunk_text = ""
    current_parse_mode = 'Markdown' # Standard ist Markdown

    message_blocks = message_text.split('\n---\n')
    
    for i, block in enumerate(message_blocks):
        block_to_add = block + '\n---\n' if i < len(message_blocks) - 1 else block
        
        if len(current_chunk_text) + len(block_to_add) <= MAX_LENGTH:
            current_chunk_text += block_to_add
        else:
            # Der aktuelle Chunk ist voll. Speichere ihn.
            if current_chunk_text:
                chunks.append((current_chunk_text, current_parse_mode))
            
            # Jetzt den neuen Block behandeln
            if len(block_to_add) > MAX_LENGTH:
                # *** HIER IST DIE NEUE LOGIK ***
                print(f"Warnung: Ein einzelner Kategorie-Block ist > {MAX_LENGTH} Zeichen. Kürze...")
                # Kürze den Text und setze den Parse-Modus auf 'None' (reiner Text)
                truncated_text = block_to_add[:MAX_LENGTH - 20] + "\n...(gekürzt)"
                chunks.append((truncated_text, 'None')) # Sende diesen Chunk als reinen Text
                current_chunk_text = "" # Starte einen leeren Chunk für die nächste Runde
            else:
                # Starte einen normalen neuen Chunk
                current_chunk_text = block_to_add
                current_parse_mode = 'Markdown'

    # Füge den letzten verbleibenden Chunk hinzu
    if current_chunk_text:
        chunks.append((current_chunk_text, current_parse_mode))

    # Sende alle vorbereiteten Chunks nacheinander
    total_chunks = len(chunks)
    for i, (chunk_text, parse_mode) in enumerate(chunks):
        print(f"Sende Chunk {i+1}/{total_chunks} (Mode: {parse_mode})...")
        # Übergebe den spezifischen Parse-Modus (Markdown or None)
        _send_telegram_message(url, chunk_text, chat_id, parse_mode=parse_mode)
        time.sleep(1) # Kurze Pause zwischen den Nachrichten

    print("Alle Chunks erfolgreich gesendet.")


def _send_telegram_message(url, message_text, chat_id, parse_mode='Markdown'):
    """ 
    Private Hilfsfunktion, die die eigentliche Sende-Anfrage durchführt.
    Akzeptiert jetzt einen 'parse_mode'-Parameter.
    """
    payload = {
        'chat_id': chat_id,
        'text': message_text,
        'disable_web_page_preview': True
    }
    
    # Füge 'parse_mode' nur hinzu, wenn es 'Markdown' ist.
    # Wenn 'parse_mode' 'None' ist, wird der Key weggelassen (reiner Text).
    if parse_mode == 'Markdown':
        payload['parse_mode'] = 'Markdown'
        
    try:
        response = requests.post(url, data=payload)
        if response.status_code != 200:
            # Wir loggen den Fehler, aber das Skript bricht nicht mehr ab
            print(f"!! FEHLER beim Senden an Telegram: {response.status_code} {response.text}")
    except Exception as e:
        print(f"!! FEHLER bei der Telegram-Anfrage: {e}")

# --------------------------------------------------------------------------
# HAUPTAUSFÜHRUNG (Main Guard) - NEUE ORCHESTRIERUNGS-LOGIK
# --------------------------------------------------------------------------
if __name__ == "__main__":
    print("Starte tägliches AI-Briefing Skript...")
    
    # Hole das Datum für den Header
    utc_now = datetime.now(timezone.utc)
    try:
        import zoneinfo
        local_tz = zoneinfo.ZoneInfo("Europe/Berlin")
    except ImportError:
        local_tz = timezone(timedelta(hours=1)) # Fallback
    local_time = utc_now.astimezone(local_tz)
    today_date = local_time.strftime("%d. %B %Y")
    
    # Der Header wird ganz am Anfang erstellt
    header = f"🤖 *Dein AI-Briefing für {today_date}*\n\n"
    all_summaries = []

    # === DIE NEUE HAUPTSCHLEIFE ===
    # Wir iterieren durch jede KATEGORIE
    for category, urls in FEEDS.items():
        
        # 1. Sammeln (pro Kategorie)
        raw_news_for_category = collect_news_for_category(urls, category)
        
        if not raw_news_for_category:
            print(f"Keine neuen Artikel für {category} gefunden.")
            continue # Nächste Kategorie
        
        # 2. Zusammenfassen (pro Kategorie)
        category_summary = summarize_category_with_gemini(raw_news_for_category, category)
        
        # 3. Baue den finalen Block (wenn News vorhanden sind)
        if "Keine nennenswerten News" not in category_summary:
            
            # Wähle ein schönes Emoji für die Überschrift
            emoji = "•" # Standard
            if "Global" in category: emoji = "🌎"
            elif "DACH" in category: emoji = "🇩🇪🇦🇹🇨🇭"
            elif "Forschung" in category: emoji = "🔬"
            elif "Gemini" in category: emoji = "✨"
            elif "Medien" in category: emoji = "📰"
            
            # Erstelle den finalen Block für diese Kategorie
            final_category_block = (
                f"{emoji} *{category}*\n\n" # Die Kategorie-Überschrift
                f"{category_summary}\n\n"      # Der von Gemini generierte Inhalt
                "---\n"                      # Ein horizontaler Trenner
            )
            all_summaries.append(final_category_block)

    # 4. Senden (Alles auf einmal)
    if not all_summaries:
        final_message = header + "Es gab heute keine nennenswerten AI-News in einer Kategorie."
    else:
        # Füge alle Blöcke zusammen
        final_message = header + "".join(all_summaries)
        # Entferne den letzten Trenner "---"
        if final_message.endswith("---\n"):
            final_message = final_message[:-4]

    send_to_telegram(final_message)
    
    print("Skript-Ausführung beendet.")
