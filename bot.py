import os
import json
import re
import time
import random
from datetime import datetime, timezone
import requests
import feedparser

STATE_FILE = "state.json"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
DONATE_URL = os.getenv("DONATE_URL", "")

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

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

def fetch_manual_test():
    """Тестовые посты для проверки"""
    return [
        {
            "id": "test_epic_1",
            "title": "🎮 Бесплатная игра в Epic Games Store",
            "url": "https://store.epicgames.com/free-games",
            "source": "EpicGames",
            "image_url": None,
            "expires_at": None
        },
        {
            "id": "test_steam_1", 
            "title": "🎯 Халява в Steam - успей забрать!",
            "url": "https://store.steampowered.com/",
            "source": "Steam",
            "image_url": None,
            "expires_at": None
        }
    ]

def fetch_gotd():
    url = "https://www.giveawayoftheday.com/feed/"
    try:
        d = feedparser.parse(url)
        items = []
        for e in d.entries[:5]:  # Максимум 5
            items.append({
                "id": e.link,
                "title": f"💎 {e.title}",
                "url": e.link,
                "source": "GiveawayOfTheDay",
                "image_url": None,
                "expires_at": None
            })
        return items
    except Exception as ex:
        print(f"GOTD error: {ex}")
        return []

def fetch_sharewareonsale():
    url = "https://sharewareonsale.com/feed"
    try:
        d = feedparser.parse(url, request_headers=HEADERS)
        items = []
        for e in d.entries[:10]:
            title = e.title or ""
            if re.search(r"(100% off|free|giveaway)", title, re.I):
                items.append({
                    "id": e.link,
                    "title": f"🎁 {title}",
                    "url": e.link,
                    "source": "SharewareOnSale",
                    "image_url": None,
                    "expires_at": None
                })
        return items
    except Exception as ex:
        print(f"SharewareOnSale error: {ex}")
        return []

def fetch_epic_freebies():
    url = "https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions?locale=ru-RU&country=RU&allowCountries=RU"
    items = []
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
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
                link = f"https://store.epicgames.com/p/{slug}" if slug else "https://store.epicgames.com/free-games"
                
                img = None
                for ki in el.get("keyImages", []):
                    if ki.get("type") in ("Thumbnail", "DieselStoreFrontWide", "OfferImageWide"):
                        img = ki.get("url")
                        break
                
                items.append({
                    "id": f"epic:{slug or title}",
                    "title": f"🎮 Epic Games: {title} — БЕСПЛАТНО!",
                    "url": link,
                    "source": "EpicGames",
                    "image_url": img,
                    "expires_at": None
                })
    except Exception as ex:
        print(f"Epic fetch error: {ex}")
    return items

def collect_items():
    items = []
    
    # Сначала тестовые
    #items.extend(fetch_manual_test())
    
    # Потом реальные
    for fetcher in (fetch_gotd, fetch_sharewareonsale, fetch_epic_freebies):
        try:
            items.extend(fetcher())
        except Exception as ex:
            print(f"Fetcher {fetcher.__name__} failed: {ex}")
    
    # Убираем дубликаты
    seen = set()
    unique = []
    for it in items:
        key = it["url"]
        if key not in seen:
            seen.add(key)
            unique.append(it)
    
    return unique

def render_text(item):
    templates = [
        f"{item['title']}\n\n✅ Проверенная раздача\n⏰ Ограниченное время\n🔥 Забирай по кнопке ниже",
        f"{item['title']}\n\n💯 Абсолютно бесплатно\n🚀 Без регистрации и СМС\n👇 Жми кнопку чтобы получить",
        f"{item['title']}\n\n🎯 Экономия до $50\n⭐ Официальная лицензия\n📲 Получить — жми кнопку"
    ]
    
    text = random.choice(templates)
    
    if item['source']:
        text += f"\n\n📍 Источник: {item['source']}"
    
    return text

def send_telegram(item):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError("TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID not set")

    caption = render_text(item)

    keyboard = {"inline_keyboard": [[{"text": "🎁 Забрать халяву", "url": item["url"]}]]}
    if DONATE_URL:
        keyboard["inline_keyboard"].append([{"text": "💖 Поддержать канал", "url": DONATE_URL}])

    api_base = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
    
    # Пробуем с картинкой
    if item.get("image_url"):
        url = f"{api_base}/sendPhoto"
        data = {
            "chat_id": TELEGRAM_CHAT_ID,
            "caption": caption,
            "parse_mode": "HTML",
            "reply_markup": json.dumps(keyboard, ensure_ascii=False),
            "photo": item["image_url"]
        }
        try:
            r = requests.post(url, data=data, timeout=30)
            if r.status_code == 200:
                return True
        except:
            pass

    # Без картинки
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
    print("Starting Freebies Agent...")
    
    state = load_state()
    posted = set(state.get("posted", []))
    
    print(f"Already posted: {len(posted)} items")

    items = collect_items()
    print(f"Found total: {len(items)} items")
    
    new_items = [it for it in items if it["id"] not in posted]
    print(f"New items: {len(new_items)}")

    # Постим максимум 3 за раз
    posts_count = 0
    for it in new_items[:3]:
        try:
            print(f"Posting: {it['title']}")
            ok = send_telegram(it)
            if ok:
                posted.add(it["id"])
                posts_count += 1
                # Случайная задержка 30-90 секунд
                time.sleep(random.randint(30, 90))
        except Exception as ex:
            print(f"Post failed: {ex}")
            continue

    state["posted"] = list(posted)
    save_state(state)
    print(f"Done! Posted: {posts_count} items")

if __name__ == "__main__":
    main()
