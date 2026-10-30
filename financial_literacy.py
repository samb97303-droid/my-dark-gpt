import json
import os
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

ROOT = Path(__file__).resolve().parent
ANSWERS_PATH = ROOT / "answers.json"

SITE_URL = os.getenv("SITE_URL", "https://egy.app.spx-learning-square.com/login")
SUBJECT_URL = os.getenv("TARGET_URL", "https://egy.app.spx-learning-square.com/subjects/7")
SITE_USER = os.getenv("SITE_USER", "464604716")
SITE_PASS = os.getenv("SITE_PASS", "eqJV9pY?")
HEADLESS = os.getenv("HEADLESS", "false").lower() == "true"

# Try generic selectors first—fallbacks are included below.
USER_SELECTOR = os.getenv("USER_SELECTOR")
PASS_SELECTOR = os.getenv("PASS_SELECTOR")
SUBMIT_SELECTOR = os.getenv("SUBMIT_SELECTOR")


def normalize_text(value):
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def load_answers():
    with ANSWERS_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def debug_screenshot(page, file_name):
    page.screenshot(path=file_name, full_page=True)
    print(f"[debug] screenshot saved: {file_name}")


def log_question(page):
    selectors = [
        "h1, h2, h3, h4, .question-title, .prompt, .title, [data-testid*='question']",
        "div[role='heading']",
        "p",
    ]
    for sel in selectors:
        loc = page.locator(sel)
        if loc.count() == 0:
            continue
        for item in loc.all():
            text = normalize_text(item.inner_text())
            if not text:
                continue
            if len(text) < 30:
                continue
            print(f"Question: {text}")
            return text
    print("Question: <not detected>")
    return ""


def click_by_text(page, text, timeout_ms=15000):
    text = normalize_text(text)
    if not text:
        return False

    selectors = [
        f"text={text}",
        f"button:has-text(\"{text}\")",
        f"label:has-text(\"{text}\")",
        f"div:has-text(\"{text}\")",
        f"[role='button']:has-text(\"{text}\")",
        f"li:has-text(\"{text}\")",
    ]

    for sel in selectors:
        loc = page.locator(sel)
        if loc.count() == 0:
            continue
        try:
            loc.first.click(timeout=timeout_ms)
            return True
        except Exception:
            pass

    # Fallback: scan visible clickable elements and compare text content.
    candidates = page.locator("button, label, li, div, input, [role='button'], [role='radio']")
    for item in candidates.all():
        try:
            if not item.is_visible():
                continue
        except Exception:
            continue
        txt = normalize_text(item.inner_text())
        if not txt:
            continue
        if text in txt or txt in text:
            try:
                item.click(timeout=timeout_ms)
                return True
            except Exception:
                pass

    return False


def click_next(page):
    selectors = [
        "button:has-text('التالي')",
        "button:has-text('Next')",
        "button:has-text('Submit')",
        "button:has-text('إرسال')",
        "button:has-text('حفظ')",
        "[data-testid*='next']",
        "[data-testid*='submit']",
        "button[type='submit']",
        "input[type='submit']",
        ".next-btn",
    ]
    for sel in selectors:
        loc = page.locator(sel)
        if loc.count() == 0:
            continue
        try:
            loc.first.click(timeout=10000)
            print(f"[info] clicked next/submit via selector: {sel}")
            return True
        except Exception:
            pass
    return False


def wait_for_login_state(page):
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1500)


def login(page):
    page.goto(SITE_URL, wait_until="domcontentloaded")
    wait_for_login_state(page)

    user_sel = USER_SELECTOR or os.getenv("USER_SELECTOR") or (
        "input[type=email], input[name*=user i], input[id*=user i], "
        "input[name*=email i], input[id*=email i], "
        "input[type=text], input[type=tel], input[type=number]"
    )
    pass_sel = PASS_SELECTOR or os.getenv("PASS_SELECTOR") or "input[type=password]"

    page.wait_for_selector(pass_sel, timeout=30000)
    page.locator(user_sel).first.fill(SITE_USER)
    page.locator(pass_sel).first.fill(SITE_PASS)

    submit_sel = SUBMIT_SELECTOR or os.getenv("SUBMIT_SELECTOR")
    if submit_sel:
        page.locator(submit_sel).first.click(timeout=15000)
    else:
        submit = page.locator("button[type=submit], input[type=submit], button:has-text('تسجيل')")
        if submit.count() > 0:
            submit.first.click(timeout=15000)
        else:
            page.locator(pass_sel).first.press("Enter")

    wait_for_login_state(page)
    page.wait_for_timeout(2000)

    still_login = page.locator(pass_sel)
    if "login" in page.url.lower() and still_login.count() and still_login.first.is_visible():
        debug_screenshot(page, "after_login_failed.png")
        raise RuntimeError("Login appears to have failed. Check after_login_failed.png and credentials.")

    print("Login OK")
    print("Current URL:", page.url)


