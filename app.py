#!/usr/bin/env python3
"""
🔍 סוכן ניתוח דיגיטלי לעסקים — קובץ אחד, פקודה אחת
======================================================

הרצה:
    python app.py

זה הכל. הדפדפן ייפתח אוטומטית.
"""

# ──────────────── התקנה אוטומטית ────────────────
import subprocess, sys, importlib, os

def _install(pkg_import, pkg_pip=None):
    try: importlib.import_module(pkg_import)
    except ImportError:
        print(f"[*] מתקין {pkg_pip or pkg_import}...")
        # יצירת venv אם לא קיים
        venv_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "venv")
        if not os.path.exists(venv_dir):
            print("[*] יוצר סביבה וירטואלית...")
            subprocess.check_call([sys.executable, "-m", "venv", venv_dir])
            # מפעיל מחדש עם ה-venv
            venv_python = os.path.join(venv_dir, "bin", "python3")
            os.execv(venv_python, [venv_python] + sys.argv)
        subprocess.check_call([sys.executable, "-m", "pip", "install", pkg_pip or pkg_import, "-q"])

# בדיקה אם כבר בתוך venv, אם לא — צור והפעל מחדש
venv_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "venv")
if not sys.prefix.endswith("venv") and not os.environ.get("VIRTUAL_ENV"):
    if not os.path.exists(venv_dir):
        print("[*] יוצר סביבה וירטואלית...")
        subprocess.check_call([sys.executable, "-m", "venv", venv_dir])
    venv_python = os.path.join(venv_dir, "bin", "python3")
    print("[*] מפעיל מחדש בסביבה וירטואלית...")
    os.execv(venv_python, [venv_python] + sys.argv)

_install("requests")
_install("bs4", "beautifulsoup4")
_install("lxml")
_install("playwright")

# התקנת דפדפן Playwright אם חסר
def _ensure_playwright_browser():
    pw_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".playwright_installed")
    if not os.path.exists(pw_dir):
        print("[*] מתקין דפדפן Chromium (פעם אחת בלבד)...")
        subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"])
        open(pw_dir, 'w').close()
        print("[✓] דפדפן הותקן!")

_ensure_playwright_browser()

# ──────────────── ייבוא ────────────────
import os, re, time, json, threading, webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse, quote_plus, urljoin
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional, List, Dict

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

PORT = int(os.environ.get("PORT", 8080))

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  שלב 1 — איתור עסק
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def detect_input_type(s):
    s = s.strip()
    if re.match(r'^https?://', s): return "url"
    if re.match(r'^www\.', s): return "url"
    if re.match(r'^[\w-]+\.\w{2,}', s) and ' ' not in s: return "url"
    return "name"

def norm_url(u):
    u = u.strip()
    if not u.startswith(('http://', 'https://')): u = 'https://' + u
    return u

def google_search(query, n=10):
    url = f"https://www.google.com/search?q={quote_plus(query)}&num={n}&hl=he"
    results = []
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, 'lxml')
        for g in soup.select('div.g'):
            a = g.select_one('a[href]')
            h3 = g.select_one('h3')
            if a and h3:
                href = a.get('href','')
                if href.startswith('/url?q='): href = href.split('/url?q=')[1].split('&')[0]
                if href.startswith('http'):
                    results.append({'title': h3.get_text(strip=True), 'url': href})
        if not results:
            for a in soup.select('a[href]'):
                href = a.get('href','')
                if '/url?q=' in href:
                    actual = href.split('/url?q=')[1].split('&')[0]
                    if actual.startswith('http') and 'google.com' not in actual:
                        h3 = a.find('h3')
                        if h3: results.append({'title': h3.get_text(strip=True), 'url': actual})
    except Exception as e:
        print(f"  [!] חיפוש גוגל: {e}")
    return results[:n]

SKIP_DOMAINS = ['facebook.com','instagram.com','twitter.com','x.com','linkedin.com',
    'youtube.com','tiktok.com','yelp.com','tripadvisor.com','zap.co.il','rest.co.il',
    'b144.co.il','wolt.com','google.com','maps.google','waze.com','wikipedia.org',
    'easy.co.il','10bis.co.il','buyme.co.il','saloona.co.il']

def find_website(results):
    for r in results:
        domain = urlparse(r['url']).netloc.lower()
        if not any(s in domain for s in SKIP_DOMAINS):
            return r['url']
    return None

def google_business_data(name):
    d = {'rating':None,'review_count':None,'address':None,'phone':None,
         'category':None,'has_photos':False,'profile_complete':False}
    try:
        r = requests.get(f"https://www.google.com/search?q={quote_plus(name)}&hl=he", headers=HEADERS, timeout=15)
        r.raise_for_status()
        html = r.text
        soup = BeautifulSoup(html, 'lxml')

        for pat in [r'(\d[.,]\d)\s*</span>\s*<span[^>]*>\((\d[\d,.]*)\s*(?:ביקורות|reviews|חוות)',
                    r'(\d[.,]\d)\s*\((\d[\d,.]*)\)']:
            m = re.search(pat, html)
            if m:
                d['rating'] = float(m.group(1).replace(',','.'))
                try: d['review_count'] = int(m.group(2).replace(',','').replace('.',''))
                except: pass
                break

        el = soup.select_one('[data-attrid*="address"] span, .LrzXr')
        if el: d['address'] = el.get_text(strip=True)
        el = soup.select_one('[data-attrid*="phone"] span, [data-attrid*="tel"] span')
        if el: d['phone'] = el.get_text(strip=True)
        else:
            m = re.search(r'0[2-9]\d[- ]?\d{3}[- ]?\d{4}', html)
            if m: d['phone'] = m.group()
        el = soup.select_one('[data-attrid*="category"] span, .YhemCb')
        if el: d['category'] = el.get_text(strip=True)
        if soup.select('[data-attrid*="image"], .bicc'): d['has_photos'] = True
        filled = sum(1 for v in [d['rating'],d['address'],d['phone'],d['category']] if v)
        d['profile_complete'] = filled >= 3
    except Exception as e:
        print(f"  [!] Google Business: {e}")
    return d

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  שלב 2 — ניתוח אתר
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def fetch_site(url, pw_page=None):
    """שולף דף עם Playwright (דפדפן אמיתי שמריץ JavaScript)"""
    own_browser = False
    try:
        t0 = time.time()

        if pw_page:
            page = pw_page
        else:
            # פתח דפדפן זמני
            own_browser = True
            pw = sync_playwright().start()
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_extra_http_headers({
                "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8,en;q=0.7"
            })

        page.goto(url, wait_until="networkidle", timeout=30000)
        # חכה שהדף יטען לגמרי
        page.wait_for_timeout(2000)
        # גלול למטה כדי לטעון lazy content
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(1000)
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(500)

        html = page.content()
        final_url = page.url
        lt = time.time() - t0
        size = len(html.encode('utf-8')) / 1024

        if own_browser:
            browser.close()
            pw.stop()

        return html, lt, size, final_url
    except Exception as e:
        print(f"  [!] אתר {url}: {e}")
        if own_browser:
            try: browser.close(); pw.stop()
            except: pass
        # fallback ל-requests
        try:
            print(f"  [*] מנסה fallback עם requests...")
            t0 = time.time()
            r = requests.get(url, headers=HEADERS, timeout=20, allow_redirects=True)
            lt = time.time() - t0
            r.raise_for_status()
            return r.text, lt, len(r.content)/1024, r.url
        except Exception as e2:
            print(f"  [!] גם requests נכשל: {e2}")
            return None, 0, 0, url

def _count(haystack, needles):
    return sum(1 for n in needles if n in haystack)

def _count_weighted(haystack, needles_weights):
    """חיפוש משוקלל — מילים חזקות שוות יותר"""
    return sum(w for n, w in needles_weights if n in haystack)

def _find_in_attrs(tag, needles):
    """בודק אם אחת המילים מופיעה באחד מה-attributes של תגית"""
    attrs_text = ' '.join(str(v) for v in tag.attrs.values() if isinstance(v, str)).lower()
    return any(n in attrs_text for n in needles)

def discover_internal_pages(base_url, soup):
    """מאתר עמודים פנימיים חשובים באתר"""
    parsed_base = urlparse(base_url)
    base_domain = parsed_base.netloc.lower()
    found = {}

    # קטגוריות עמודים חשובים לניתוח
    page_patterns = {
        'about': ['about','אודות','מי-אנחנו','מי_אנחנו','about-us','our-story','הסיפור-שלנו'],
        'contact': ['contact','צור-קשר','צור_קשר','contact-us','יצירת-קשר'],
        'services': ['services','שירותים','מה-אנחנו-עושים','what-we-do','our-services'],
        'portfolio': ['portfolio','פורטפוליו','עבודות','projects','our-work','gallery','גלריה'],
        'testimonials': ['testimonials','המלצות','reviews','חוות-דעת','לקוחות-ממליצים'],
        'pricing': ['pricing','מחירים','מחירון','plans','תוכניות','packages','חבילות'],
        'blog': ['blog','בלוג','מאמרים','articles','news','חדשות'],
        'faq': ['faq','שאלות','שאלות-נפוצות','שאלות-ותשובות'],
    }

    for a in soup.find_all('a', href=True):
        href = a.get('href', '').strip()
        if not href or href.startswith(('#', 'mailto:', 'tel:', 'javascript:')):
            continue

        # בנה URL מלא
        full_url = urljoin(base_url, href)
        parsed = urlparse(full_url)

        # רק עמודים מאותו דומיין
        if parsed.netloc.lower() != base_domain:
            continue

        path = parsed.path.lower().rstrip('/')
        link_text = a.get_text(strip=True).lower()

        # בדוק אם העמוד שייך לקטגוריה חשובה
        for category, patterns in page_patterns.items():
            if category in found:
                continue
            for pat in patterns:
                if pat in path or pat in link_text:
                    found[category] = full_url
                    break

    return found

