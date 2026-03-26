"""
LinkedIn messaging tool — send messages to profiles.

Click Message button on profile → either:
1. Inline compose overlay opens (Premium message, no InMail credits)
2. New tab opens with Recruiter InMail (uses credits)
"""

import asyncio
import logging
import re
from pathlib import Path
from typing import Any

from fastmcp import Context, FastMCP
from fastmcp.dependencies import Depends

from linkedin_mcp_server.constants import TOOL_TIMEOUT_SECONDS
from linkedin_mcp_server.dependencies import get_extractor
from linkedin_mcp_server.error_handler import raise_tool_error
from linkedin_mcp_server.scraping import LinkedInExtractor

logger = logging.getLogger(__name__)

# Inline overlay selectors
SEL_OVERLAY = 'div.msg-overlay-conversation-bubble'
SEL_OVERLAY_COMPOSE = 'div.msg-form__contenteditable[contenteditable="true"]'
SEL_OVERLAY_SEND = 'button.msg-form__send-btn[type="submit"]'
SEL_OVERLAY_SUBJECT = 'div.msg-form__subject input'

# Recruiter InMail selectors
SEL_RECRUITER_SUBJECT = 'input[data-test-compose-subject-input]'
SEL_RECRUITER_BODY = 'div.ql-editor[contenteditable="true"]'
SEL_RECRUITER_SEND = 'button[data-test-messaging-submit-btn]'

SCREENSHOT_DIR = Path.home() / ".linkedin-mcp" / "debug-screenshots"
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)


async def _click_message_button(page):
    """Click the Message button on a LinkedIn profile.

    Tries the direct Message button first, then More → Message.
    Uses mouse.click(x, y) to simulate a real user click so LinkedIn's
    SPA can intercept and open the overlay instead of navigating.
    Returns True if clicked, False if not found.
    """
    # Try direct Message button on profile — can be <button> (premium)
    # or <a> (non-premium). Both are valid profile action buttons.
    for tag in ["button", "a"]:
        try:
            elements = page.locator(tag)
            count = await elements.count()
            for i in range(count):
                el = elements.nth(i)
                try:
                    if not await el.is_visible(timeout=500):
                        continue
                    text = (await el.text_content() or "").strip()
                    if text != "Message":
                        continue
                    # Verify it's a profile action button, not a sidebar link.
                    # Profile action buttons are near the top of the page.
                    box = await el.bounding_box()
                    if not box or box["y"] > 600:
                        continue  # Too far down — likely sidebar
                    await el.click(no_wait_after=True)
                    logger.info("Clicked direct Message <%s> on profile", tag)
                    return True
                except Exception:
                    continue
        except Exception:
            pass

    # Try More → Message
    more_clicked = await page.evaluate(
        r"""() => {
            for (const b of document.querySelectorAll('button')) {
                if (b.textContent.trim() === 'More' &&
                    b.hasAttribute('aria-expanded')) {
                    b.click(); return true;
                }
            }
            return false;
        }"""
    )
    if not more_clicked:
        logger.warning("No More button found")
        return False

    logger.info("Clicked More button")
    await asyncio.sleep(2)

    # Click Message in dropdown via mouse.click for same reason
    msg_pos = await page.evaluate(
        r"""() => {
            const items = document.querySelectorAll('[role="menuitem"]');
            for (const item of items) {
                if (item.textContent.trim().toLowerCase().startsWith('message')) {
                    const rect = item.getBoundingClientRect();
                    return {x: rect.x + rect.width / 2, y: rect.y + rect.height / 2};
                }
            }
            return null;
        }"""
    )
    if msg_pos:
        await page.mouse.click(msg_pos["x"], msg_pos["y"])
        logger.info(
            "Clicked Message in dropdown at (%.0f, %.0f)",
            msg_pos["x"], msg_pos["y"],
        )
        return True

    logger.warning("No Message found in More dropdown")
    return False


