import os
import json
import re
import time
from datetime import datetime, timezone
import requests
import feedparser

STATE_FILE = "state.json"

TELEGRAM_BOT_TOKEN = os.getenv("")
TELEGRAM_CHAT_ID = os.getenv("")
DONATE_URL = os.getenv("DONATE_URL", "")
USE_OLLAMA = os.getenv("USE_OLLAMA", "0").lower() in ("1", "true", "yes")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "mistral:instruct")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; FreebiesAgent/1.0)"}

def load_state():
    if not os.path.exists(STATE_FILE):
        return {"posted": []}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {"posted": []}

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def fetch_gotd():
    url = "https://www.giveawayoftheday.com/feed/"
    d = feedparser.parse(url)
    items = []
    for e in d.entries:
        items.append({
            "id": e.link,
            "title": e.title,
            "url": e.link,
            "source": "GiveawayOfTheDay",
            "image_url": None,
            "expires_at": None
        })
    return items

def fetch_sharewareonsale():
    url = "https://sharewareonsale.com/feed"
    d = feedparser.parse(url, request_headers=HEADERS)
    items = []
    for e in d.entries:
        title = e.title or ""
        if re.search(r"(100% off|free|giveaway)", title, re.I):
            items.append({
                "id": e.link,
                "title": title,
                "url": e.link,
                "source": "SharewareOnSale",
                "image_url": None,
                "expires_at": None
            })
    return items

def fetch_reddit_freegames():
    url = "https://www.reddit.com/r/FreeGamesOnSteam/.rss"
    d = feedparser.parse(url, request_headers=HEADERS)
    items = []
    for e in d.entries:
        title = e.title or ""
        if re.search(r"(free)", title, re.I):
            items.append({
                "id": e.link,
                "title": title,
                "url": e.link,
                "source": "r/FreeGamesOnSteam",
                "image_url": None,
                "expires_at": None
            })
    return items

def fetch_epic_freebies():
    url = "https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions?locale=ru-RU&country=RU&allowCountries=RU"
    items = []
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
        data = r.json()
        elements = data.get("data", {}).get("Catalog", {}).get("searchStore", {}).get("elements", [])
        for el in elements:
            price = (el.get("price") or {}).get("totalPrice") or {}
            discount_price = price.get("discountPrice", 1)
            original_price = price.get("originalPrice", 0)
            if original_price > 0 and discount_price == 0:
                title = el.get("title") or "Epic Games Freebie"
                slug = el.get("productSlug") or el.get("urlSlug") or ""
                slug = slug.split("?")[0].strip("/")
                link = f"https://store.epicgames.com/p/{slug}" if slug else "https://store.epicgames.com/"
                img = None
                for ki in el.get("keyImages", []):
                    if ki.get("type") in ("Thumbnail", "DieselStoreFrontWide", "OfferImageWide"):
                        img = ki.get("url")
                        break
                items.append({
                    "id": f"epic:{slug or title}",
                    "title": f"Epic Games: {title} — бесплатно",
                    "url": link,
                    "source": "EpicGames",
                    "image_url": img,
                    "expires_at": None
                })
    except Exception as ex:
        print("Epic fetch error:", ex)
    return items

def collect_items():
    items = []
    for fetcher in (fetch_gotd, fetch_sharewareonsale, fetch_reddit_freegames, fetch_epic_freebies):
        try:
            items.extend(fetcher())
        except Exception as ex:
            print(f"Fetcher {fetcher.__name__} failed:", ex)
    seen = set()
    unique = []
    for it in items:
        key = it["url"]
        if key not in seen:
            seen.add(key)
            unique.append(it)
    return unique

def render_text(item):
    base = f"🎁 {item['title']}\nИсточник: {item['source']}"
    if USE_OLLAMA:
        try:
            prompt = (
                "Сформулируй краткий пост для Telegram (до 350 символов) на русском, дружелюбно, без хештегов. "
                "Дай 1-2 выгоды и призыв открыть по кнопке. Тема:\n"
                f"{item['title']} (источник: {item['source']})"
            )
            payload = {"model": OLLAMA_MODEL, "prompt": prompt, "stream": True}
            with requests.post(OLLAMA_URL, json=payload, timeout=60, stream=True) as resp:
                resp.raise_for_status()
                out = []
                for line in resp.iter_lines(decode_unicode=True):
                    if not line:
                        continue
                    try:
                        j = json.loads(line)
                        out.append(j.get("response", ""))
                    except:
                        pass
                text = "".join(out).strip()
                if text:
                    return text
        except Exception as ex:
            print("Ollama error:", ex)
    return f"{base}\n\nОткрыть предложение — по кнопке ниже ⤵️"

def send_telegram(item):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError("TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID not set")

    caption = render_text(item)

    keyboard = {"inline_keyboard": [[{"text": "Открыть", "url": item["url"]}]]}
    if DONATE_URL:
        keyboard["inline_keyboard"].append([{"text": "Поддержать канал ❤️", "url": DONATE_URL}])

    api_base = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
    if item.get("image_url"):
        url = f"{api_base}/sendPhoto"
        data = {
            "chat_id": TELEGRAM_CHAT_ID,
            "caption": caption,
            "parse_mode": "HTML",
            "reply_markup": json.dumps(keyboard, ensure_ascii=False),
        }
        files = {}
        try:
            data["photo"] = item["image_url"]
            r = requests.post(url, data=data, files=files, timeout=30)
            r.raise_for_status()
            return True
        except Exception as ex:
            print("sendPhoto failed, fallback to sendMessage:", ex)

    url = f"{api_base}/sendMessage"
    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": caption,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
        "reply_markup": json.dumps(keyboard, ensure_ascii=False),
    }
    r = requests.post(url, data=data, timeout=30)
    r.raise_for_status()
    return True

def main():
    state = load_state()
    posted = set(state.get("posted", []))

    items = collect_items()
    new_items = [it for it in items if it["id"] not in posted]

    for it in new_items:
        try:
            print("Posting:", it["title"])
            ok = send_telegram(it)
            if ok:
                posted.add(it["id"])
                time.sleep(1.2)
        except Exception as ex:
            print("Post failed:", ex)
            continue

    state["posted"] = list(posted)
    save_state(state)
    print(f"Done. New posts: {len(new_items)}")

if __name__ == "__main__":
    main()
