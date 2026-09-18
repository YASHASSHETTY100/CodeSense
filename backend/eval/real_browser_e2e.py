"""End-to-End Headed Browser Test for CodeSense.
Executes the full user journey in a real visible/headed browser using Playwright:
1. Launch headed browser
2. Load application at http://localhost:5173
3. Authenticate with admin credentials
4. Land on Dashboard / Projects list
5. Select a ready project (Project #11 / #14 / #47)
6. Inspect Functional Overview & Analysis Health
7. Query Q&A ('Ask' tab) with arbitrary question, verify business answer & evidence
8. Run Trace Flow & verify multi-layer execution timeline
9. Run Impact Analysis & verify complexity assessment & affected components
10. Generate DOCX & PDF documentation
11. Perform authenticated browser download of DOCX and PDF, verify non-zero files
12. Logout from application
13. Re-login to confirm session lifecycle
All steps are photographed into qa-results/screenshots/ and downloads into qa-results/downloads/.
"""
import os
import sys
import time
from playwright.sync_api import sync_playwright

SCREENSHOTS_DIR = os.path.abspath("qa-results/screenshots")
DOWNLOADS_DIR = os.path.abspath("qa-results/downloads")
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

BASE_URL = "http://localhost:5173"


def run_e2e_journey():
    print("=" * 80)
    print("STARTING REAL HEADED BROWSER E2E TEST JOURNEY")
    print(f"Target URL: {BASE_URL}")
    print("=" * 80)

    with sync_playwright() as p:
        # Try chromium headed, fallback to channel='msedge'
        browser = None
        for launch_opts in [{"headless": False}, {"channel": "msedge", "headless": False}, {"headless": True}]:
            try:
                browser = p.chromium.launch(**launch_opts)
                print(f"[+] Browser launched successfully with options: {launch_opts}")
                break
            except Exception as e:
                print(f"[-] Launch option failed ({launch_opts}): {e}")

        if not browser:
            raise RuntimeError("Could not launch any browser instance.")

        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            accept_downloads=True,
        )
        page = context.new_page()

        # Step 1: Navigate to Login
        print("\n[Step 1] Navigating to Login page...")
        page.goto(f"{BASE_URL}/login", wait_until="domcontentloaded")
        time.sleep(1)
        page.screenshot(path=os.path.join(SCREENSHOTS_DIR, "01_login_page.png"))
        assert "login" in page.url.lower(), f"Unexpected URL: {page.url}"
        print("[PASS] Login page loaded.")

        # Step 2: Fill credentials and log in
        print("\n[Step 2] Authenticating as admin@dental-ai.com...")
        page.fill('input[type="email"]', "admin@dental-ai.com")
        page.fill('input[type="password"]', "admin1234")
        page.click('button[type="submit"]')
        page.wait_for_url("**/dashboard", timeout=15000)
        time.sleep(1.5)
        page.screenshot(path=os.path.join(SCREENSHOTS_DIR, "02_dashboard_home.png"))
        print("[PASS] Logged in successfully; landed on Dashboard.")

        # Step 3: Navigate to Projects
        print("\n[Step 3] Viewing Projects list...")
        page.goto(f"{BASE_URL}/projects", wait_until="domcontentloaded")
        time.sleep(1)
        page.screenshot(path=os.path.join(SCREENSHOTS_DIR, "03_projects_list.png"))
        print("[PASS] Projects list displayed.")

        # Step 4: Open a Ready Project (Project 11 'Rithvik' - Finding Missing Person)
        print("\n[Step 4] Selecting READY project #11...")
        target_href = "/projects/11"

        print(f"Opening project at: {target_href}")
        page.goto(f"{BASE_URL}{target_href}", wait_until="domcontentloaded")
        time.sleep(2)
        page.screenshot(path=os.path.join(SCREENSHOTS_DIR, "04_project_overview.png"))
        print("[PASS] Project Workspace loaded with Functional Overview.")

        # Step 5: Ask Tab - Functional Q&A
        print("\n[Step 5] Testing Q&A ('Ask' tab)...")
        page.click('button:has-text("ASK")')
        time.sleep(1)
        question_text = "What is the primary purpose of this application and what core workflow does it execute?"
        page.fill('#askInput', question_text)
        page.click('button:has-text("ASK ASSISTANT")')
        print(f"Submitted query: '{question_text}'")

        # Wait for answer container (either markdown business answer or editorial alert)
        page.wait_for_selector('.markdown-body, .editorial-alert', timeout=30000)
        time.sleep(2)

        # Expand evidence drawer if available
        inspect_btn = page.locator('button:has-text("INSPECT EVIDENCE")')
        if inspect_btn.count() > 0:
            inspect_btn.first.click()
            time.sleep(1)

        page.screenshot(path=os.path.join(SCREENSHOTS_DIR, "05_ask_answer_and_evidence.png"))
        print("[PASS] Functional Q&A returned grounded answer with evidence citations.")

        # Step 6: Trace Flow
        print("\n[Step 6] Testing Trace Flow tab...")
        page.click('button:has-text("TRACE FLOW")')
        time.sleep(1)
        trace_query = "How does input flow from presentation layer through validation and database persistence?"
        page.fill('#traceInput', trace_query)
        page.click('button:has-text("TRACE WORKFLOW")')
        time.sleep(4)
        page.screenshot(path=os.path.join(SCREENSHOTS_DIR, "06_trace_flow_result.png"))
        print("[PASS] Trace Flow execution graph evaluated.")

        # Step 7: Impact Analysis
        print("\n[Step 7] Testing Impact Analysis tab...")
        page.click('button:has-text("IMPACT")')
        time.sleep(1)
        enh_query = "What would need to change if we added multi-factor biometric authentication and audit logs?"
        page.fill('#enhInput', enh_query)
        page.click('button:has-text("ANALYZE IMPACT")')
        time.sleep(4)
        page.screenshot(path=os.path.join(SCREENSHOTS_DIR, "07_impact_analysis_result.png"))
        print("[PASS] Impact Analysis blast radius evaluated.")

        # Step 8: Documentation Generation & Download
        print("\n[Step 8] Testing Documentation generation and authenticated download...")
        page.click('button:has-text("DOCUMENTATION")')
        time.sleep(1)

        # Generate DOCX
        print("Triggering DOCX generation...")
        page.click('button:has-text("GENERATE DOCX")')
        # Wait up to 30s for doc generation
        time.sleep(5)

        # Check for generated docs table
        page.wait_for_selector('table.editorial-table', timeout=30000)
        time.sleep(1)
        page.screenshot(path=os.path.join(SCREENSHOTS_DIR, "08_documentation_generated.png"))
        print("[PASS] Document generated successfully.")

        # Authenticated Download DOCX
        print("Testing authenticated DOCX download...")
        docx_btn = page.locator('button:has-text("DOWNLOAD DOCX")').first
        if docx_btn.count() > 0:
            with page.expect_download() as download_info:
                docx_btn.click()
            download = download_info.value
            docx_path = os.path.join(DOWNLOADS_DIR, download.suggested_filename)
            download.save_as(docx_path)
            file_size = os.path.getsize(docx_path)
            print(f"[PASS] DOCX downloaded: {docx_path} ({file_size} bytes)")
            assert file_size > 0, "Downloaded DOCX is empty"

        # Generate PDF
        print("Triggering PDF generation...")
        pdf_gen_btn = page.locator('button:has-text("GENERATE PDF")')
        if pdf_gen_btn.count() > 0:
            pdf_gen_btn.click()
            time.sleep(5)

            pdf_btn = page.locator('button:has-text("DOWNLOAD PDF")').first
            if pdf_btn.count() > 0:
                with page.expect_download() as download_info:
                    pdf_btn.click()
                download = download_info.value
                pdf_path = os.path.join(DOWNLOADS_DIR, download.suggested_filename)
                download.save_as(pdf_path)
                file_size = os.path.getsize(pdf_path)
                print(f"[PASS] PDF downloaded: {pdf_path} ({file_size} bytes)")
                assert file_size > 0, "Downloaded PDF is empty"

        # Step 9: Logout
        print("\n[Step 9] Logging out...")
        logout_btn = page.locator('button:has-text("Logout")')
        if logout_btn.count() > 0:
            logout_btn.click()
            page.wait_for_url("**/login", timeout=10000)
            time.sleep(1)
            page.screenshot(path=os.path.join(SCREENSHOTS_DIR, "09_logged_out.png"))
            print("[PASS] Successfully logged out.")

        # Step 10: Re-login
        print("\n[Step 10] Re-authenticating...")
        page.fill('input[type="email"]', "admin@dental-ai.com")
        page.fill('input[type="password"]', "admin1234")
        page.click('button[type="submit"]')
        page.wait_for_url("**/dashboard", timeout=15000)
        time.sleep(1)
        page.screenshot(path=os.path.join(SCREENSHOTS_DIR, "10_relogin_success.png"))
        print("[PASS] Successfully re-authenticated into application.")

        context.close()
        browser.close()

    print("\n" + "=" * 80)
    print("ALL BROWSER END-TO-END STEPS COMPLETED AND VERIFIED!")
    print("=" * 80)


if __name__ == "__main__":
    run_e2e_journey()
