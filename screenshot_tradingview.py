import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from dotenv import load_dotenv
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright


WATZAP_BASE_URL = "https://api.watzap.id/v1"
TRADINGVIEW_BASE_URL = "https://id.tradingview.com/chart/V8SRU55P/?symbol=XAUUSD"


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"Variabel {name} belum diisi. Periksa file .env.")
    return value


def tradingview_url(symbol: str, interval: str) -> str:
    parts = urlsplit(TRADINGVIEW_BASE_URL)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update({"symbol": symbol, "interval": interval})
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
    )


def chrome_profile_path() -> Path:
    local_app_data = os.getenv("LOCALAPPDATA")
    if not local_app_data:
        raise RuntimeError("Variabel lingkungan LOCALAPPDATA tidak tersedia.")
    return Path(local_app_data) / "ChartMonitor" / "ChromeRemoteProfile"


def chrome_executable() -> Path:
    configured_path = os.getenv("CHROME_PATH", "").strip()
    candidates = [Path(configured_path)] if configured_path else []
    for environment_name, relative_path in (
        ("PROGRAMFILES", Path("Google/Chrome/Application/chrome.exe")),
        ("PROGRAMFILES(X86)", Path("Google/Chrome/Application/chrome.exe")),
        ("LOCALAPPDATA", Path("Google/Chrome/Application/chrome.exe")),
    ):
        root = os.getenv(environment_name)
        if root:
            candidates.append(Path(root) / relative_path)

    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise RuntimeError(
        "Google Chrome tidak ditemukan. Atur CHROME_PATH di .env ke lokasi chrome.exe."
    )


def debugging_port() -> int:
    try:
        port = int(os.getenv("CHROME_DEBUG_PORT", "9222"))
    except ValueError as exc:
        raise ValueError("CHROME_DEBUG_PORT harus berupa angka port.") from exc
    if not 1 <= port <= 65535:
        raise ValueError("CHROME_DEBUG_PORT harus berada di antara 1 dan 65535.")
    return port


def start_chrome_for_debugging(chart_url: str) -> str:
    port = debugging_port()
    endpoint = f"http://127.0.0.1:{port}/json/version"
    try:
        with urlopen(endpoint, timeout=2) as response:
            details = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError):
        chrome = chrome_executable()
        profile_path = chrome_profile_path()
        profile_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.Popen(
                [
                    str(chrome),
                    f"--remote-debugging-port={port}",
                    "--remote-debugging-address=127.0.0.1",
                    f"--user-data-dir={profile_path}",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--window-size=1600,810",
                    chart_url,
                ],
                close_fds=True,
                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            )
        except OSError as exc:
            raise RuntimeError(f"Gagal menjalankan Google Chrome: {exc}") from exc

        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                with urlopen(endpoint, timeout=2) as response:
                    details = json.loads(response.read().decode("utf-8"))
                break
            except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError):
                time.sleep(0.5)
        else:
            raise RuntimeError(
                "Chrome tidak membuka port remote debugging lokal. "
                "Tutup jendela ChromeRemoteProfile lalu coba lagi."
            )

    if not isinstance(details, dict) or not details.get("webSocketDebuggerUrl"):
        raise RuntimeError(
            f"Port {port} sudah dipakai aplikasi lain, bukan Chrome debugging."
        )
    return f"http://127.0.0.1:{port}"


def open_tradingview_chrome(chart_url: str):
    playwright = sync_playwright().start()
    try:
        browser_endpoint = start_chrome_for_debugging(chart_url)
        browser = playwright.chromium.connect_over_cdp(
            browser_endpoint,
            timeout=20_000,
        )
    except PlaywrightError as exc:
        playwright.stop()
        raise RuntimeError(f"Gagal menyambungkan skrip ke Chrome: {exc}") from exc
    except (OSError, RuntimeError, ValueError):
        playwright.stop()
        raise

    if not browser.contexts:
        playwright.stop()
        raise RuntimeError("Chrome tidak menyediakan browser context untuk screenshot.")
    context = browser.contexts[0]
    page = context.pages[0] if context.pages else context.new_page()
    try:
        page.set_viewport_size({"width": 1600, "height": 810})
        response = page.goto(
            chart_url,
            wait_until="domcontentloaded",
            timeout=60_000,
        )
        if response is not None and response.status >= 400:
            raise RuntimeError(f"TradingView mengembalikan HTTP {response.status}.")
    except PlaywrightError as exc:
        playwright.stop()
        raise RuntimeError(f"Gagal membuka Google Chrome: {exc}") from exc
    except RuntimeError:
        playwright.stop()
        raise
    return playwright, browser, context, page