def fetch_multiple_pages(base_url, internal_pages, max_pages=6):
    """שולף מספר עמודים עם דפדפן אחד משותף ומחזיר את ה-HTML המאוחד"""
    all_html = []
    total_lt = 0
    total_size = 0
    pages_fetched = [base_url]

    pw = None
    browser = None
    try:
        # פתח דפדפן אחד לכל העמודים
        print("  [*] מפעיל דפדפן לסריקה...")
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_extra_http_headers({
            "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8,en;q=0.7"
        })

        # שלוף עמוד ראשי
        html, lt, size, final_url = fetch_site(base_url, pw_page=page)
        if not html:
            browser.close(); pw.stop()
            return None, [], 0, 0, base_url
        all_html.append(html)
        total_lt += lt
        total_size += size

        # שלוף עמודים פנימיים
        fetched = 0
        for category, page_url in internal_pages.items():
            if fetched >= max_pages - 1:
                break
            if page_url == base_url or page_url == final_url:
                continue
            print(f"    📄 סורק: {category} → {page_url}")
            p_html, p_lt, p_size, _ = fetch_site(page_url, pw_page=page)
            if p_html and len(p_html) > 500:
                all_html.append(p_html)
                total_lt += p_lt
                total_size += p_size
                pages_fetched.append(page_url)
                fetched += 1

        browser.close()
        pw.stop()
    except Exception as e:
        print(f"  [!] שגיאה בדפדפן: {e}")
        try:
            if browser: browser.close()
            if pw: pw.stop()
        except: pass

    if not all_html:
        return None, [], 0, 0, base_url

    # אחד את כל ה-HTML לניתוח מקיף
    combined_html = '\n'.join(all_html)
    avg_lt = total_lt / len(pages_fetched) if pages_fetched else 0
    return combined_html, pages_fetched, avg_lt, total_size, base_url

