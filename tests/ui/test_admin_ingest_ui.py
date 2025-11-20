from __future__ import annotations

from pathlib import Path

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
    expect(page.locator("body")).to_be_visible()

    input_locator = page.locator('input[name="youtube_url"]')
    if input_locator.count() == 0:
        pytest.skip("Ingestion form is not available in this environment")

    video_url = "https://www.youtube.com/watch?v=opT0UP0q0BE"
    input_locator.fill(video_url)
    # Don't wait for navigation after click - the inline pipeline takes too long with stub broker
    page.click('button:has-text("Queue video")', no_wait_after=True)

    # Wait for the browser to return to /admin/videos and render the flash message.
    page.wait_for_function("window.location.href.includes('/admin/videos')", timeout=60_000)
    expect(page.locator("text=Video queued for processing")).to_be_visible(timeout=60_000)
    # Navigate to the newest video's detail page and verify the status timeline renders.
    page.locator("article.card a[href^='/admin/videos/']").first.click()
    page.wait_for_url("**/admin/videos/*", timeout=10_000)
    expect(page.locator("#video-timeline")).to_be_visible()
    expect(page.locator("#video-timeline >> text=Queued")).to_be_visible()


def test_admin_upload_ingest_flow(page: Page, base_url: str, seeded_user: tuple[str, str]) -> None:
    email, password = seeded_user
    page.goto(f"{base_url}/admin/login")
    page.fill('input[name="email"]', email)
    page.fill('input[name="password"]', password)
    page.click('button[type="submit"]')

    page.wait_for_url(f"{base_url}/admin/videos", timeout=10_000)
    page.goto(f"{base_url}/admin/videos?ingest_mode=upload")

    upload_input = page.locator('input[name="upload_file"]')
    if upload_input.count() == 0:
        pytest.skip("Upload form is not available in this environment")

    sample = Path(__file__).resolve().parent / "assets" / "sample.mp4"
    upload_input.set_input_files(str(sample))
    page.click('button:has-text("Upload & Queue")', no_wait_after=True)

    page.wait_for_function("window.location.href.includes('/admin/videos')", timeout=60_000)
    expect(page.locator("text=Upload queued for processing")).to_be_visible(timeout=60_000)