def setup_chrome_profile(chart_url: str) -> None:
    start_chrome_for_debugging(chart_url)
    input(
        "Login ke TradingView di jendela Chrome yang terbuka dan pastikan "
        "chart beserta indikatornya tampil. Setelah selesai, tekan Enter "
        "di terminal: "
    )


def capture_chart(
    chart_url: str,
    output_path: Path,
    wait_seconds: int,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    playwright, _, _, page = open_tradingview_chrome(chart_url)
    try:
        page.locator("canvas").first.wait_for(
            state="visible",
            timeout=60_000,
        )
        page.wait_for_timeout(wait_seconds * 1000)

        watchlist_content = page.locator('[data-name="symbol-list-wrap"]')
        if watchlist_content.is_visible():
            page.locator('button[data-name="base"]').click()
            page.wait_for_function(
                """() => {
                    const watchlist = document.querySelector(
                        '[data-name="symbol-list-wrap"]'
                    );
                    const toolbar = document.querySelector(
                        '[data-name="widgetbar-wrap"]'
                    );
                    return !watchlist ||
                        !toolbar ||
                        toolbar.getBoundingClientRect().width <= 50;
                }""",
                timeout=5_000,
            )

        page.add_style_tag(
            content='[data-name="widgetbar-wrap"] { display: none !important; }'
        )
        screenshot = page.screenshot(
            full_page=False,
            clip={"x": 0, "y": 42, "width": 1600, "height": 768},
        )
        output_path.write_bytes(screenshot)
    except PlaywrightError as exc:
        raise RuntimeError(f"Gagal mengambil screenshot chart: {exc}") from exc
    finally:
        playwright.stop()


def cloudinary_upload(image_path: Path) -> str:
    cloud_name = required_env("CLOUDINARY_CLOUD_NAME")
    api_key = required_env("CLOUDINARY_API_KEY")
    api_secret = required_env("CLOUDINARY_API_SECRET")
    timestamp = str(int(time.time()))
    signature_source = f"timestamp={timestamp}{api_secret}"
    signature = hashlib.sha1(signature_source.encode("utf-8")).hexdigest()

    boundary = f"----ChartMonitor{os.urandom(12).hex()}"
    fields = {
        "api_key": api_key,
        "timestamp": timestamp,
        "signature": signature,
    }
    body = bytearray()

    for name, value in fields.items():
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        )

    body.extend(f"--{boundary}\r\n".encode())
    body.extend(
        (
            f'Content-Disposition: form-data; name="file"; '
            f'filename="{image_path.name}"\r\n'
            "Content-Type: image/png\r\n\r\n"
        ).encode()
    )
    body.extend(image_path.read_bytes())
    body.extend(f"\r\n--{boundary}--\r\n".encode())

    request = Request(
        f"https://api.cloudinary.com/v1_1/{cloud_name}/image/upload",
        data=bytes(body),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    result = post_json(request, "Cloudinary")
    secure_url = result.get("secure_url")
    if not isinstance(secure_url, str) or not secure_url.startswith("https://"):
        raise RuntimeError(f"Cloudinary tidak mengembalikan secure_url: {result}")
    return secure_url


def post_json(request: Request, service_name: str) -> dict:
    try:
        with urlopen(request, timeout=60) as response:
            response_body = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"{service_name} mengembalikan HTTP {exc.code}: {detail}"
        ) from exc
    except URLError as exc:
        raise RuntimeError(f"Gagal terhubung ke {service_name}: {exc.reason}") from exc

    try:
        result = json.loads(response_body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"{service_name} mengembalikan respons yang bukan JSON: {response_body}"
        ) from exc

    if not isinstance(result, dict):
        raise RuntimeError(f"Respons {service_name} tidak sesuai format: {result}")
    return result


