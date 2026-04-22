import logging
import os
from datetime import timedelta

from flask import Flask, jsonify, request, send_from_directory
from werkzeug.middleware.proxy_fix import ProxyFix

from freeapi.rate_limit import check_rate_limit
from freeapi.routes import register_routes

logger = logging.getLogger('freeapi')

_STATIC_EXTENSIONS = {
    '.js', '.css', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico',
    '.woff', '.woff2', '.ttf', '.eot', '.otf', '.map', '.webp',
    '.mp4', '.webm', '.pdf', '.json', '.xml', '.txt',
}

_SCRAPER_PATTERNS = (
    'python-requests', 'python-urllib', 'python/', 'urllib',
    'curl/', 'wget/', 'scrapy', 'go-http-client', 'java/',
    'okhttp', 'libwww', 'lwp-', 'masscan', 'zgrab', 'nikto',
    'sqlmap', 'nmap', 'dirbuster', 'gobuster', 'nuclei',
    'httpclient', 'apache-httpclient',
)


def _is_browser_request() -> bool:
    ua = request.headers.get('User-Agent', '').strip()
    if not ua:
        return False
    ua_lower = ua.lower()
    for pattern in _SCRAPER_PATTERNS:
        if pattern in ua_lower:
            return False
    return True


def _is_static_asset(path: str) -> bool:
    _, ext = os.path.splitext(path)
    return ext.lower() in _STATIC_EXTENSIONS


# (limit, window_sec) per endpoint group. Применяется в before_request.
_RATE_LIMIT_RULES = (
    # auth
    (('POST',), ('/api/auth/login', '/api/auth/register'), 10, 60),
    # отзывы — создание/редактирование/удаление, лайки
    (('POST', 'PUT', 'PATCH', 'DELETE'), ('/api/reviews',), 20, 60),
    # support чат — отправка сообщений
    (('POST',), ('/api/support/',), 30, 60),
    # тестовый chat playground
    (('POST',), ('/api/chat/test', '/api/v1/chat/completions'), 30, 60),
)


def _rate_limit_for(path: str, method: str):
    for methods, prefixes, limit, window in _RATE_LIMIT_RULES:
        if method not in methods:
            continue
        for prefix in prefixes:
            if path == prefix or path.startswith(prefix.rstrip('/') + '/'):
                return (limit, window)
    return None


def _get_allowed_origins():
    origins_env = os.environ.get('ALLOWED_ORIGINS', '')
    if origins_env:
        return [o.strip() for o in origins_env.split(',') if o.strip()]
    return []


def create_app():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(message)s')
    logging.getLogger('freeapi').setLevel(logging.INFO)
    app = Flask(__name__, static_folder='../static', static_url_path='')
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    app.secret_key = os.environ.get('SESSION_SECRET', 'change-me-in-production')
    app.config['JSON_AS_ASCII'] = False
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=int(os.environ.get('SESSION_DAYS', '30')))
    app.config['SESSION_REFRESH_EACH_REQUEST'] = True

    forwarded_proto = os.environ.get('X_FORWARDED_PROTO', '').lower()
    is_https = (
        os.environ.get('HTTPS', '').lower() in ('1', 'true', 'yes')
        or os.environ.get('FLASK_ENV') == 'production'
        or os.environ.get('REPLIT_DEPLOYMENT')
        or forwarded_proto == 'https'
    )
    if is_https:
        app.config['SESSION_COOKIE_SECURE'] = True
        app.config['SESSION_COOKIE_SAMESITE'] = 'None'
    else:
        app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

    app.config['SESSION_COOKIE_HTTPONLY'] = True
    # Максимальный размер запроса: 150MB (base64 изображений в JSON)
    app.config['MAX_CONTENT_LENGTH'] = 150 * 1024 * 1024

    @app.before_request
    def security_checks():
        path = request.path

        if request.method == 'OPTIONS':
            return None

        if path.startswith('/api/'):
            ip = request.remote_addr or request.headers.get('CF-Connecting-IP', '0.0.0.0')
            limits = _rate_limit_for(path, request.method)
            if limits is not None:
                limit, window = limits
                if not check_rate_limit(ip, path, limit=limit, window=window):
                    logger.warning('[RateLimit] Заблокирован %s → %s (limit=%d/%ds)', ip, path, limit, window)
                    return jsonify({'error': True, 'message': 'Слишком много запросов. Попробуйте позже.', 'log_code': 'RATE_LIMIT_429'}), 429
            return None

        if _is_static_asset(path):
            return None

        if not _is_browser_request():
            logger.info('[AntiScrape] Отклонён запрос (User-Agent: %r) → %s', request.headers.get('User-Agent', ''), path)
            return jsonify({'error': True, 'message': 'Forbidden'}), 403

        return None

    @app.after_request
    def add_headers(response):
        origin = request.headers.get('Origin', '')
        allowed_origins = _get_allowed_origins()

        if allowed_origins:
            if origin in allowed_origins:
                response.headers['Access-Control-Allow-Origin'] = origin
            else:
                response.headers['Access-Control-Allow-Origin'] = allowed_origins[0]
        else:
            if origin:
                response.headers['Access-Control-Allow-Origin'] = origin
                response.headers['Vary'] = 'Origin'
            else:
                response.headers['Access-Control-Allow-Origin'] = '*'

        response.headers['Access-Control-Allow-Credentials'] = 'true'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-Requested-With'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS, PATCH'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'

        # КРИТИЧНО для Android WebView (Termux): запрет кэширования HTML и SW.
        # Без этого WebView держит старый index.html до 12ч, и фиксы не применяются.
        ctype = (response.content_type or '').lower()
        if 'text/html' in ctype or request.path == '/' or request.path.endswith('.html'):
            response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'

        if request.path.endswith('/status') and 'text/event-stream' in response.content_type:
            response.headers['X-Accel-Buffering'] = 'no'
            response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            response.headers['Connection'] = 'keep-alive'

        return response

    @app.route('/', defaults={'path': ''})
    @app.route('/<path:path>')
    def frontend(path):
        if path.startswith('api/'):
            return jsonify({'error': True, 'message': 'API endpoint not found'}), 404
        static_root = app.static_folder
        if path and os.path.exists(os.path.join(static_root, path)):
            return send_from_directory(static_root, path)
        if os.path.exists(os.path.join(static_root, 'index.html')):
            return send_from_directory(static_root, 'index.html')
        return jsonify({'ok': True, 'message': 'FreeApi Python запущен'})

    register_routes(app)
    return app