async def _send_via_overlay(page, message, subject, dry_run, screenshot_fn):
    """Send a message using the inline compose overlay on the profile page.

    This is the Premium message path (no InMail credits used).
    Appends sign-off since there's no auto-signature.
    """
    compose = page.locator(SEL_OVERLAY_COMPOSE).first
    await compose.wait_for(state="visible", timeout=5_000)

    # Scroll the overlay into view
    await compose.evaluate("el => el.scrollIntoView({block: 'center'})")
    await asyncio.sleep(0.5)

    # Check if there's a subject field (some overlays have it)
    try:
        subject_input = page.locator(SEL_OVERLAY_SUBJECT).first
        if await subject_input.is_visible(timeout=2_000):
            await subject_input.scroll_into_view_if_needed()
            await subject_input.fill(subject)
            logger.info("Filled overlay subject")
    except Exception:
        pass

    # Type message with sign-off
    full_message = message + "\n\nBest,\nOliver"
    await compose.scroll_into_view_if_needed()
    await asyncio.sleep(0.3)
    await compose.click()
    await asyncio.sleep(0.3)
    lines = full_message.split("\n")
    for i, line in enumerate(lines):
        if i > 0:
            await page.keyboard.press("Shift+Enter")
        if line:
            await page.keyboard.type(line, delay=5)

    await asyncio.sleep(1)
    await screenshot_fn("overlay_message_typed")

    if dry_run:
        return {"status": "dry_run", "method": "premium_message"}

    # Click send
    send_btn = page.locator(SEL_OVERLAY_SEND).first
    for _ in range(10):
        if await send_btn.get_attribute("disabled") is None:
            break
        await asyncio.sleep(0.5)
    await send_btn.click()
    await asyncio.sleep(2)
    await screenshot_fn("overlay_after_send")

    return {"status": "success", "method": "premium_message"}


async def _send_via_recruiter(new_tab, message, subject, dry_run, screenshot_fn):
    """Send an InMail using the Recruiter tab.

    No sign-off needed — Recruiter auto-appends signature.
    """
    # Wait for compose form to load
    subject_input = None
    for attempt in range(8):
        try:
            el = new_tab.locator(SEL_RECRUITER_SUBJECT).first
            if await el.is_visible(timeout=3_000):
                subject_input = el
                break
        except Exception:
            pass
        await asyncio.sleep(3)
        await screenshot_fn(f"recruiter_wait_{attempt}")

    if subject_input is None:
        body = await new_tab.evaluate(
            r"() => document.body.innerText.substring(0, 3000)"
        )
        await screenshot_fn("recruiter_compose_not_found")
        raise RuntimeError(
            f"Recruiter compose form not found. URL: {new_tab.url}. "
            f"Page text: {body[:500]}"
        )

    # Fill subject
    await subject_input.click()
    await subject_input.fill(subject)
    await asyncio.sleep(0.5)

    # Fill message body (Quill editor)
    body_editor = new_tab.locator(SEL_RECRUITER_BODY).first
    await body_editor.wait_for(state="visible", timeout=5_000)
    await body_editor.click()
    await asyncio.sleep(0.3)

    lines = message.split("\n")
    for i, line in enumerate(lines):
        if i > 0:
            await new_tab.keyboard.press("Shift+Enter")
        if line:
            await new_tab.keyboard.type(line, delay=5)

    await asyncio.sleep(1)
    await screenshot_fn("recruiter_message_typed")

    if dry_run:
        return {"status": "dry_run", "method": "recruiter_inmail"}

    # Click send
    send_btn = new_tab.locator(SEL_RECRUITER_SEND).first
    try:
        await send_btn.wait_for(state="visible", timeout=5_000)
        for _ in range(10):
            if await send_btn.get_attribute("disabled") is None:
                break
            await asyncio.sleep(0.5)
        await send_btn.click()
    except Exception:
        await new_tab.evaluate(
            r"""() => {
                const btn = document.querySelector('[data-test-messaging-submit-btn]');
                if (btn) { btn.removeAttribute('disabled'); btn.click(); return true; }
                return false;
            }"""
        )

    await asyncio.sleep(3)
    await screenshot_fn("recruiter_after_send")

    # Check for success or error
    post_send = await new_tab.evaluate(
        r"""() => {
            const text = document.body.innerText.substring(0, 3000).toLowerCase();
            if (text.includes('message sent successfully') ||
                text.includes('message has been sent')) {
                return {status: 'success'};
            }
            const subject = document.querySelector('[data-test-compose-subject-input]');
            if (subject && subject.value) {
                const lines = document.body.innerText.split('\n');
                const errorLines = lines.filter(l => {
                    const lower = l.toLowerCase().trim();
                    return lower && (
                        lower.includes('error') || lower.includes('cannot') ||
                        lower.includes('unable') || lower.includes('limit') ||
                        lower.includes('already') || lower.includes('pending') ||
                        lower.includes('not be contacted')
                    );
                }).map(l => l.trim()).slice(0, 3);
                return {status: 'error', detail: errorLines.join('; ') || 'Compose still open after send'};
            }
            return {status: 'unknown'};
        }"""
    )

    if post_send.get("status") == "error":
        raise RuntimeError(f"InMail send failed: {post_send['detail']}")

    return {"status": "success", "method": "recruiter_inmail"}