def send_to_watzap(image_url: str, caption: str) -> dict:
    payload = {
        "api_key": required_env("WATZAP_API_KEY"),
        "number_key": required_env("WATZAP_NUMBER_KEY"),
        "phone_no": required_env("WATZAP_PHONE_NO"),
        "url": image_url,
        "message": caption,
        "separate_caption": "",
    }
    request = Request(
        f"{WATZAP_BASE_URL}/send_image_url",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    result = post_json(request, "WatZap")

    acknowledgement = result.get("ack")
    if str(acknowledgement).lower() not in {"successfully", "success"}:
        raise RuntimeError(f"WatZap gagal mengirim gambar: {result}")

    return result


def main() -> int:
    env_path = Path(__file__).resolve().with_name(".env")
    load_dotenv(dotenv_path=env_path)
    parser = argparse.ArgumentParser(
        description="Screenshot chart TradingView dan kirim melalui WatZap."
    )
    parser.add_argument(
        "--symbol",
        default=os.getenv("TRADINGVIEW_SYMBOL", "BINANCE:BTCUSDT"),
        help="Simbol TradingView, misalnya BINANCE:BTCUSDT.",
    )
    parser.add_argument(
        "--interval",
        default=os.getenv("TRADINGVIEW_INTERVAL", "15"),
        help="Interval TradingView, misalnya 15, 1H, 1D.",
    )
    parser.add_argument(
        "--chart-url",
        default=os.getenv("TRADINGVIEW_CHART_URL", "").strip() or None,
        help="URL chart TradingView tersimpan (opsional, memakai layout dan drawing chart).",
    )
    parser.add_argument(
        "--setup-chrome",
        action="store_true",
        help="Buka Chrome untuk login TradingView dan menyimpan sesi browser lokal.",
    )
    parser.add_argument(
        "--output",
        default=os.getenv("SCREENSHOT_PATH", "screenshots/chart.png"),
        help="Lokasi file screenshot.",
    )
    parser.add_argument(
        "--wait",
        type=int,
        default=int(os.getenv("CHART_WAIT_SECONDS", "8")),
        help="Waktu tunggu setelah chart tampil, dalam detik.",
    )
    parser.add_argument(
        "--caption",
        default=os.getenv("WHATSAPP_CAPTION", ""),
        help="Caption gambar WhatsApp (opsional).",
    )
    args = parser.parse_args()

    chart_url = args.chart_url or tradingview_url(args.symbol, args.interval)

    if args.setup_chrome:
        try:
            setup_chrome_profile(chart_url)
            print(f"Sesi Chrome disimpan di: {chrome_profile_path()}")
            return 0
        except (OSError, RuntimeError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

    if args.wait < 0:
        parser.error("--wait tidak boleh negatif.")

    try:
        for name in (
            "WATZAP_API_KEY",
            "WATZAP_NUMBER_KEY",
            "WATZAP_PHONE_NO",
            "CLOUDINARY_CLOUD_NAME",
            "CLOUDINARY_API_KEY",
            "CLOUDINARY_API_SECRET",
        ):
            required_env(name)

        output_path = Path(args.output).expanduser()
        if not output_path.is_absolute():
            output_path = Path(__file__).resolve().parent / output_path
        output_path = output_path.resolve()
        capture_chart(chart_url, output_path, args.wait)
        print(f"Screenshot tersimpan: {output_path}")

        image_url = cloudinary_upload(output_path)
        print("Screenshot berhasil diunggah ke Cloudinary.")

        result = send_to_watzap(image_url, args.caption)
        print(f"Pesan berhasil dikirim melalui WatZap: {json.dumps(result)}")
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