def analyze_site(url):
    res = {'ok':False,'url':url,'design':{},'conv':{},'trust':{},'ux':{},'techs':[],'seo':{},'pages_scanned':[]}
    if not url: return res

    pw = None
    browser = None
    try:
        # פתח דפדפן אחד לכל הסריקה
        print(f"  [*] מפעיל דפדפן Chromium לסריקה מלאה...")
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_extra_http_headers({
            "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8,en;q=0.7"
        })

        # שלב 1: שלוף עמוד ראשי כדי לגלות עמודים פנימיים
        print(f"  [*] סורק עמוד ראשי: {url}")
        homepage_html, hp_lt, hp_size, final_url = fetch_site(url, pw_page=page)
        if not homepage_html:
            browser.close(); pw.stop()
            return res

        homepage_soup = BeautifulSoup(homepage_html, 'lxml')

        # שלב 2: גלה עמודים פנימיים
        internal_pages = discover_internal_pages(final_url, homepage_soup)
        if internal_pages:
            print(f"  [+] נמצאו {len(internal_pages)} עמודים פנימיים: {', '.join(internal_pages.keys())}")
        else:
            print(f"  [*] לא נמצאו עמודים פנימיים נוספים")

        # שלב 3: שלוף עמודים פנימיים עם אותו דפדפן
        all_html = [homepage_html]
        pages_fetched = [final_url]
        total_lt = hp_lt
        total_size = hp_size
        fetched = 0
        for category, page_url in internal_pages.items():
            if fetched >= 5:
                break
            if page_url == url or page_url == final_url:
                continue
            print(f"    📄 סורק: {category} → {page_url}")
            p_html, p_lt, p_size, _ = fetch_site(page_url, pw_page=page)
            if p_html and len(p_html) > 500:
                all_html.append(p_html)
                total_lt += p_lt
                total_size += p_size
                pages_fetched.append(page_url)
                fetched += 1

        browser.close()
        pw.stop()

        html = '\n'.join(all_html)
        avg_lt = total_lt / len(pages_fetched) if pages_fetched else 0

    except Exception as e:
        print(f"  [!] שגיאה: {e}")
        try:
            if browser: browser.close()
            if pw: pw.stop()
        except: pass
        return res

    if not html: return res

    # שמור HTML לדיבאג
    debug_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug_html.txt")
    try:
        with open(debug_path, 'w', encoding='utf-8') as df:
            df.write(html)
        print(f"  [DEBUG] HTML נשמר ב: {debug_path} ({len(html)} תווים)")
    except: pass

    res['ok'] = True
    res['url'] = final_url
    res['pages_scanned'] = pages_fetched
    low = html.lower()
    soup = BeautifulSoup(html, 'lxml')
    lt = avg_lt

    # ══════════════════════════════════════
    #  ניתוח עיצוב — חכם ומדויק
    # ══════════════════════════════════════
    dp, dm = [], []
    ds = 4  # בסיס

    # בדיקת CSS מודרני — גם ב-style tags וגם inline
    style_blocks = ' '.join(s.get_text() for s in soup.find_all('style'))
    style_combined = (style_blocks + ' ' + low).lower()

    modern_css = _count(style_combined, ['display:flex','display: flex','display:grid','display: grid',
        'var(--','css-grid','flexbox','gap:','aspect-ratio','clamp(','min(','max('])
    has_custom_props = 'var(--' in style_combined or ':root' in style_combined
    has_modern_layout = any(x in style_combined for x in ['display:grid','display: grid','display:flex','display: flex'])

    if modern_css >= 4: ds += 2; dp.append('טכנולוגיות CSS מודרניות (Flex/Grid/Variables)')
    elif modern_css >= 2: ds += 1; dp.append('שימוש בסיסי ב-CSS מודרני')
    else: dm.append('לא משתמש בטכנולוגיות עיצוב מודרניות')

    # אנימציות — בדיקה מעמיקה
    anim_patterns = ['animation','@keyframes','transition','transform','aos-init','aos-animate',
        'gsap','lottie','fade-in','slide-','wow ','animate__','motion','framer-motion',
        'data-aos','data-animate','data-scroll','reveal','parallax']
    anim_count = _count(style_combined, anim_patterns)
    if anim_count >= 3: ds += 1; dp.append('אנימציות ואפקטים חזותיים מתקדמים')
    elif anim_count >= 1: dp.append('אנימציות בסיסיות')
    else: dm.append('אין אנימציות או אפקטים חזותיים')

    # פונטים מותאמים
    font = any(f in low for f in ['fonts.googleapis','font-face','typekit','fonts.adobe','fontsource',
        'woff2','woff','font-display'])
    if font: ds += 1; dp.append('פונטים מותאמים אישית')

    # Hero Section — בדיקה חכמה
    hero_by_class = bool(soup.find(class_=re.compile(r'hero|banner|jumbotron|masthead|splash|intro-section|main-banner', re.I)))
    hero_by_id = bool(soup.find(id=re.compile(r'hero|banner|masthead|splash|intro', re.I)))
    hero_by_tag = bool(soup.find(['section','div'], class_=re.compile(r'slider|carousel|swiper|slick', re.I)))
    hero_by_structure = bool(soup.select('header + section, header + div > h1, .hero-content, .banner-content'))
    has_hero = hero_by_class or hero_by_id or hero_by_tag or hero_by_structure
    if has_hero: ds += 1; dp.append('Hero/Banner Section בולט')
    else: dm.append('חסר Hero Section בראש הדף')

    # תמונות איכותיות
    imgs = soup.find_all('img')
    has_quality_imgs = len(imgs) >= 3
    has_lazy_load = any(img.get('loading') == 'lazy' or 'lazy' in str(img.get('class','')) or img.get('data-src') for img in imgs)
    has_webp = any('.webp' in str(img.get('src','')) or '.webp' in str(img.get('data-src','')) for img in imgs)
    if has_quality_imgs: dp.append(f'{len(imgs)} תמונות באתר')
    else: dm.append('מעט תמונות באתר')
    if has_webp or has_lazy_load: ds += 1; dp.append('אופטימיזציית תמונות (WebP/Lazy Load)')

    # וידאו
    has_video = bool(soup.find(['video','iframe'], src=re.compile(r'youtube|vimeo|wistia|vidyard|loom', re.I))) or \
                any('youtube' in str(iframe.get('src','')) or 'vimeo' in str(iframe.get('src','')) for iframe in soup.find_all('iframe'))
    if has_video: ds += 1; dp.append('תוכן וידאו')

    # Favicon
    has_favicon = bool(soup.find('link', rel=re.compile(r'icon|shortcut', re.I)))
    if not has_favicon: dm.append('חסר Favicon (אייקון בטאב)')

    res['design'] = {'score': max(1, min(10, ds)), 'plus': dp, 'minus': dm}

    # ══════════════════════════════════════
    #  ניתוח המרה — חכם ומדויק
    # ══════════════════════════════════════
    cp, cm = [], []
    cs = 1  # בסיס נמוך

    # וואטסאפ — בדיקה מקיפה
    wa_patterns = ['whatsapp','wa.me','api.whatsapp','whatsapp.com','wa-widget',
        'btn-whatsapp','whatsapp-button','wa-button','click.wa','wa-chat','whatsapp-chat']
    has_wa = any(w in low for w in wa_patterns) or \
             bool(soup.find('a', href=re.compile(r'wa\.me|whatsapp|api\.whatsapp', re.I)))
    # גם בדוק data attributes
    if not has_wa:
        has_wa = bool(soup.find(attrs={'data-action': re.compile(r'whatsapp', re.I)})) or \
                 bool(soup.find(class_=re.compile(r'whatsapp|wa-btn|wa-float', re.I)))

    # טופס — בדיקה מתקדמת
    has_form = False
    form_type = None
    # 1. טפסים רגילים
    for f in soup.find_all('form'):
        form_text = (f.get_text() + str(f.get('action','')) + str(f.get('class','')) + str(f.get('id',''))).lower()
        if re.search(r'contact|lead|form|טופס|פרטים|צור.?קשר|השאר|newsletter|subscribe|הרשמ|register|signup|sign.?up|inquiry|פנייה', form_text, re.I):
            has_form = True; form_type = 'contact'; break
    # 2. בדיקה לפי input fields (אתרי React/Vue שלא משתמשים ב-<form>)
    if not has_form:
        contact_inputs = []
        for i in soup.find_all('input'):
            attrs_text = ' '.join([str(i.get('type','')), str(i.get('name','')),
                str(i.get('placeholder','')), str(i.get('id','')), str(i.get('class',''))]).lower()
            if re.search(r'email|phone|name|tel|שם|טלפון|מייל|mail|נייד|mobile', attrs_text):
                contact_inputs.append(i)
        if len(contact_inputs) >= 2:
            has_form = True; form_type = 'inputs'
    # 3. textarea (טופס "ספר לנו")
    if not has_form:
        textareas = soup.find_all('textarea')
        if textareas and soup.find_all('input', attrs={'type': re.compile(r'email|tel', re.I)}):
            has_form = True; form_type = 'textarea'
    # 4. בדיקת פלטפורמות טפסים חיצוניות
    external_forms = ['typeform','jotform','google.com/forms','hubspot','mailchimp',
        'elementor-form','wpforms','gravity','ninja-forms','contact-form-7','cf7',
        'forminator','fluent-form','wufoo','tally.so','paperform']
    has_external_form = any(ef in low for ef in external_forms)
    if has_external_form and not has_form:
        has_form = True; form_type = 'external'

    # CTA — בדיקה חכמה יותר
    cta_strong = ['צור קשר','הזמן עכשיו','קבל הצעת מחיר','קנה עכשיו','התחל עכשיו','הירשם עכשיו',
        'בואו נדבר','קבע פגישה','השאר פרטים','הצטרף עכשיו','נסה בחינם','התחל ניסיון',
        'contact us','get started','buy now','sign up','free trial','get quote','book now',
        'book a demo','schedule a call','start free','try free','order now','get offer',
        'לפרטים נוספים','למידע נוסף','לתיאום פגישה','שלח הודעה','דברו איתנו']
    cta_weak = ['learn more','read more','קרא עוד','גלה עוד','פרטים','more info']

    # בדוק CTA בכפתורים ובלינקים עם class שנראה כמו כפתור
    cta_elements = soup.find_all(['button','a'])
    strong_cta_found = 0
    weak_cta_found = 0
    for el in cta_elements:
        el_text = el.get_text(strip=True).lower()
        el_class = str(el.get('class','')).lower()
        is_button_style = any(b in el_class for b in ['btn','button','cta','action','primary'])
        if any(k in el_text for k in cta_strong):
            strong_cta_found += 1
        elif any(k in el_text for k in cta_weak) and is_button_style:
            weak_cta_found += 1

    has_cta = strong_cta_found > 0
    has_weak_cta = weak_cta_found > 0

    # יצירת קשר מוקדמת — בדיקה ב-20% הראשונים של ה-HTML
    first_part = low[:len(low)//5]
    early_contact = any(e in first_part for e in ['צור קשר','contact','whatsapp','wa.me','tel:',
        'טלפון','השאר פרטים','קבע פגישה','book','schedule','התקשר','call us','דברו איתנו'])

    # טלפון לחיץ
    tel_links = soup.find_all('a', href=re.compile(r'^tel:', re.I))
    has_tel = len(tel_links) > 0
    # גם בדוק מספרי טלפון בטקסט (ישראליים)
    phone_in_text = bool(re.search(r'0[2-9]\d[- ]?\d{3,4}[- ]?\d{3,4}', soup.get_text()))

    # צ'אט חי — בדיקה מורחבת
    chat_services = ['tawk','crisp','intercom','drift','livechat','tidio','zendesk','freshchat',
        'hubspot','olark','chatra','smartsupp','liveperson','comm100','purechat','clickdesk',
        'jivochat','kayako','zoho-chat','zopim','lc-widget','fb-customerchat',
        'messenger-checkbox','m.me/','facebook.com/dialog']
    has_chat = any(c in low for c in chat_services)

    # פופאפ / exit intent
    popup_signs = ['popup','pop-up','modal','exit-intent','exitintent','optinmonster','sumo',
        'leadpages','unbounce','poptin','wisepops','privy','sleeknote','hello-bar']
    has_popup = any(p in low for p in popup_signs)

    # חישוב ציון המרה
    if has_wa: cs += 2; cp.append('כפתור וואטסאפ')
    else: cm.append('אין כפתור וואטסאפ — ערוץ התקשורת #1 בישראל')
    if has_form:
        cs += 2; cp.append(f'טופס להשארת פרטים ({form_type})')
    else: cm.append('אין טופס להשארת פרטים')
    if has_cta:
        cs += 1; cp.append(f'קריאות לפעולה חזקות (CTA) — {strong_cta_found} נמצאו')
        if strong_cta_found >= 3: cs += 1; cp.append('CTAs מרובים ברחבי האתר')
    elif has_weak_cta:
        cp.append('קריאות לפעולה חלשות בלבד')
    else: cm.append('אין קריאה ברורה לפעולה (CTA)')
    if early_contact: cs += 1; cp.append('יצירת קשר בחלק העליון של האתר')
    else: cm.append('אין יצירת קשר בתחילת האתר — גולשים עוזבים')
    if has_tel: cs += 1; cp.append(f'טלפון לחיץ ({len(tel_links)} קישורים)')
    elif phone_in_text: cs += 0.5; cp.append('מספר טלפון מופיע (אך לא לחיץ)')
    else: cm.append('אין טלפון לחיץ')
    if has_chat: cs += 1; cp.append('צ\'אט חי לשירות מיידי')
    if has_popup: cs += 0.5; cp.append('פופאפ / Exit Intent ללכידת לידים')

    res['conv'] = {'score': max(1, min(10, round(cs))), 'plus': cp, 'minus': cm,
                   'wa': has_wa, 'form': has_form, 'cta': has_cta, 'early': early_contact}

    # ══════════════════════════════════════
    #  ניתוח אמון — חכם ומדויק
    # ══════════════════════════════════════
    tp, tm = [], []
    ts = 2  # בסיס
    text = soup.get_text().lower()

    # המלצות לקוחות — בדיקה מעמיקה
    testim_in_html = _count(low, ['testimonial','review-card','testimonial-card','client-review',
        'customer-review','review-item','testimonial-item','review-slider','testimonials-section'])
    testim_in_text = _count(text, ['המלצ','חוות דעת','מה לקוחות','מה אומרים','ממליצים','לקוחות מספרים',
        'הלקוחות שלנו','סיפורי הצלחה','reviews','what our clients','what customers say','client stories'])
    # בדוק גם אלמנטים עם כוכבות דירוג
    star_ratings = bool(soup.find(class_=re.compile(r'star|rating|stars', re.I))) or '★' in text or '⭐' in text
    testim = testim_in_html >= 1 or testim_in_text >= 1 or star_ratings

    # פורטפוליו / עבודות — בדיקה מעמיקה
    portf_in_html = _count(low, ['portfolio','gallery-item','project-card','work-item','case-study',
        'portfolio-item','gallery-grid','masonry','lightbox','fancybox'])
    portf_in_text = _count(text, ['פורטפוליו','עבודות','פרויקטים','גלריה','תיק עבודות',
        'projects','our work','case studies','portfolio','gallery'])
    portf = portf_in_html >= 1 or portf_in_text >= 1

    # הסמכות ותעודות
    certs_patterns = ['certification','certified','תעודה','הסמכה','מוסמך','iso ','תו תקן',
        'accredited','licensed','מורשה','רישיון','badge','award','פרס','הכרה']
    certs = _count(text, certs_patterns) >= 1

    # דף אודות
    about_link = bool(soup.find('a', href=re.compile(r'about|אודות', re.I))) or \
                 any(re.search(r'about|אודות|מי אנחנו|our story|הסיפור שלנו', a.get_text(), re.I)
                     for a in soup.find_all('a') if a.get_text())
    about_content = any(x in text for x in ['שנות ניסיון','years of experience','הצוות שלנו',
        'our team','החזון שלנו','our vision','our mission','המשימה שלנו','founded','נוסדה'])

    # רשתות חברתיות — בדיקה מורחבת
    social_domains = ['facebook.com','instagram.com','twitter.com','x.com','linkedin.com',
        'youtube.com','tiktok.com','pinterest.com','threads.net']
    social_links = [a for a in soup.find_all('a', href=True)
                    if any(s in a.get('href','').lower() for s in social_domains)]
    has_social = len(social_links) > 0
    social_count = len(set(urlparse(a.get('href','')).netloc for a in social_links))

    # לוגואים של לקוחות / שותפים
    logos_section = bool(soup.find(class_=re.compile(r'logo|client|partner|brand|trust', re.I))) or \
                    _count(text, ['הלקוחות שלנו','our clients','שותפים','partners','trusted by','סומכים עלינו']) >= 1

    # SSL
    has_ssl = final_url.startswith('https://')

    # מדיניות פרטיות / תנאי שימוש
    has_privacy = bool(soup.find('a', href=re.compile(r'privacy|פרטיות|terms|תנאי', re.I))) or \
                  _count(text, ['מדיניות פרטיות','privacy policy','תנאי שימוש','terms of service','terms & conditions']) >= 1

    # חישוב ציון אמון
    if testim: ts += 2; tp.append('המלצות / חוות דעת לקוחות')
    else: tm.append('אין המלצות לקוחות — 92% מהצרכנים קוראים ביקורות')
    if portf: ts += 1; tp.append('עבודות קודמות / פורטפוליו')
    else: tm.append('אין פורטפוליו / עבודות קודמות')
    if certs: ts += 1; tp.append('תעודות / הסמכות / פרסים')
    if about_link or about_content:
        ts += 1; tp.append('דף אודות / מי אנחנו')
        if about_content: tp.append('תוכן אודות עשיר (ניסיון, צוות, חזון)')
    else: tm.append('אין דף אודות')
    if has_social:
        ts += 1; tp.append(f'רשתות חברתיות ({social_count} פלטפורמות)')
    else: tm.append('אין קישורים לרשתות חברתיות')
    if logos_section: ts += 1; tp.append('לוגואים של לקוחות / שותפים')
    if has_ssl: tp.append('אתר מאובטח (HTTPS/SSL)')
    else: ts -= 1; tm.append('אתר לא מאובטח — אין SSL!')
    if has_privacy: tp.append('מדיניות פרטיות / תנאי שימוש')
    else: tm.append('חסרה מדיניות פרטיות')

    res['trust'] = {'score': max(1, min(10, ts)), 'plus': tp, 'minus': tm,
                    'testim': testim, 'portf': portf}

    # ══════════════════════════════════════
    #  ניתוח UX — חכם ומדויק
    # ══════════════════════════════════════
    up, um = [], []
    us = 4  # בסיס

    # מותאם למובייל — בדיקות מרובות
    viewport = bool(soup.find('meta', attrs={'name': 'viewport'}))
    responsive_css = any(x in style_combined for x in ['@media','media screen','max-width:','min-width:'])
    mobile_classes = _count(low, ['col-sm','col-md','col-lg','col-xl','sm:','md:','lg:','xl:',
        'mobile','responsive','d-none','d-block','hidden-xs','visible-xs'])
    is_mobile_friendly = viewport and (responsive_css or mobile_classes > 0)
    if is_mobile_friendly: us += 2; up.append('מותאם למובייל (Viewport + Responsive CSS)')
    elif viewport: us += 1; up.append('יש Viewport Meta (התאמה בסיסית למובייל)')
    else: us -= 2; um.append('לא מותאם למובייל — בעיה קריטית! 70%+ גולשים מהנייד')

    # ניווט
    nav = soup.find('nav')
    header_links = soup.select('header a, .navbar a, .nav a, .menu a, [role="navigation"] a')
    hamburger = bool(soup.find(class_=re.compile(r'hamburger|burger|toggle|menu-btn|mobile-menu', re.I))) or \
                bool(soup.find(attrs={'aria-label': re.compile(r'menu|navigation|תפריט', re.I)}))
    nav_items = len(header_links) if header_links else (len(nav.find_all('a')) if nav else 0)
    if nav or nav_items >= 3:
        us += 1; up.append(f'ניווט ברור ({nav_items} קישורים)')
        if hamburger: up.append('תפריט המבורגר למובייל')
    else: us -= 1; um.append('ניווט לא ברור או חסר')

    # Footer
    footer = soup.find('footer')
    if footer:
        footer_links = len(footer.find_all('a'))
        us += 1; up.append(f'Footer עם מידע ({footer_links} קישורים)')
    else: um.append('אין Footer — חסר מידע בתחתית האתר')

    # מהירות טעינה
    if lt < 2: us += 2; up.append(f'טעינה מהירה מאוד ({lt:.1f}s)')
    elif lt < 3: us += 1; up.append(f'טעינה מהירה ({lt:.1f}s)')
    elif lt < 5: up.append(f'טעינה סבירה ({lt:.1f}s)')
    else: us -= 1; um.append(f'טעינה איטית ({lt:.1f}s) — גולשים עוזבים אחרי 3 שניות')

    # נגישות בסיסית
    alt_imgs = [img for img in imgs if img.get('alt')]
    aria_labels = soup.find_all(attrs={'aria-label': True})
    has_h1 = bool(soup.find('h1'))
    accessibility_score = 0
    if len(alt_imgs) >= len(imgs) * 0.5 and len(imgs) > 0: accessibility_score += 1
    if len(aria_labels) >= 3: accessibility_score += 1
    if has_h1: accessibility_score += 1
    if accessibility_score >= 2: up.append('נגישות בסיסית תקינה (Alt, ARIA, H1)')
    elif accessibility_score == 1: up.append('נגישות חלקית')
    else: um.append('בעיות נגישות — חסרים Alt, ARIA labels')

    # משקל דף
    page_size_kb = total_size
    if page_size_kb < 500: up.append(f'משקל דף קל ({page_size_kb:.0f}KB)')
    elif page_size_kb < 2000: up.append(f'משקל דף סביר ({page_size_kb:.0f}KB)')
    elif page_size_kb > 5000: us -= 1; um.append(f'דף כבד מאוד ({page_size_kb:.0f}KB) — פוגע בביצועים')

    # 404 / שגיאות
    broken_indicators = _count(low, ['404','page not found','not found','שגיאה','error page'])
    if broken_indicators > 0: um.append('נמצאו סימנים לשגיאות 404')

    res['ux'] = {'score': max(1, min(10, us)), 'plus': up, 'minus': um, 'viewport': viewport}

    # ══════════════════════════════════════
    #  טכנולוגיות — בדיקה מורחבת
    # ══════════════════════════════════════
    sigs = {
        'WordPress': ['wp-content','wp-includes','wordpress'],
        'Wix': ['wix.com','static.wixstatic','wixsite'],
        'Squarespace': ['squarespace.com','sqsp.net'],
        'Shopify': ['shopify.com','cdn.shopify','myshopify'],
        'Webflow': ['webflow.io','webflow.com','w-nav'],
        'Elementor': ['elementor','elementor-widget'],
        'Divi': ['divi','et_pb_','et-db'],
        'React': ['react','__next','_next/static','reactroot','data-reactroot'],
        'Vue.js': ['vue.js','nuxt','__nuxt','data-v-'],
        'Angular': ['ng-version','ng-app','angular'],
        'Next.js': ['_next/','__next','next.js'],
        'Gatsby': ['gatsby','___gatsby'],
        'Bootstrap': ['bootstrap'],
        'Tailwind CSS': ['tailwind','tw-'],
        'Material UI': ['mui','material-ui','mdc-'],
        'jQuery': ['jquery','jquery.min.js'],
        'Google Analytics': ['google-analytics','gtag(','ga.js','analytics.js'],
        'Google Tag Manager': ['googletagmanager','gtm.js','gtm.start'],
        'Facebook Pixel': ['fbevents.js','facebook.com/tr','fbq('],
        'Hotjar': ['hotjar','_hjSettings'],
        'Cloudflare': ['cloudflare','cf-ray','cdnjs.cloudflare'],
        'reCAPTCHA': ['recaptcha','grecaptcha'],
    }
    res['techs'] = [n for n, ss in sigs.items() if any(s in low for s in ss)]

    # ══════════════════════════════════════
    #  SEO — ניתוח מקיף
    # ══════════════════════════════════════
    seo = {}
    title_tag = soup.find('title')
    seo['title'] = title_tag.string.strip() if title_tag and title_tag.string else ''
    seo['title_len'] = len(seo['title'])

    meta_desc = soup.find('meta', attrs={'name': 'description'})
    seo['description'] = meta_desc.get('content','').strip() if meta_desc else ''
    seo['desc_len'] = len(seo['description'])

    h1_tags = soup.find_all('h1')
    seo['h1_count'] = len(h1_tags)
    seo['h1_text'] = h1_tags[0].get_text(strip=True)[:100] if h1_tags else ''

    h2_tags = soup.find_all('h2')
    seo['h2_count'] = len(h2_tags)

    # Canonical
    canonical = soup.find('link', rel='canonical')
    seo['canonical'] = bool(canonical)

    # Open Graph
    og_tags = soup.find_all('meta', attrs={'property': re.compile(r'^og:', re.I)})
    seo['og_count'] = len(og_tags)

    # Schema / Structured Data
    schema_scripts = soup.find_all('script', type=re.compile(r'application/ld\+json', re.I))
    seo['schema'] = len(schema_scripts) > 0

    # Alt texts
    imgs_total = len(imgs)
    imgs_with_alt = len([img for img in imgs if img.get('alt','').strip()])
    seo['alt_ratio'] = f'{imgs_with_alt}/{imgs_total}' if imgs_total > 0 else 'N/A'

    # Sitemap / Robots hints
    seo['has_robots'] = bool(soup.find('meta', attrs={'name': 'robots'}))

    # SEO score
    seo_score = 3
    seo_plus = []
    seo_minus = []
    if seo['title'] and 10 <= seo['title_len'] <= 70: seo_score += 1; seo_plus.append(f'כותרת תקינה ({seo["title_len"]} תווים)')
    elif seo['title']: seo_plus.append(f'כותרת קיימת (אורך: {seo["title_len"]})')
    else: seo_score -= 1; seo_minus.append('חסרה כותרת (Title Tag)')
    if seo['description'] and 50 <= seo['desc_len'] <= 160: seo_score += 1; seo_plus.append(f'Meta Description תקין ({seo["desc_len"]} תווים)')
    elif seo['description']: seo_plus.append(f'Meta Description קיים (אורך: {seo["desc_len"]})')
    else: seo_score -= 1; seo_minus.append('חסר Meta Description')
    if seo['h1_count'] == 1: seo_score += 1; seo_plus.append('H1 יחיד ותקין')
    elif seo['h1_count'] > 1: seo_minus.append(f'יותר מ-H1 אחד ({seo["h1_count"]}) — בעייתי ל-SEO')
    else: seo_score -= 1; seo_minus.append('חסר H1')
    if seo['h2_count'] >= 2: seo_plus.append(f'{seo["h2_count"]} כותרות H2')
    if seo['canonical']: seo_score += 1; seo_plus.append('Canonical URL מוגדר')
    if seo['og_count'] >= 3: seo_score += 1; seo_plus.append(f'Open Graph Tags ({seo["og_count"]})')
    else: seo_minus.append('חסרים Open Graph Tags (שיתוף ברשתות)')
    if seo['schema']: seo_score += 1; seo_plus.append('Schema / Structured Data (JSON-LD)')
    else: seo_minus.append('חסר Schema Markup — פוגע בהופעה בגוגל')
    if has_ssl: seo_plus.append('HTTPS (גורם דירוג בגוגל)')

    seo['score'] = max(1, min(10, seo_score))
    seo['plus'] = seo_plus
    seo['minus'] = seo_minus
    res['seo'] = seo
    return res

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  שלב 3 — ציון + נקודות איבוד
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def gb_score(gb):
    s = 3; ip = []; im = []
    rat = gb.get('rating')
    rc = gb.get('review_count')
    if rat:
        if rat>=4.5: s+=3; ip.append(f'דירוג מצוין: {rat}/5')
        elif rat>=4: s+=2; ip.append(f'דירוג טוב: {rat}/5')
        elif rat>=3.5: s+=1; im.append(f'דירוג בינוני: {rat}/5')
        else: s-=1; im.append(f'דירוג נמוך: {rat}/5')
    else: s-=1; im.append('לא נמצא דירוג בגוגל')
    if rc:
        if rc>=100: s+=2; ip.append(f'כמות ביקורות מרשימה: {rc}')
        elif rc>=30: s+=1; ip.append(f'ביקורות סבירות: {rc}')
        elif rc>=10: im.append(f'מעט ביקורות: {rc}')
        else: s-=1; im.append(f'מעט מאוד ביקורות: {rc}')
    else: im.append('לא נמצאו ביקורות')
    if gb.get('has_photos'): s+=1; ip.append('תמונות בפרופיל')
    else: im.append('אין תמונות בפרופיל')
    if gb.get('profile_complete'): s+=1; ip.append('פרופיל מלא')
    else: im.append('פרופיל לא מלא')
    return max(1,min(10,s)), ip, im

def lost_points(site, gb):
    pts = []
    def add(t,d,i,cat): pts.append({'t':t,'d':d,'i':i,'cat':cat})
    if not site.get('ok'):
        add('אין אתר אינטרנט פעיל','בעולם של היום, עסק בלי אתר מאבד את רוב הלקוחות שמחפשים מידע אונליין.','critical','website')
        if not gb.get('rating'):
            add('אין נוכחות בגוגל','לקוחות שמחפשים בגוגל לא מוצאים את העסק. פרופיל Google Business מלא יכול להביא עשרות לקוחות חדשים.','critical','google')
        return pts
    c = site['conv']
    # המרה
    if not c.get('form') and not c.get('wa'): add('אין מערכת ללכידת לידים','האתר לא מציע דרך קלה ללקוח להשאיר פרטים. לקוחות שנכנסים יוצאים בלי להשאיר פרטים.','critical','conversion')
    if not c.get('form'): add('אין טופס להשארת פרטים','טופס יצירת קשר הוא הדרך הפשוטה ביותר ללכוד לידים. בלעדיו, לקוחות שלא רוצים להתקשר עוזבים.','critical','conversion')
    if not c.get('wa'): add('אין כפתור וואטסאפ','וואטסאפ הוא ערוץ התקשורת המועדף בישראל. כפתור וואטסאפ צף יכול להגדיל המרות ב-30%+.','high','conversion')
    if not c.get('cta'): add('אין קריאה ברורה לפעולה (CTA)','בלי CTA ברורים, הגולש לא יודע מה הצעד הבא — וזה גורם לנטישה.','high','conversion')
    if not c.get('early'): add('אין יצירת קשר בתחילת האתר','רוב הגולשים לא גוללים לסוף. בלי יצירת קשר בחלק העליון — הם עוזבים.','high','conversion')
    # אמון
    if not site['trust'].get('testim'): add('אין המלצות לקוחות','92% מהצרכנים קוראים ביקורות לפני רכישה. בלי המלצות — אין הוכחת אמון.','high','trust')
    if not site['trust'].get('portf'): add('אין פורטפוליו / עבודות קודמות','לקוחות רוצים לראות דוגמאות של עבודות. בלי זה — קשה לבנות אמון.','medium','trust')
    # UX
    if not site['ux'].get('viewport'): add('לא מותאם למובייל','70%+ מהגלישה בישראל מהנייד. אתר לא מותאם מאבד את רוב הלקוחות.','critical','ux')
    if site['ux']['score'] <= 4: add('חוויית משתמש ירודה','האתר מקשה על הגולש למצוא מידע ולבצע פעולות. זה גורם לנטישה מהירה.','high','ux')
    # SEO
    seo = site.get('seo', {})
    if isinstance(seo, dict) and 'score' in seo:
        if seo['score'] <= 4: add('SEO חלש — האתר לא מופיע בגוגל','בלי אופטימיזציה למנועי חיפוש, לקוחות חדשים לא מוצאים את העסק בגוגל.','high','seo')
        if not seo.get('description'): add('חסר Meta Description','תיאור האתר בתוצאות גוגל ריק — פוגע באחוז הלחיצות מגוגל.','medium','seo')
        if not seo.get('schema'): add('חסר Schema Markup','בלי נתונים מובנים, האתר מציג פחות מידע בגוגל ונראה פחות אטרקטיבי.','medium','seo')
    # עיצוב
    if site['design']['score'] <= 3: add('עיצוב לא מקצועי','עיצוב ישן או לא מקצועי גורם ללקוחות לעזוב תוך שניות. הרושם הראשוני קריטי.','high','design')
    # גוגל
    if not gb.get('rating'): add('אין פרופיל Google Business','לקוחות שמחפשים בגוגל לא מוצאים מידע. פרופיל מלא מביא עשרות לקוחות חדשים.','critical','google')
    elif gb['rating']<4: add(f'דירוג נמוך בגוגל ({gb["rating"]})','עסקים עם דירוג מעל 4.2 מקבלים פי 2 יותר פניות.','high','google')
    rc = gb.get('review_count',0)
    if rc and rc<20: add(f'מעט ביקורות ({rc})','עסקים מובילים מציגים עשרות עד מאות ביקורות.','medium','google')
    return pts

def lead_score(site, gbs):
    if not site.get('ok'): return max(1, min(3, gbs//3))
    return max(1,min(10, round(
        site['conv']['score']*.35 + site['trust']['score']*.25 +
        gbs*.20 + site['design']['score']*.10 + site['ux']['score']*.10)))

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  שלב 4 — מחולל דוח HTML
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _clr(s): return '#22c55e' if s>=8 else '#eab308' if s>=6 else '#f97316' if s>=4 else '#ef4444'
def _lbl(s): return 'מצוין' if s>=8 else 'טוב' if s>=6 else 'בינוני' if s>=4 else 'חלש' if s>=2 else 'קריטי'
def _imp_i(i): return {'critical':'🔴','high':'🟠','medium':'🟡','low':'🔵'}.get(i,'⚪')
def _imp_l(i): return {'critical':'קריטי','high':'גבוה','medium':'בינוני','low':'נמוך'}.get(i,'')
def _ring(sc,sz):
    r=(sz-16)//2; c=2*3.14159*r; p=(sc/10)*c; o=c-p; cl=_clr(sc); h=sz//2
    return f'<svg width="{sz}" height="{sz}" viewBox="0 0 {sz} {sz}"><circle cx="{h}" cy="{h}" r="{r}" fill="none" stroke="#e5e7eb" stroke-width="8"/><circle cx="{h}" cy="{h}" r="{r}" fill="none" stroke="{cl}" stroke-width="8" stroke-linecap="round" stroke-dasharray="{c}" stroke-dashoffset="{o}" transform="rotate(-90 {h} {h})" style="transition:stroke-dashoffset 1s ease-out"/><text x="{h}" y="{h-5}" text-anchor="middle" font-size="28" font-weight="bold" fill="{cl}">{sc}</text><text x="{h}" y="{h+18}" text-anchor="middle" font-size="13" fill="#6b7280">מתוך 10</text></svg>'

def gen_report(biz_name, biz_url, site, gb):
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    gbs, gbp, gbm = gb_score(gb)
    pts = lost_points(site, gb)
    ms = lead_score(site, gbs)
    mc = _clr(ms)

    cards = ''
    if site.get('ok'):
        seo_sc = site.get('seo',{}).get('score',0)
        for lbl,sc,ic in [('עיצוב',site['design']['score'],'🎨'),('המרה',site['conv']['score'],'🎯'),('אמון',site['trust']['score'],'🛡️'),('חוויית משתמש',site['ux']['score'],'📱'),('SEO',seo_sc,'🔍')]:
            cl=_clr(sc)
            cards+=f'<div style="background:#f9fafb;border-radius:12px;padding:20px 16px;text-align:center"><div style="font-size:28px;margin-bottom:8px">{ic}</div><div style="font-size:28px;font-weight:800;color:{cl}">{sc}/10</div><div style="font-size:13px;color:#6b7280;margin:4px 0 10px">{lbl}</div><div style="height:6px;background:#e5e7eb;border-radius:3px;overflow:hidden"><div style="height:100%;width:{sc*10}%;background:{cl};border-radius:3px"></div></div></div>'

    mk = lambda arr,ico: ''.join(f'<div style="padding:8px 0;font-size:14px;border-bottom:1px solid #e5e7eb;line-height:1.6">{ico} {x}</div>' for x in arr) if arr else '<div style="color:#9ca3af">—</div>'
    wp = (site['design'].get('plus',[])+site['conv'].get('plus',[])+site['trust'].get('plus',[])+site['ux'].get('plus',[])) if site.get('ok') else []
    wm = (site['design'].get('minus',[])+site['conv'].get('minus',[])+site['trust'].get('minus',[])+site['ux'].get('minus',[])) if site.get('ok') else ['לא נמצא אתר פעיל']

    lh = ''
    ic_bg = {'critical':'#fee2e2','high':'#ffedd5','medium':'#fef9c3','low':'#dbeafe'}
    ic_cl = {'critical':'#991b1b','high':'#9a3412','medium':'#854d0e','low':'#1e40af'}
    ic_bd = {'critical':'#ef4444','high':'#f97316','medium':'#eab308','low':'#3b82f6'}
    for idx,p in enumerate(pts,1):
        lh += f'<div style="background:#f9fafb;border-radius:12px;padding:20px;margin-bottom:12px;border-right:4px solid {ic_bd.get(p["i"],"#e5e7eb")}"><div style="display:flex;align-items:center;gap:10px;margin-bottom:8px"><span style="width:28px;height:28px;border-radius:50%;background:#1a1a2e;color:#fff;display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:700;flex-shrink:0">{idx}</span><span style="font-size:16px;font-weight:700;flex-grow:1">{p["t"]}</span><span style="padding:4px 12px;border-radius:20px;font-size:12px;font-weight:600;white-space:nowrap;background:{ic_bg.get(p["i"],"#f3f4f6")};color:{ic_cl.get(p["i"],"#374151")}">{_imp_i(p["i"])} {_imp_l(p["i"])}</span></div><p style="font-size:14px;color:#4b5563;line-height:1.8;padding-right:38px">{p["d"]}</p></div>'

    gb_html = ''
    if gb.get('rating'):
        sp = (gb['rating']/5)*100
        gb_html = f'<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:12px;margin-bottom:20px"><div style="background:#f9fafb;border-radius:12px;padding:20px;text-align:center"><div style="font-size:32px;font-weight:800">{gb["rating"]}</div><div style="height:6px;background:#e5e7eb;border-radius:3px;margin:8px auto;width:80%;overflow:hidden"><div style="height:100%;width:{sp}%;background:#eab308;border-radius:3px"></div></div><div style="font-size:13px;color:#6b7280">דירוג ממוצע</div></div><div style="background:#f9fafb;border-radius:12px;padding:20px;text-align:center"><div style="font-size:32px;font-weight:800">{gb.get("review_count","—")}</div><div style="font-size:13px;color:#6b7280;margin-top:8px">ביקורות</div></div><div style="background:#f9fafb;border-radius:12px;padding:20px;text-align:center"><div style="font-size:32px">{"✅" if gb.get("has_photos") else "❌"}</div><div style="font-size:13px;color:#6b7280;margin-top:8px">תמונות</div></div><div style="background:#f9fafb;border-radius:12px;padding:20px;text-align:center"><div style="font-size:32px">{"✅" if gb.get("profile_complete") else "❌"}</div><div style="font-size:13px;color:#6b7280;margin-top:8px">פרופיל מלא</div></div></div>'
    else:
        gb_html = '<div style="background:#fef3c7;color:#92400e;padding:20px;border-radius:12px;text-align:center;font-size:15px;margin-bottom:20px">לא נמצא פרופיל Google Business פעיל</div>'

    techs = ' '.join(f'<span style="background:#e0f2fe;color:#0369a1;padding:6px 14px;border-radius:20px;font-size:13px;font-weight:500">{t}</span>' for t in site.get('techs',[])) or '<span style="color:#9ca3af;font-size:14px">לא זוהו</span>'

    # SEO section
    seo_data = site.get('seo', {})
    seo_section = ''
    if site.get('ok') and isinstance(seo_data, dict) and 'score' in seo_data:
        seo_sc = seo_data['score']
        seo_cl = _clr(seo_sc)
        seo_plus_html = mk(seo_data.get('plus',[]), '✅')
        seo_minus_html = mk(seo_data.get('minus',[]), '❌')
        seo_details = ''
        if seo_data.get('title'):
            seo_details += f'<div style="padding:8px 12px;background:#f9fafb;border-radius:8px;margin-bottom:8px;font-size:13px"><strong>Title:</strong> <span style="direction:ltr;display:inline">{seo_data["title"][:80]}</span></div>'
        if seo_data.get('description'):
            seo_details += f'<div style="padding:8px 12px;background:#f9fafb;border-radius:8px;margin-bottom:8px;font-size:13px"><strong>Meta Description:</strong> <span style="direction:ltr;display:inline">{seo_data["description"][:160]}</span></div>'
        if seo_data.get('h1_text'):
            seo_details += f'<div style="padding:8px 12px;background:#f9fafb;border-radius:8px;margin-bottom:8px;font-size:13px"><strong>H1:</strong> {seo_data["h1_text"]}</div>'
        seo_section = f'<div class="s"><div class="sh"><div class="si" style="background:#fef3c7">🔍</div><div class="st">ניתוח SEO <span style="font-size:16px;color:{seo_cl};margin-right:8px">{seo_sc}/10</span></div></div>{seo_details}<div class="g2" style="margin-top:16px"><div class="fc"><div class="ft">❌ דורש שיפור</div>{seo_minus_html}</div><div class="fc"><div class="ft">✅ תקין</div>{seo_plus_html}</div></div></div>'

    # רשימת עמודים שנסרקו
    pages_scanned = site.get('pages_scanned', [])
    pages_html = ''
    if pages_scanned and len(pages_scanned) > 0:
        pages_list = ''.join(f'<div style="padding:6px 0;font-size:13px;border-bottom:1px solid #f0f2f5;direction:ltr;text-align:left"><span style="color:#6366f1;margin-left:8px">📄</span> <a href="{p}" target="_blank" style="color:#4b5563;text-decoration:none;word-break:break-all">{p}</a></div>' for p in pages_scanned)
        pages_html = f'<div class="s"><div class="sh"><div class="si" style="background:#ecfdf5">📑</div><div class="st">עמודים שנסרקו ({len(pages_scanned)})</div></div>{pages_list}</div>'

    wi = 'לעסק אין אתר פעיל. זהו חסרון קריטי — 80%+ מהלקוחות מחפשים אונליין.' if not site.get('ok') else \
         'האתר פוגע בעסק — לקוחות מקבלים רושם לא מקצועי ועוזבים.' if ms<4 else \
         'האתר בסיסי אך חסרים אלמנטים להמרה. לקוחות רבים עוזבים.' if ms<6 else \
         'האתר טוב אך יש הזדמנויות שיפור משמעותיות.' if ms<8 else \
         'האתר ברמה גבוהה. שיפורים קטנים יגדילו המרות.'
    gi = 'פרופיל חלש — לקוחות לא מקבלים מספיק מידע ופונים למתחרים.' if gbs<5 else \
         'פרופיל סביר — עידוד ביקורות יעזור לבלוט.' if gbs<7 else 'פרופיל טוב — תורם לאמון.'

    url_d = f'<a href="{biz_url}" target="_blank" style="color:#818cf8;text-decoration:none;font-size:14px">{biz_url}</a>' if biz_url else '<span style="color:#ef4444;font-size:14px">לא נמצא אתר</span>'

    return f'''<!DOCTYPE html><html lang="he" dir="rtl"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>דוח ניתוח - {biz_name}</title><link href="https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;500;600;700;800;900&display=swap" rel="stylesheet"><style>*{{margin:0;padding:0;box-sizing:border-box}}body{{font-family:'Heebo',sans-serif;background:#f0f2f5;color:#1a1a2e;line-height:1.7;direction:rtl}}.c{{max-width:900px;margin:0 auto;padding:20px}}.s{{background:#fff;border-radius:16px;padding:32px;margin-bottom:24px;box-shadow:0 2px 12px rgba(0,0,0,.06)}}.sh{{display:flex;align-items:center;gap:12px;margin-bottom:24px;padding-bottom:16px;border-bottom:2px solid #f0f2f5}}.si{{width:44px;height:44px;border-radius:12px;display:flex;align-items:center;justify-content:center;font-size:22px}}.st{{font-size:20px;font-weight:700}}.g2{{display:grid;grid-template-columns:1fr 1fr;gap:20px}}.fc{{background:#f9fafb;border-radius:12px;padding:20px}}.ft{{font-size:15px;font-weight:700;margin-bottom:12px}}.imp{{background:#f9fafb;border-right:4px solid #6366f1;padding:16px 20px;border-radius:0 8px 8px 0;margin-top:20px;font-size:14px;line-height:1.8;color:#4b5563}}@media(max-width:700px){{.g2{{grid-template-columns:1fr}}.g4{{grid-template-columns:repeat(3,1fr)}}.c{{padding:12px}}.s{{padding:20px 16px;border-radius:12px;margin-bottom:16px}}.sh{{gap:8px;margin-bottom:16px;padding-bottom:12px}}.si{{width:36px;height:36px;font-size:18px}}.st{{font-size:17px}}.imp{{padding:12px 14px;font-size:13px}}}}@media(max-width:480px){{.g4{{grid-template-columns:repeat(2,1fr)}}}}.g4{{display:grid;grid-template-columns:repeat(5,1fr);gap:16px;margin-bottom:24px}}@media print{{body{{background:#fff}}.s{{box-shadow:none;border:1px solid #e5e7eb}}}}</style></head><body><div class="c">
    <div style="background:linear-gradient(135deg,#eef2ff,#e0e7ff,#dbeafe);color:#1e293b;padding:40px 28px;border-radius:20px;margin-bottom:24px;overflow:hidden;border:1px solid #c7d2fe"><div style="display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:20px"><div style="flex:1;min-width:200px"><div style="display:inline-block;background:rgba(99,102,241,.12);padding:6px 16px;border-radius:20px;font-size:13px;margin-bottom:16px;color:#4338ca;font-weight:600">📊 דוח ניתוח דיגיטלי</div><div style="font-size:min(32px,6vw);font-weight:800;margin-bottom:8px;color:#1e293b">ניתוח נוכחות דיגיטלית</div><div style="font-size:min(24px,5vw);color:#4338ca;margin-bottom:6px;font-weight:700">{biz_name}</div><div style="font-size:13px;color:#64748b;word-break:break-all">🕐 {now} &nbsp; {url_d}</div></div><div style="text-align:center;flex-shrink:0">{_ring(ms,120)}<div style="font-size:12px;color:#64748b;margin-top:4px">ציון המרה</div></div></div></div>
    <div class="s" style="text-align:center;padding:28px 20px"><div style="font-size:20px;font-weight:700;margin-bottom:16px">ציון המרת לידים</div><div style="display:flex;align-items:center;justify-content:center;gap:20px;flex-wrap:wrap;margin-bottom:16px">{_ring(ms,140)}<div style="text-align:right"><div style="font-size:min(64px,14vw);font-weight:900;line-height:1;color:{mc}">{ms}</div><div style="font-size:16px;color:#6b7280;margin-top:4px">{_lbl(ms)}</div></div></div><p style="font-size:14px;color:#6b7280;max-width:600px;margin:0 auto;line-height:1.8">ציון זה מבוסס על ניתוח מקיף של האתר, אלמנטים להמרה, אמון דיגיטלי, חוויית משתמש ופרופיל Google Business.</p></div>
    <div class="s"><div class="sh"><div class="si" style="background:#ede9fe">🌐</div><div class="st">מצב האתר</div></div>{'<p style="color:#ef4444;font-size:16px;font-weight:600;margin-bottom:16px">⚠️ לא נמצא אתר פעיל</p>' if not site.get('ok') else ''}{f'<div class="g4">{cards}</div>' if cards else ''}<div class="g2"><div class="fc"><div class="ft">❌ חסר / דורש שיפור</div>{mk(wm,"❌")}</div><div class="fc"><div class="ft">✅ קיים ותקין</div>{mk(wp,"✅")}</div></div><div class="imp"><strong>השפעה:</strong> {wi}</div></div>
    <div class="s"><div class="sh"><div class="si" style="background:#fef3c7">📍</div><div class="st">מצב העסק בגוגל</div></div>{gb_html}<div class="g2"><div class="fc"><div class="ft">❌ חסר / דורש שיפור</div>{mk(gbm,"❌")}</div><div class="fc"><div class="ft">✅ קיים ותקין</div>{mk(gbp,"✅")}</div></div><div class="imp"><strong>השפעה:</strong> {gi}</div></div>
    <div class="s"><div class="sh"><div class="si" style="background:#fee2e2">⚡</div><div class="st">נקודות בהן העסק מפסיד לקוחות</div></div>{lh or '<div style="background:#ecfdf5;color:#065f46;padding:20px;border-radius:12px;text-align:center">לא זוהו נקודות חולשה משמעותיות 🎉</div>'}</div>
    {seo_section}
    <div class="s"><div class="sh"><div class="si" style="background:#e0f2fe">💻</div><div class="st">טכנולוגיות מזוהות</div></div><div style="display:flex;flex-wrap:wrap;gap:8px">{techs}</div></div>
    {pages_html}
    <div style="text-align:center;padding:30px;color:#9ca3af;font-size:13px">דוח זה נוצר אוטומטית ע״י מערכת ניתוח דיגיטלית מבוססת AI</div>
    </div></body></html>'''


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  שרת ווב + דף נחיתה
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

LANDING = r'''<!DOCTYPE html>
<html lang="he" dir="rtl"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>ניתוח דיגיטלי לעסקים</title>
<link href="https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;500;600;700;800;900&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Heebo',sans-serif;direction:rtl;min-height:100vh;background:linear-gradient(160deg,#f8fafc,#eef2ff,#f0f9ff);color:#1e293b;overflow-x:hidden}
.bg{position:fixed;inset:0;z-index:0;overflow:hidden}
.bg .o{position:absolute;border-radius:50%;animation:d 22s ease-in-out infinite}
.bg .o:nth-child(1){width:650px;height:650px;top:-220px;right:-120px;background:radial-gradient(circle,rgba(99,102,241,.08),transparent 70%)}
.bg .o:nth-child(2){width:450px;height:450px;bottom:-120px;left:-70px;background:radial-gradient(circle,rgba(168,85,247,.06),transparent 70%);animation-delay:-6s}
.bg .o:nth-child(3){width:320px;height:320px;top:38%;left:28%;background:radial-gradient(circle,rgba(59,130,246,.05),transparent 70%);animation-delay:-12s}
@keyframes d{0%,100%{transform:translate(0) scale(1)}33%{transform:translate(35px,-45px) scale(1.06)}66%{transform:translate(-25px,30px) scale(.94)}}
.w{position:relative;z-index:1;max-width:820px;margin:0 auto;padding:48px 20px;min-height:100vh;display:flex;flex-direction:column;justify-content:center}
.br{text-align:center;margin-bottom:44px}
.br-i{width:76px;height:76px;background:linear-gradient(135deg,#6366f1,#818cf8);border-radius:22px;display:inline-flex;align-items:center;justify-content:center;font-size:38px;margin-bottom:18px;box-shadow:0 18px 50px rgba(99,102,241,.2)}
.br h1{font-size:38px;font-weight:900;background:linear-gradient(135deg,#1e293b,#4338ca);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;margin-bottom:10px}
.br p{font-size:17px;color:#64748b;font-weight:300;max-width:520px;margin:0 auto;line-height:1.9}
.cd{background:rgba(255,255,255,.75);border:1px solid rgba(99,102,241,.12);border-radius:24px;padding:40px;backdrop-filter:blur(24px);box-shadow:0 24px 64px rgba(99,102,241,.08)}
.lb{font-size:15px;font-weight:600;color:#4338ca;margin-bottom:10px;display:block}
.ir{display:flex;gap:12px}
.ir input{flex:1;padding:18px 22px;font-size:17px;font-family:'Heebo',sans-serif;border:2px solid #e2e8f0;border-radius:16px;background:#fff;color:#1e293b;outline:none;transition:.25s;direction:ltr;text-align:right}
.ir input::placeholder{color:#94a3b8;direction:rtl}
.ir input:focus{border-color:#6366f1;box-shadow:0 0 0 4px rgba(99,102,241,.1);background:#fff}
.gb{padding:18px 38px;font-size:17px;font-weight:700;font-family:'Heebo',sans-serif;border:none;border-radius:16px;background:linear-gradient(135deg,#6366f1,#818cf8);color:#fff;cursor:pointer;transition:.25s;white-space:nowrap}
.gb:hover{transform:translateY(-2px);box-shadow:0 10px 32px rgba(99,102,241,.3)}
.gb:disabled{opacity:.65;cursor:not-allowed;transform:none;box-shadow:none}
.ch{display:flex;flex-wrap:wrap;gap:8px;margin-top:18px}
.ch span{padding:8px 16px;border-radius:10px;background:#f1f5f9;border:1px solid #e2e8f0;color:#64748b;font-size:13px;cursor:pointer;transition:.2s}
.ch span:hover{background:#eef2ff;border-color:#c7d2fe;color:#4338ca}
.st{display:none;margin-top:30px}.st.on{display:block}
.sp{display:flex;align-items:center;gap:12px;padding:11px 0;color:#94a3b8;font-size:14px;transition:.3s}
.sp.r{color:#6366f1}.sp.k{color:#22c55e}
.dt{width:30px;height:30px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:13px;background:#f8fafc;border:2px solid #e2e8f0;flex-shrink:0;transition:.3s}
.sp.r .dt{border-color:#6366f1;background:#eef2ff}
.sp.k .dt{border-color:#22c55e;background:#f0fdf4}
.sn{width:16px;height:16px;border:2px solid #c7d2fe;border-top-color:#6366f1;border-radius:50%;animation:sn .7s linear infinite}
@keyframes sn{to{transform:rotate(360deg)}}
.er{display:none;margin-top:16px;padding:14px 18px;background:#fef2f2;border:1px solid #fecaca;border-radius:12px;color:#dc2626;font-size:14px}.er.on{display:block}
.ft{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-top:44px}
.fc{background:rgba(255,255,255,.6);border:1px solid #e2e8f0;border-radius:16px;padding:22px;text-align:center}
@media(max-width:600px){
.ft{grid-template-columns:1fr}
.ir{flex-direction:column}
.ir input{font-size:16px;padding:16px 18px}
.gb{width:100%;padding:16px;font-size:16px}
.br h1{font-size:24px;line-height:1.3}
.br p{font-size:15px;line-height:1.7}
.br-i{width:60px;height:60px;font-size:30px;border-radius:18px}
.cd{padding:24px 18px;border-radius:18px}
.w{padding:24px 14px}
.br{margin-bottom:28px}
.lb{font-size:14px}
.ch{gap:6px}
.ch span{padding:6px 12px;font-size:12px}
.sp{font-size:13px;padding:9px 0}
.fc{padding:16px}
.conn{bottom:10px;left:10px;font-size:11px;padding:6px 12px}
}
@media(max-width:380px){
.br h1{font-size:21px}
.ir input{font-size:15px;padding:14px 14px}
}
.conn{position:fixed;bottom:20px;left:20px;z-index:99;padding:8px 16px;border-radius:10px;background:#f0fdf4;border:1px solid #bbf7d0;color:#16a34a;font-size:12px;backdrop-filter:blur(8px)}
</style></head><body>
<div class="bg"><div class="o"></div><div class="o"></div><div class="o"></div></div>
<div class="w">
  <div class="br"><div class="br-i">🔍</div><h1>ניתוח דיגיטלי לעסקים</h1><p>הזן שם עסק או כתובת אתר וקבל דוח מקצועי שמנתח את הנוכחות הדיגיטלית ומראה איפה העסק מפסיד לקוחות</p></div>
  <div class="cd">
    <label class="lb">שם העסק או כתובת האתר</label>
    <form class="ir" onsubmit="go(event)">
      <input id="q" placeholder="לדוגמה: https://www.example.com או פיצה רומא פתח תקווה" autocomplete="off" required/>
      <button class="gb" id="btn" type="submit">🔎 נתח עכשיו</button>
    </form>
    <div class="ch"><span onclick="f('https://www.fiverr.com')">fiverr.com</span><span onclick="f('https://www.wix.com')">wix.com</span><span onclick="f('https://www.monday.com')">monday.com</span><span onclick="f('https://www.zara.com')">zara.com</span></div>
    <div class="st" id="steps">
      <div class="sp" id="s1"><div class="dt">1</div>מאתר מידע על העסק…</div>
      <div class="sp" id="s2"><div class="dt">2</div>סורק את כל עמודי האתר…</div>
      <div class="sp" id="s3"><div class="dt">3</div>בודק פרופיל Google Business…</div>
      <div class="sp" id="s4"><div class="dt">4</div>מחשב ציונים ומנתח…</div>
      <div class="sp" id="s5"><div class="dt">5</div>מכין דוח מקצועי…</div>
    </div>
    <div class="er" id="err"></div>
  </div>
  <div class="ft">
    <div class="fc"><div style="font-size:26px;margin-bottom:10px">🌐</div><div style="font-size:14px;font-weight:700;color:#1e293b;margin-bottom:4px">סריקת כל האתר</div><div style="font-size:12px;color:#64748b">עמוד ראשי + עמודים פנימיים</div></div>
    <div class="fc"><div style="font-size:26px;margin-bottom:10px">📍</div><div style="font-size:14px;font-weight:700;color:#1e293b;margin-bottom:4px">Google Business</div><div style="font-size:12px;color:#64748b">דירוג, ביקורות, נוכחות</div></div>
    <div class="fc"><div style="font-size:26px;margin-bottom:10px">🎯</div><div style="font-size:14px;font-weight:700;color:#1e293b;margin-bottom:4px">ציון המרה</div><div style="font-size:12px;color:#64748b">1-10 עם נקודות חולשה</div></div>
  </div>
</div>
<div class="conn">🟢 שרת מקומי פעיל — סריקה מלאה</div>
<script>
const $=id=>document.getElementById(id);
function f(v){$('q').value=v;$('q').focus()}
function rs(){for(let i=1;i<=5;i++){const s=$('s'+i);s.className='sp';s.querySelector('.dt').innerHTML=i}}
function run(n){const s=$('s'+n);s.className='sp r';s.querySelector('.dt').innerHTML='<div class="sn"></div>'}
function ok(n){const s=$('s'+n);s.className='sp k';s.querySelector('.dt').innerHTML='✓'}
async function go(e){
  e.preventDefault();
  const q=$('q').value.trim(); if(!q) return;
  $('btn').disabled=true;
  $('err').className='er';
  $('steps').className='st on';
  rs();
  try{
    run(1);
    const r=await fetch('/analyze',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'query='+encodeURIComponent(q)});
    ok(1);run(2);await new Promise(r=>setTimeout(r,400));ok(2);
    run(3);await new Promise(r=>setTimeout(r,300));ok(3);
    run(4);await new Promise(r=>setTimeout(r,200));ok(4);
    run(5);await new Promise(r=>setTimeout(r,200));ok(5);
    if(!r.ok) throw new Error('שגיאת שרת');
    const html=await r.text();
    await new Promise(r=>setTimeout(r,300));
    document.open();document.write(html);document.close();
  }catch(ex){
    $('err').textContent='שגיאה: '+(ex.message||'נסה שנית');
    $('err').className='er on';
  }finally{$('btn').disabled=false}
}
$('q').addEventListener('keydown',e=>{if(e.key==='Enter')go(e)});
</script></body></html>'''


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ('/','/index.html'):
            self.send_response(200)
            self.send_header('Content-Type','text/html; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin','*')
            self.end_headers()
            self.wfile.write(LANDING.encode())
        else:
            self.send_response(404); self.end_headers()

    def do_POST(self):
        if self.path=='/analyze':
            cl = int(self.headers.get('Content-Length',0))
            body = self.rfile.read(cl).decode()
            query = parse_qs(body).get('query',[''])[0]
            if not query:
                self.send_response(400); self.end_headers(); return

            print(f"\n{'='*50}")
            print(f"  🔎 ניתוח: {query}")
            print(f"{'='*50}")

            try:
                # איתור
                inp_type = detect_input_type(query)
                biz_url = None
                biz_name = query

                if inp_type == 'url':
                    biz_url = norm_url(query)
                    try: biz_name = urlparse(biz_url).netloc.replace('www.','').split('.')[0].capitalize()
                    except: pass
                    sr = google_search(f"site:{urlparse(biz_url).netloc}", 3)
                    if sr: biz_name = sr[0]['title'].split(' - ')[0].split(' | ')[0].strip() or biz_name
                else:
                    sr = google_search(query, 10)
                    biz_url = find_website(sr)

                print(f"  ✅ שם: {biz_name}")
                print(f"  {'✅' if biz_url else '❌'} אתר: {biz_url or 'לא נמצא'}")

                # ניתוח אתר
                site = analyze_site(biz_url) if biz_url else {'ok':False}
                print(f"  {'✅ נסרק' if site.get('ok') else '❌ לא נסרק'}")

                # Google Business
                gb = google_business_data(biz_name)
                print(f"  📊 דירוג: {gb.get('rating','—')} | ביקורות: {gb.get('review_count','—')}")

                # דוח
                report = gen_report(biz_name, biz_url or '', site, gb)

                # הוסף כפתור חזרה
                back = '<div style="position:sticky;top:0;z-index:99;text-align:center;padding:10px;background:rgba(248,250,252,.95);backdrop-filter:blur(8px);border-bottom:1px solid #e2e8f0"><a href="/" style="display:inline-flex;align-items:center;gap:8px;padding:10px 24px;border-radius:12px;background:linear-gradient(135deg,#6366f1,#818cf8);color:#fff;text-decoration:none;font-family:Heebo,sans-serif;font-weight:700;font-size:14px;box-shadow:0 4px 20px rgba(99,102,241,.2);-webkit-tap-highlight-color:transparent">→ ניתוח חדש</a></div>'
                report = report.replace('<body>','<body>'+back, 1)

                gbs,_,_ = gb_score(gb)
                ms = lead_score(site, gbs)
                print(f"  🎯 ציון המרה: {ms}/10")
                print(f"  ✅ הדוח נשלח!")

                self.send_response(200)
                self.send_header('Content-Type','text/html; charset=utf-8')
                self.end_headers()
                self.wfile.write(report.encode())

            except Exception as e:
                print(f"  ❌ שגיאה: {e}")
                import traceback; traceback.print_exc()
                self.send_response(500)
                self.send_header('Content-Type','text/plain; charset=utf-8')
                self.end_headers()
                self.wfile.write(f'שגיאה: {e}'.encode())
        else:
            self.send_response(404); self.end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin','*')
        self.send_header('Access-Control-Allow-Methods','POST, GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers','Content-Type')
        self.end_headers()

    def log_message(self, fmt, *a): pass  # שקט


def main():
    print(f"""
╔═══════════════════════════════════════════════════╗
║  🔍  סוכן ניתוח דיגיטלי לעסקים                  ║
╠═══════════════════════════════════════════════════╣
║                                                   ║
║  🌐  נפתח בדפדפן: http://localhost:{PORT}          ║
║  🛑  לעצירה: Ctrl+C                               ║
║                                                   ║
╚═══════════════════════════════════════════════════╝
    """)
    if not os.environ.get("PORT"):
        threading.Timer(1.2, lambda: webbrowser.open(f'http://localhost:{PORT}')).start()
    HTTPServer(('0.0.0.0', PORT), H).serve_forever()

if __name__=='__main__':
    main()