def register_messaging_tools(mcp: FastMCP) -> None:
    """Register messaging tools with the MCP server."""

    @mcp.tool(
        timeout=TOOL_TIMEOUT_SECONDS * 3,
        title="Send Message",
        annotations={"readOnlyHint": False, "openWorldHint": True},
        tags={"messaging"},
    )
    async def send_message(
        linkedin_username: str,
        message: str,
        ctx: Context,
        dry_run: bool = False,
        subject: str = "Opportunity at the Center for AI Safety",
        extractor: LinkedInExtractor = Depends(get_extractor),
    ) -> dict[str, Any]:
        """Send a LinkedIn message to a person.

        Navigates to their profile, clicks Message, types the message,
        and clicks Send.

        For 1st connections / people with mutuals: uses regular LinkedIn messaging.
        For no-mutual connections: uses LinkedIn Recruiter InMail.

        Args:
            linkedin_username: LinkedIn username (e.g., "oliverzhang42")
            message: The message text to send. Plain text only.
            dry_run: If True, navigate and type but DON'T click Send.
            subject: Subject line for Recruiter InMail (not used for
                    regular messages). Defaults to
                    "Opportunity at the Center for AI Safety".
        """
        try:
            page = extractor._page
            screenshots = []

            async def screenshot(name: str) -> str:
                path = SCREENSHOT_DIR / f"{linkedin_username}_{name}.png"
                await page.screenshot(path=str(path))
                screenshots.append(str(path))
                return str(path)

            # Step 1: Navigate to profile
            await ctx.report_progress(0, 4, "Navigating to profile...")
            profile_url = f"https://www.linkedin.com/in/{linkedin_username}/"
            await page.goto(profile_url, wait_until="domcontentloaded", timeout=30_000)
            await asyncio.sleep(3)
            await screenshot("1_profile")

            # Dismiss any popups
            try:
                await page.keyboard.press("Escape")
                await asyncio.sleep(0.5)
            except Exception:
                pass

            # Step 2: Click Message button
            await ctx.report_progress(1, 4, "Clicking Message...")
            clicked = await _click_message_button(page)
            if not clicked:
                raise RuntimeError(
                    f"Could not find Message button on profile. URL: {page.url}"
                )

            # Step 3: Detect which path — overlay or new tab
            await ctx.report_progress(2, 4, "Detecting compose method...")

            # Wait and check for overlay on profile page
            await asyncio.sleep(5)
            await screenshot("after_msg_click")

            overlay_compose = None
            try:
                el = page.locator(SEL_OVERLAY_COMPOSE).first
                if await el.is_visible(timeout=5_000):
                    overlay_compose = el
                    logger.info("Inline compose overlay detected!")
            except Exception:
                pass

            if overlay_compose:
                # ====== PREMIUM MESSAGE (overlay) ======
                await ctx.report_progress(3, 4, "Typing message...")
                result = await _send_via_overlay(
                    page, message, subject, dry_run, screenshot
                )
                return {
                    **result,
                    "recipient": linkedin_username,
                    "message_length": len(message),
                    "message_preview": message[:100]
                    + ("..." if len(message) > 100 else ""),
                    "screenshots": screenshots,
                }

            # Check for new tab (Recruiter InMail)
            all_pages = page.context.pages
            new_tab = None
            for p in all_pages:
                if p != page and "/talent/" in p.url:
                    new_tab = p
                    break

            # If no Recruiter tab found yet, check all non-original pages
            if not new_tab:
                for p in all_pages:
                    if p != page:
                        new_tab = p
                        break

            if new_tab:
                # ====== RECRUITER INMAIL (new tab) ======
                logger.info("Recruiter tab detected: %s", new_tab.url)

                async def recruiter_ss(name: str) -> str:
                    path = SCREENSHOT_DIR / f"{linkedin_username}_{name}.png"
                    await new_tab.screenshot(path=str(path))
                    screenshots.append(str(path))
                    return str(path)

                await recruiter_ss("recruiter_landing")
                await ctx.report_progress(3, 4, "Typing InMail...")

                result = await _send_via_recruiter(
                    new_tab, message, subject, dry_run, recruiter_ss
                )

                try:
                    await new_tab.close()
                except Exception:
                    pass

                return {
                    **result,
                    "recipient": linkedin_username,
                    "message_length": len(message),
                    "message_preview": message[:100]
                    + ("..." if len(message) > 100 else ""),
                    "screenshots": screenshots,
                }

            # Neither overlay nor new tab
            body = await page.evaluate(
                r"() => document.body.innerText.substring(0, 2000)"
            )
            await screenshot("no_compose_found")
            raise RuntimeError(
                f"Clicked Message but no compose overlay or Recruiter tab appeared. "
                f"URL: {page.url}. Page text: {body[:500]}"
            )

        except Exception as e:
            raise_tool_error(e, "send_message")
