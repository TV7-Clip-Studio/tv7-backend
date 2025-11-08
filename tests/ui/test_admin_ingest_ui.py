from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

pytestmark = [pytest.mark.ui, pytest.mark.no_db_override]


def test_admin_login_and_ingest_flow(
    page: Page, base_url: str, seeded_user: tuple[str, str]
) -> None:
    email, password = seeded_user

    page.goto(f"{base_url}/admin/login")
    expect(page.locator("text=Operator Sign In")).to_be_visible()

    page.fill('input[name="email"]', email)
    page.fill('input[name="password"]', password)
    page.click('button[type="submit"]')

    page.wait_for_url(f"{base_url}/admin/videos", timeout=10_000)
    expect(page.locator("text=Ingest a new video")).to_be_visible()

    video_url = "https://www.youtube.com/watch?v=opT0UP0q0BE"
    page.fill('input[name="youtube_url"]', video_url)
    page.click('button:has-text("Queue video")')

    # The dashboard redirects back with a flash message.
    page.wait_for_url(f"{base_url}/admin/videos?flash=*", timeout=10_000)
    expect(page.locator("text=Video queued for processing")).to_be_visible()
    # Navigate to the newest video's detail page and verify the status timeline renders.
    page.locator("article.card a[href^='/admin/videos/']").first.click()
    page.wait_for_url("**/admin/videos/*", timeout=10_000)
    expect(page.locator("#video-timeline")).to_be_visible()
    expect(page.locator("#video-timeline >> text=Queued")).to_be_visible()
