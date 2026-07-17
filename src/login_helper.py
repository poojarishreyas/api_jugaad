import sys
import os
import json
from PySide6.QtCore import Qt, QUrl, QTimer, Signal
from PySide6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QLabel
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import (
    QWebEngineProfile, QWebEnginePage, QWebEngineUrlRequestInterceptor,
    QWebEngineScript, qWebEngineChromiumVersion
)

try:
    _CHROMIUM_VERSION = qWebEngineChromiumVersion()
except Exception:
    _CHROMIUM_VERSION = "130.0.6723.58"

_CHROME_MAJOR = _CHROMIUM_VERSION.split('.')[0]

class GoogleRequestInterceptor(QWebEngineUrlRequestInterceptor):
    def interceptRequest(self, info):
        info.setHttpHeader(
            b"Sec-CH-UA",
            f'"Chromium";v="{_CHROME_MAJOR}", "Google Chrome";v="{_CHROME_MAJOR}", "Not_A Brand";v="24"'.encode()
        )
        info.setHttpHeader(b"Sec-CH-UA-Mobile", b"?0")
        info.setHttpHeader(b"Sec-CH-UA-Platform", b'"Windows"')

class LoginWindow(QMainWindow):
    def __init__(self, provider, custom_url=None):
        super().__init__()
        self.provider = provider
        self.custom_url = custom_url
        self.setWindowTitle(f"API Jugaad - Manual Login for {provider.capitalize()}")
        self.resize(1000, 800)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        
        # UI Header
        from PySide6.QtWidgets import QHBoxLayout, QPushButton
        header_layout = QHBoxLayout()
        
        self.label = QLabel("Please log in normally. If using a custom site, click Save when done.")
        self.label.setStyleSheet("padding: 10px; background: #ffe066; font-weight: bold; font-size: 14px;")
        header_layout.addWidget(self.label, stretch=1)
        
        self.save_btn = QPushButton("Save Cookies & Close")
        self.save_btn.setStyleSheet("padding: 10px; background: #4CAF50; color: white; font-weight: bold; font-size: 14px;")
        self.save_btn.clicked.connect(self.save_to_env)
        header_layout.addWidget(self.save_btn)
        
        layout.addLayout(header_layout)

        self.profile = QWebEngineProfile(f"JugaadProfile_{provider}", self)
        
        ua_string = (
            f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            f"AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/{_CHROMIUM_VERSION} Safari/537.36"
        )
        self.profile.setHttpUserAgent(ua_string)

        self.interceptor = GoogleRequestInterceptor(self)
        self.profile.setUrlRequestInterceptor(self.interceptor)

        anti_detect_js = QWebEngineScript()
        anti_detect_js.setName("AntiDetect")
        anti_detect_js.setSourceCode(f"""
            // ── Hide webdriver flag ──────────────────────────────────────
            Object.defineProperty(navigator, 'webdriver', {{ get: () => false }});
            delete navigator.__proto__.webdriver;

            // ── Override navigator.userAgent to match HTTP header ────────
            Object.defineProperty(navigator, 'userAgent', {{
                get: () => '{ua_string}'
            }});
            Object.defineProperty(navigator, 'appVersion', {{
                get: () => '{ua_string.replace("Mozilla/", "")}'
            }});
            Object.defineProperty(navigator, 'platform', {{ get: () => 'Win32' }});
            Object.defineProperty(navigator, 'vendor', {{ get: () => 'Google Inc.' }});

            // ── Complete window.chrome object ────────────────────────────
            if (!window.chrome) {{ window.chrome = {{}}; }}
            if (!window.chrome.runtime) {{
                window.chrome.runtime = {{
                    connect: function() {{}},
                    sendMessage: function() {{}},
                    onMessage: {{ addListener: function() {{}} }},
                    id: undefined
                }};
            }}
            if (!window.chrome.csi) {{
                window.chrome.csi = function() {{ return {{}}; }};
            }}
            if (!window.chrome.loadTimes) {{
                window.chrome.loadTimes = function() {{
                    return {{
                        commitLoadTime: Date.now() / 1000,
                        connectionInfo: 'h2',
                        finishDocumentLoadTime: Date.now() / 1000,
                        finishLoadTime: Date.now() / 1000,
                        firstPaintAfterLoadTime: 0,
                        firstPaintTime: Date.now() / 1000,
                        navigationType: 'Other',
                        npnNegotiatedProtocol: 'h2',
                        requestTime: Date.now() / 1000,
                        startLoadTime: Date.now() / 1000,
                        wasAlternateProtocolAvailable: false,
                        wasFetchedViaSpdy: true,
                        wasNpnNegotiated: true
                    }};
                }};
            }}
            if (!window.chrome.app) {{
                window.chrome.app = {{
                    isInstalled: false,
                    InstallState: {{ DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed' }},
                    RunningState: {{ CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running' }}
                }};
            }}

            // ── Fake plugins ─────────────────────────────────────────────
            Object.defineProperty(navigator, 'plugins', {{
                get: () => {{
                    const p = [
                        {{ name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format', length: 1 }},
                        {{ name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '', length: 1 }},
                        {{ name: 'Native Client', filename: 'internal-nacl-plugin', description: '', length: 2 }}
                    ];
                    p.length = 3;
                    return p;
                }}
            }});
            Object.defineProperty(navigator, 'mimeTypes', {{
                get: () => {{
                    const m = [
                        {{ type: 'application/pdf', suffixes: 'pdf', description: 'Portable Document Format' }},
                        {{ type: 'application/x-google-chrome-pdf', suffixes: 'pdf', description: 'Portable Document Format' }}
                    ];
                    m.length = 2;
                    return m;
                }}
            }});

            // ── Fake languages ───────────────────────────────────────────
            Object.defineProperty(navigator, 'languages', {{ get: () => ['en-US', 'en'] }});

            // ── Hardware / device spoofing ────────────────────────────────
            Object.defineProperty(navigator, 'hardwareConcurrency', {{ get: () => 8 }});
            Object.defineProperty(navigator, 'deviceMemory', {{ get: () => 8 }});
            Object.defineProperty(navigator, 'maxTouchPoints', {{ get: () => 0 }});
            Object.defineProperty(navigator, 'connection', {{
                get: () => ({{ effectiveType: '4g', rtt: 50, downlink: 10, saveData: false }})
            }});

            // ── Fix Permissions API ──────────────────────────────────────
            if (navigator.permissions) {{
                const origQuery = navigator.permissions.query.bind(navigator.permissions);
                navigator.permissions.query = (params) => {{
                    if (params.name === 'notifications') {{
                        return Promise.resolve({{ state: Notification.permission }});
                    }}
                    return origQuery(params);
                }};
            }}

            // ── Protect overridden functions from toString detection ─────
            const _origToString = Function.prototype.toString;
            const _customFns = new Set();
            Function.prototype.toString = function() {{
                if (_customFns.has(this)) {{
                    return 'function ' + (this.name || '') + '() {{ [native code] }}';
                }}
                return _origToString.call(this);
            }};
            _customFns.add(Function.prototype.toString);
            if (navigator.permissions) _customFns.add(navigator.permissions.query);
        """)
        anti_detect_js.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        anti_detect_js.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        anti_detect_js.setRunsOnSubFrames(True)
        self.profile.scripts().insert(anti_detect_js)

        self.webview = QWebEngineView(self)
        self.webview.setPage(QWebEnginePage(self.profile, self.webview))
        layout.addWidget(self.webview)

        self.profile.cookieStore().cookieAdded.connect(self.on_cookie_added)
        self.cookies = {}
        self.all_cookie_objects = []

        if provider == "chatgpt":
            self.target_url = "https://chatgpt.com/"
        elif provider == "gemini":
            self.target_url = "https://gemini.google.com/"
        elif provider == "zai":
            self.target_url = "https://z.ai/"
        else:
            self.target_url = self.custom_url or "https://google.com/"
            
        self.webview.load(QUrl(self.target_url))
        
        self.check_timer = QTimer(self)
        self.check_timer.timeout.connect(self.check_if_logged_in)
        self.check_timer.start(2000)

    def on_cookie_added(self, cookie):
        domain = cookie.domain()
        name = cookie.name().data().decode('utf-8')
        value = cookie.value().data().decode('utf-8')
        self.cookies[name] = value
        
        # Store full cookie objects for JSON dump
        cookie_dict = {
            "name": name,
            "value": value,
            "domain": domain,
            "path": cookie.path(),
            "secure": cookie.isSecure(),
            "httpOnly": cookie.isHttpOnly()
        }
        self.all_cookie_objects.append(cookie_dict)

    def check_if_logged_in(self):
        if self.provider == "chatgpt":
            if "__Secure-next-auth.session-token.0" in self.cookies:
                self.label.setText("✅ ChatGPT Login detected! Saving cookies...")
                self.save_to_env()
                
        elif self.provider == "gemini":
            if "__Secure-1PSID" in self.cookies and "__Secure-1PSIDTS" in self.cookies:
                self.label.setText("✅ Gemini Login detected! Saving cookies...")
                self.save_to_env()
                
        elif self.provider == "zai":
            if "acw_tc" in self.cookies: 
                self.label.setText("✅ Z.ai Login detected! Saving cookies...")
                self.save_to_env()

    def save_to_env(self):
        self.check_timer.stop()
        env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
        
        env_lines = []
        if os.path.exists(env_path):
            with open(env_path, 'r') as f:
                env_lines = f.readlines()
                
        env_dict = {}
        for line in env_lines:
            if '=' in line and not line.startswith('#'):
                k, v = line.strip().split('=', 1)
                env_dict[k] = v
                
        if self.provider == "chatgpt":
            env_dict["PROVIDER"] = "chatgpt"
            env_dict["SESSION_TOKEN_0"] = self.cookies.get("__Secure-next-auth.session-token.0", "")
            env_dict["SESSION_TOKEN_1"] = self.cookies.get("__Secure-next-auth.session-token.1", "")
        elif self.provider == "gemini":
            env_dict["PROVIDER"] = "gemini"
            env_dict["GEMINI_PSID"] = self.cookies.get("__Secure-1PSID", "")
            env_dict["GEMINI_PSIDTS"] = self.cookies.get("__Secure-1PSIDTS", "")
            env_dict["GEMINI_PSIDCC"] = self.cookies.get("__Secure-1PSIDCC", "")
        else:
            # For any custom provider, we dump all cookies as a JSON string
            env_dict["PROVIDER"] = self.provider
            env_dict[f"{self.provider.upper()}_COOKIES"] = json.dumps(self.all_cookie_objects)
        
        with open(env_path, 'w') as f:
            for k, v in env_dict.items():
                f.write(f"{k}={v}\n")
                
        print(f"Successfully saved {self.provider} cookies to .env")
        QApplication.quit()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    provider = sys.argv[1] if len(sys.argv) > 1 else "chatgpt"
    custom_url = sys.argv[2] if len(sys.argv) > 2 else None
    window = LoginWindow(provider, custom_url)
    window.show()
    sys.exit(app.exec())