def open_subject_lessons(page):
    page.goto(SUBJECT_URL, wait_until="domcontentloaded")
    wait_for_login_state(page)

    lesson_patterns = [
        "الدرس 1",
        "Lesson 1",
        "lesson 1",
        "1",
        "الدرس",
        "Lesson",
    ]
    for pattern in lesson_patterns:
        candidates = page.locator(f"text={pattern}")
        if candidates.count() > 0:
            try:
                candidates.first.click(timeout=15000)
                print(f"Opened lesson by pattern: {pattern}")
                return True
            except Exception:
                pass

    # Try a more generic clickable card approach.
    card_selectors = [
        "a, button, li, div, [role='button']",
    ]
    for sel in card_selectors:
        cards = page.locator(sel)
        if cards.count() == 0:
            continue
        for idx in range(min(cards.count(), 30)):
            text = normalize_text(cards.nth(idx).inner_text())
            if "درس" in text or "lesson" in text.lower():
                try:
                    cards.nth(idx).click(timeout=15000)
                    print(f"Opened lesson via card index {idx}: {text[:80]}")
                    return True
                except Exception:
                    pass

    debug_screenshot(page, "subject_page_debug.png")
    raise RuntimeError("Could not find a lesson card/button. See subject_page_debug.png and adjust selectors.")


def solve_lesson(page, lesson_name, answers):
    print(f"\n=== {lesson_name} ===")
    for index, answer in enumerate(answers, start=1):
        log_question(page)
        if not click_by_text(page, answer):
            debug_screenshot(page, f"missing_answer_{lesson_name}_{index}.png")
            raise RuntimeError(f"Unable to find answer text for {lesson_name}: {answer}")
        print(f"Selected answer {index}/{len(answers)}: {answer}")
        page.wait_for_timeout(500)
        if index < len(answers):
            if not click_next(page):
                page.keyboard.press("Enter")
                page.wait_for_timeout(600)
            page.wait_for_timeout(1500)
    # Finish current lesson if a final next/submit exists.
    click_next(page)


def solve_all_lessons(page):
    answers = load_answers()

    # Open each lesson in the course order.
    for name in ["lesson_1", "lesson_2", "lesson_3"]:
        lesson_answers = answers.get(name, [])
        if not lesson_answers:
            continue

        # Try to open the lesson by label if the page has lesson list.
        lesson_label = name.replace("lesson_", "Lesson ")
        if not open_subject_lessons(page):
            raise RuntimeError(f"Could not go to lesson list for {lesson_label}")

        matched = False
        for pattern in [lesson_label, lesson_label.replace("Lesson ", "الدرس "), str(name).replace("lesson_", "")]:
            loc = page.locator(f"text={pattern}")
            if loc.count() > 0:
                try:
                    loc.first.click(timeout=15000)
                    matched = True
                    break
                except Exception:
                    pass

        if not matched:
            # Try generic lesson card access with index.
            cards = page.locator("a, button, li, div, [role='button']")
            for idx in range(min(cards.count(), 25)):
                txt = normalize_text(cards.nth(idx).inner_text())
                if "درس" in txt or "lesson" in txt.lower():
                    try:
                        cards.nth(idx).click(timeout=15000)
                        matched = True
                        break
                    except Exception:
                        pass

        if not matched:
            debug_screenshot(page, f"lesson_not_found_{name}.png")
            raise RuntimeError(f"Unable to find lesson card for {name}. See lesson_not_found_{name}.png")

        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(2000)
        solve_lesson(page, name, lesson_answers)

    # Optional exam if it exists.
    if answers.get("exam"):
        print("\n=== Exam ===")
        try:
            page.locator("text=Exam").first.click(timeout=5000)
        except Exception:
            pass
        solve_lesson(page, "exam", answers["exam"])


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)
        page = browser.new_context(viewport={"width": 1440, "height": 1200}, locale="ar-EG").new_page()
        try:
            login(page)
            solve_all_lessons(page)
            print("All lessons completed successfully.")
            if not HEADLESS:
                input("Press Enter to close the browser...")
        except PWTimeout:
            debug_screenshot(page, "timeout_debug.png")
            print("Timeout while waiting for page elements. See timeout_debug.png.")
            sys.exit(1)
        except Exception as exc:
            print("Error:", exc)
            debug_screenshot(page, "general_error_debug.png")
            sys.exit(1)
        finally:
            browser.close()


if __name__ == "__main__":
    main()
