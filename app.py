from flask import Flask, jsonify, request, render_template, session, redirect, url_for
from urllib.parse import urlparse, urljoin, quote, urlencode
from functools import wraps
import json
import os
import urllib.request
import tempfile
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

# app.py はプロジェクト直下に置く。
# 実体（templates / static / data）は bousai_app/ 配下にあるので、そこを参照する。
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.join(BASE_DIR, 'bousai_app')
load_dotenv(os.path.join(BASE_DIR, '.env'))

app = Flask(
    __name__,
    template_folder=os.path.join(APP_DIR, 'templates'),
    static_folder=os.path.join(APP_DIR, 'static'),
)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'dev-only-change-me')

# 管理者認証情報
ADMIN_CREDENTIALS = {
    os.environ.get('ADMIN_USERNAME', 'admin'): os.environ.get('ADMIN_PASSWORD', '123')
}

# ────────────────────────────────
# 気象警報・注意報設定
PREFECTURE_CODE = "020000"  # 青森県
AREA_NAME = "青森市"

# 気象庁の青森市の市区町村コード
AREA_CODE = "0220100"

WARNING_URL = (
    f"https://www.jma.go.jp/bosai/warning/data/r8/{PREFECTURE_CODE}.json"
)

JST = timezone(timedelta(hours=9))

# 警報・注意報のコード一覧
WARNING_CODES = {
    "00": "解除",
    "02": "暴風雪警報",
    "03": "レベル3大雨警報",
    "04": "洪水警報",
    "05": "暴風警報",
    "06": "大雪警報",
    "07": "波浪警報",
    "08": "レベル3高潮警報",
    "09": "レベル3土砂災害警報",
    "10": "レベル2大雨注意報",
    "12": "大雪注意報",
    "13": "風雪注意報",
    "14": "雷注意報",
    "15": "強風注意報",
    "16": "波浪注意報",
    "17": "融雪注意報",
    "18": "洪水注意報",
    "19": "レベル2高潮注意報",
    "20": "濃霧注意報",
    "21": "乾燥注意報",
    "22": "なだれ注意報",
    "23": "低温注意報",
    "24": "霜注意報",
    "25": "着氷注意報",
    "26": "着雪注意報",
    "27": "その他の注意報",
    "29": "レベル2土砂災害注意報",
    "32": "暴風雪特別警報",
    "33": "レベル5大雨特別警報",
    "35": "暴風特別警報",
    "36": "大雪特別警報",
    "37": "波浪特別警報",
    "38": "レベル5高潮特別警報",
    "39": "レベル5土砂災害特別警報",
    "43": "レベル4大雨危険警報",
    "48": "レベル4高潮危険警報",
    "49": "レベル4土砂災害危険警報"
}

# ────────────────────────────────
# サンプルデータの読み込み
DATA_FILE = os.path.join(APP_DIR, 'data', 'shelters.json')
INSTRUCTIONS_FILE = os.path.join(APP_DIR, 'data', 'instructions.json')

def load_json(path, default):
    """JSONファイルを読み込む（存在しない・壊れている場合は default を返す）"""
    try:
        with open(path, encoding='utf-8') as f:
            value = json.load(f)
            return value if isinstance(value, list) else default
    except (FileNotFoundError, json.JSONDecodeError):
        return default

shelters = load_json(DATA_FILE, [])
instructions = load_json(INSTRUCTIONS_FILE, [])

def _save_json(path, value):
    """JSONを一時ファイル経由で保存し、途中状態を残さない"""
    fd, temporary_path = tempfile.mkstemp(dir=os.path.dirname(path), prefix='.tmp-', suffix='.json')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(value, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary_path, path)
    except Exception:
        try:
            os.unlink(temporary_path)
        except OSError:
            pass
        raise


def save_instructions():
    """指示ボードのデータをファイルに保存する"""
    _save_json(INSTRUCTIONS_FILE, instructions)


def save_shelters():
    """避難所データをファイルに保存する"""
    _save_json(DATA_FILE, shelters)


def geocode_address(address):
    """住所を地図用座標へ変換する。取得できない場合はNoneを返す。"""
    if not address:
        return None
    try:
        query = quote(address)
        geocode_request = urllib.request.Request(
            f'https://nominatim.openstreetmap.org/search?format=jsonv2&limit=1&accept-language=ja&q={query}',
            headers={'User-Agent': 'bousai-app/1.0'},
        )
        with urllib.request.urlopen(geocode_request, timeout=5) as response:
            results = json.loads(response.read())
        if not results:
            return None
        return float(results[0]['lat']), float(results[0]['lon'])
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def reverse_geocode_coordinates(latitude, longitude):
    """緯度・経度を住所へ変換する。取得できない場合はNoneを返す。"""
    try:
        latitude = float(latitude)
        longitude = float(longitude)
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            return None
        query = urlencode({
            'format': 'jsonv2',
            'lat': latitude,
            'lon': longitude,
            'zoom': 18,
            'addressdetails': 1,
        })
        reverse_request = urllib.request.Request(
            f'https://nominatim.openstreetmap.org/reverse?{query}',
            headers={'Accept': 'application/json', 'User-Agent': 'bousai-app/1.0'},
        )
        with urllib.request.urlopen(reverse_request, timeout=5) as response:
            payload = json.loads(response.read())
        address_data = payload.get('address') or {}
        parts = [
            address_data.get('state'),
            address_data.get('city') or address_data.get('town') or address_data.get('village'),
            address_data.get('suburb') or address_data.get('neighbourhood'),
            address_data.get('quarter'),
            address_data.get('road'),
        ]
        return ''.join(part for part in parts if part) or None
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def get_registered_shelters(source=None):
    """登録フォームを通過した避難所だけを発信用に返す"""
    items = source if source is not None else shelters
    return [
        item for item in items
        if item.get('name')
        and item.get('area') in ('北側', '南側')
        and item.get('congestion') in ('空きあり', 'やや混雑', '満員')
        and item.get('opening_status') in ('受け入れ可', '受け入れ不可')
    ]


# ────────────────────────────────

# ────────────────────────────────
# 認証関連の設定とヘルパー関数
def is_safe_url(target):
    """リダイレクト先URLが安全かどうかチェック"""
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ('http', 'https') and ref_url.netloc == test_url.netloc

def login_required(f):
    """認証が必要なページに付けるデコレータ"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            # 現在のURLをnextパラメータとしてログイン画面にリダイレクト
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

def get_japan_time():
    """日本時間（JST）の現在時刻を取得する"""
    return datetime.now(JST).strftime("%Y年%m月%d日 %H:%M")


def format_report_time(iso_str):
    """気象庁の発表時刻（ISO形式）をJSTの表示用文字列に変換する"""
    if not iso_str:
        return "不明"
    try:
        parsed = datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
        if parsed.tzinfo:
            parsed = parsed.astimezone(JST)
        return parsed.strftime("%Y年%m月%d日 %H:%M")
    except ValueError:
        return iso_str


FILTER_KEYWORDS = {
    'pets': ('pets', ('可', '対応', '可能', 'あり', '有', 'OK', 'pet', 'pets')),
    'wheelchair': ('wheelchair', ('車椅子', '車いす', '対応', '可', 'あり', '有', 'OK', 'wheelchair')),
    'toilet': ('toilet', ('多目的', 'トイレ', '対応', '可', 'あり', '有', 'OK')),
}

FILTER_CONDITIONS = {
    'pets': 'ペット同伴可',
    'wheelchair': '車椅子対応',
    'toilet': '多目的トイレ等',
}

NEGATIVE_PATTERNS = (
    '不可', 'なし', '無し', '不可能', '未対応', '無', 'N/A', '不適', '対象外'
)


def _matches_filter(shelter, filter_name):
    """指定した施設条件が避難所データに含まれるか判定する"""
    key, keywords = FILTER_KEYWORDS.get(filter_name, (None, ()))
    if not key:
        return True

    response_conditions = shelter.get('response_conditions', [])
    if FILTER_CONDITIONS[filter_name] in response_conditions:
        return True

    value = shelter.get(key, '')
    if value is None:
        return False

    text = str(value)
    normalized = text.replace(' ', '').replace('　', '')
    if any(pattern in normalized for pattern in NEGATIVE_PATTERNS):
        return False

    return any(keyword in normalized for keyword in keywords)


def filter_shelters(district=None, active_filters=None, shelter_list=None, area=None):
    """地区・エリアと条件で避難所を絞り込む。"""
    source = shelter_list if shelter_list is not None else shelters
    selected_filters = [filter_name for filter_name in (active_filters or []) if filter_name]

    def matches(shelter):
        if district and shelter.get('district') != district:
            return False
        if area and shelter.get('area') not in (area, {'北側': '北', '南側': '南'}.get(area, area)):
            return False
        for filter_name in selected_filters:
            if filter_name == 'exclude_full':
                if shelter.get('congestion') == '満員':
                    return False
                continue
            if not _matches_filter(shelter, filter_name):
                return False
        return True

    return [s for s in source if matches(s)]


HOME_AREA_OPTIONS = (
    {'value': '', 'label': 'すべて'},
    {'value': '北', 'label': '北側'},
    {'value': '南', 'label': '南側'},
)
HOME_AREA_ALIAS_MAP = {
    '北': '北',
    '北側': '北',
    '南': '南',
    '南側': '南',
}
HOME_URGENCY_PRIORITY = {'高': 0, '中': 1, '低': 2}
INACTIVE_INSTRUCTION_STATUSES = {'解除', '完了', '終了', '停止', '無効'}


def normalize_home_area(area):
    """画面表示の地区名と内部値の両方を受け取り、正規化した地区名を返す"""
    if area is None:
        raise ValueError('area is required')
    normalized = str(area).strip()
    if not normalized:
        raise ValueError('area is required')
    normalized = HOME_AREA_ALIAS_MAP.get(normalized, normalized)
    if normalized not in {'北', '南'}:
        raise ValueError(f'unsupported area: {area}')
    return normalized


def get_home_instructions(area, source=None):
    """住民向けの発信を取得し、地域指定があれば絞り込む"""
    normalized_area = None if not str(area or '').strip() else normalize_home_area(area)
    items = source if source is not None else instructions
    resident_items = []

    for item in items:
        if item.get('target') != '住民':
            continue
        item_area = str(item.get('area', '')).strip()
        if normalized_area and HOME_AREA_ALIAS_MAP.get(item_area, item_area) != normalized_area:
            continue
        status = str(item.get('status', '')).strip()
        if status in INACTIVE_INSTRUCTION_STATUSES:
            continue
        resident_items.append(item)

    def urgency_rank(item):
        urgency = str(item.get('urgency', '')).strip()
        return HOME_URGENCY_PRIORITY.get(urgency, 99)

    return sorted(resident_items, key=urgency_rank)


def parse_area_warnings(warning_data):
    """気象庁の新形式JSONから対象市区町村の発表・継続中の情報を抽出する"""
    if not isinstance(warning_data, list):
        raise ValueError("気象庁の警報・注意報データが新形式の配列ではありません")

    warnings = []
    seen_codes = set()
    report_datetimes = []

    for report in warning_data:
        if not isinstance(report, dict):
            continue

        report_datetime = report.get("reportDatetime")
        if isinstance(report_datetime, str) and report_datetime:
            report_datetimes.append(report_datetime)

        warning = report.get("warning")
        if not isinstance(warning, dict):
            continue

        class20_items = warning.get("class20Items", [])
        if not isinstance(class20_items, list):
            continue

        area = next(
            (
                item for item in class20_items
                if isinstance(item, dict)
                and item.get("areaCode") == AREA_CODE
            ),
            None
        )
        if not area:
            continue

        kinds = area.get("kinds", [])
        if not isinstance(kinds, list):
            continue

        for kind in kinds:
            if not isinstance(kind, dict):
                continue

            status = kind.get("status", "")
            code = kind.get("code", "")
            if status not in ("発表", "継続") or not code or code in seen_codes:
                continue

            warnings.append({
                "name": WARNING_CODES.get(
                    code,
                    f"不明な警報・注意報 (コード: {code})"
                ),
                "code": code,
                "status": status
            })
            seen_codes.add(code)

    latest_report_datetime = max(report_datetimes, default="")
    return warnings, latest_report_datetime


def get_weather_warnings():
    """対象市区町村の警報・注意報を取得する"""
    try:
        # 青森県の新形式（令和8年～）警報・注意報データを取得
        with urllib.request.urlopen(url=WARNING_URL, timeout=10) as res:
            warning_data = json.loads(res.read())

        warnings, report_datetime = parse_area_warnings(warning_data)

        return {
            "area_name": AREA_NAME,
            "warnings": warnings,
            "report_time": format_report_time(report_datetime),
            "last_fetch_time": get_japan_time()
        }

    except Exception:
        return {
            "area_name": AREA_NAME,
            "warnings": [],
            "report_time": "取得失敗",
            "last_fetch_time": get_japan_time(),
            "error": True
        }


# トップページ：templates/index.html を返す（住民向け指示も表示する）
@app.route('/')
def index():
    resident_notices = [i for i in instructions if i.get('target') == '住民']
    return render_template(
        'index.html',
        resident_notices=resident_notices,
        area_options=HOME_AREA_OPTIONS,
        shelters=shelters
    )

# ログインページ
@app.route('/login', methods=['GET', 'POST'])
def login():
    # リダイレクト先を取得（デフォルトは避難所登録画面）
    next_url = request.args.get('next') or request.form.get('next')

    # 安全でないURLの場合はデフォルトページにリダイレクト
    if not next_url or not is_safe_url(next_url):
        next_url = url_for('shelter_register')

    if request.method == 'POST':
        password = request.form.get('password', '')

        # 建物名は使わず、設定された管理者パスワードだけで認証する。
        username, registered_password = next(iter(ADMIN_CREDENTIALS.items()))
        if registered_password == password:
            session['logged_in'] = True
            session['username'] = username
            # ログイン成功後は指定されたページにリダイレクト
            return redirect(next_url)
        return render_template('login.html', error=True, message="パスワードが正しくありません。", next=next_url)

    # ログイン済みの場合は指定されたページにリダイレクト
    if session.get('logged_in'):
        return redirect(next_url)

    return render_template('login.html', next=next_url)

# ログアウト
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/shelter_register', methods=['GET', 'POST'])
@login_required
def shelter_register():
    form_values = {
        'registered_name': request.form.get('name', '').strip(),
        'registered_area': request.form.get('area', '').strip(),
        'registered_postal_code': request.form.get('postal_code', '').strip(),
        'registered_address': request.form.get('address', '').strip(),
        'registered_contact': request.form.get('contact', '').strip(),
        'registered_conditions': request.form.getlist('response_conditions'),
        'registered_congestion': request.form.get('congestion', '').strip(),
        'registered_opening_status': request.form.get('opening_status', '').strip(),
    }
    if request.method == 'POST':
        name = form_values['registered_name']
        if not name:
            return render_template('shelter_register.html', error=True, message='避難所名を入力してください', **form_values)
        if any(item.get('name') == name for item in shelters):
            return render_template('shelter_register.html', error=True, message='同じ避難所名がすでに登録されています', **form_values)
        if form_values['registered_area'] not in ('北側', '南側'):
            return render_template('shelter_register.html', error=True, message='エリアを選択してください', **form_values)
        if form_values['registered_congestion'] not in ('空きあり', 'やや混雑', '満員'):
            return render_template('shelter_register.html', error=True, message='混雑状況を選択してください', **form_values)
        if form_values['registered_opening_status'] not in ('受け入れ可', '受け入れ不可'):
            return render_template('shelter_register.html', error=True, message='開設状況を選択してください', **form_values)

        shelter = {
            'id': max((item.get('id', 0) for item in shelters), default=0) + 1,
            'name': name,
            'area': form_values['registered_area'],
            'postal_code': form_values['registered_postal_code'],
            'address': form_values['registered_address'],
            'contact': form_values['registered_contact'],
            'response_conditions': form_values['registered_conditions'],
            'congestion': form_values['registered_congestion'],
            'opening_status': form_values['registered_opening_status'],
            'district': request.form.get('district', '').strip(),
        }
        coordinates = geocode_address(shelter['address'])
        if coordinates:
            shelter['latitude'], shelter['longitude'] = coordinates
        try:
            shelters.append(shelter)
            save_shelters()
        except Exception:
            shelters.pop()
            return render_template('shelter_register.html', error=True, message='避難所の保存に失敗しました', **form_values)
        return render_template('shelter_register.html', success=True, message='避難所を登録しました。', **form_values)

    return render_template('shelter_register.html', **form_values)

# 避難所検索ページ
@app.route('/shelter_search')
def shelter_search():
    active_filters = request.args.getlist('filters')
    return render_template(
        'shelter_search.html',
        active_filters=active_filters,
        area=request.args.get('area', ''),
        district=request.args.get('district', ''),
        pet_ok=request.args.get('pet_ok', ''),
        wheelchair_ok=request.args.get('wheelchair_ok', ''),
        multipurpose_toilet=request.args.get('multipurpose_toilet', ''),
        error_message=request.args.get('error_message', '')
    )

# 全施設一覧ページ
@app.route('/all_shelters')
def all_shelters():
    active_filters = request.args.getlist('filters')
    results = filter_shelters(None, active_filters)
    return render_template(
        'search_results.html',
        results=results,
        district='',
        active_filters=active_filters,
        area=''
    )


# 指示ボード：住民向けの指示を一覧で確認する
@app.route('/board', methods=['GET', 'POST'])
@login_required
def board():
    registered_shelters = get_registered_shelters()
    form_values = {
        'selected_regions': request.form.getlist('region'),
        'selected_disasters': request.form.getlist('disaster'),
        'selected_shelters': request.form.getlist('shelter'),
        'selected_urgency': request.form.get('urgency', '').strip(),
        'other_message': request.form.get('other_message', '').strip(),
    }
    if request.method == 'POST':
        regions = form_values['selected_regions']
        disasters = form_values['selected_disasters']
        selected_shelters = form_values['selected_shelters']
        urgency = form_values['selected_urgency']
        if not regions or not disasters or not selected_shelters or urgency not in ('低', '中', '高'):
            resident_instructions = sorted(
                (item for item in instructions if item.get('target', '住民') == '住民'),
                key=lambda item: item.get('id', 0),
                reverse=True,
            )
            return render_template(
                'board.html',
                instructions=resident_instructions,
                shelters=registered_shelters,
                error='地域・災害・避難所・緊急度をすべて入力してください。',
                **form_values,
            )

        now = get_japan_time()
        region_text = '、'.join(regions)
        disaster_text = '、'.join(disasters)
        shelter_text = '、'.join(selected_shelters)
        instruction = {
            'id': max((item.get('id', 0) for item in instructions), default=0) + 1,
            'target': '住民',
            'content': '、'.join(filter(None, (disaster_text, shelter_text, form_values['other_message']))),
            'shelter': shelter_text,
            'status': '発信中',
            'created_at': now,
            'updated_at': now,
            'region': region_text,
            'disaster': disaster_text,
            'urgency': urgency,
            'other_message': form_values['other_message'],
            # 既存の住民向け表示・エリアAPIとの互換用。
            'area': '北' if any(region in ('北部', '北側') for region in regions) else '南',
        }
        try:
            instructions.insert(0, instruction)
            save_instructions()
        except Exception:
            if instructions and instructions[0] is instruction:
                instructions.pop(0)
            resident_instructions = sorted(
                (item for item in instructions if item.get('target', '住民') == '住民'),
                key=lambda item: item.get('id', 0),
                reverse=True,
            )
            return render_template(
                'board.html',
                instructions=resident_instructions,
                shelters=registered_shelters,
                error='発信の保存に失敗しました。',
                **form_values,
            )
    resident_instructions = sorted(
        (item for item in instructions if item.get('target', '住民') == '住民'),
        key=lambda item: item.get('id', 0),
        reverse=True,
    )
    return render_template(
        'board.html',
        instructions=resident_instructions,
        shelters=registered_shelters,
        success=request.method == 'POST',
        **form_values,
    )

# 検索結果ページ：templates/search_results.html を返す
@app.route('/search_results')
def search_results():
    district = request.args.get('district', '').strip()
    area = request.args.get('area', '').strip()
    if not area:
        return redirect(url_for('shelter_search', error_message='エリアを選択してください。'))
    active_filters = request.args.getlist('filters')
    legacy_filters = {
        'pet_ok': 'pets',
        'wheelchair_ok': 'wheelchair',
        'multipurpose_toilet': 'toilet',
    }
    for parameter, filter_name in legacy_filters.items():
        if request.args.get(parameter) == '1' and filter_name not in active_filters:
            active_filters.append(filter_name)

    results = filter_shelters(district or None, active_filters, area=area or None)
    return render_template(
        'search_results.html',
        results=results,
        district=district,
        area=area,
        pet_ok='1' if 'pets' in active_filters else '',
        wheelchair_ok='1' if 'wheelchair' in active_filters else '',
        multipurpose_toilet='1' if 'toilet' in active_filters else '',
        active_filters=active_filters,
    )

# JSON API：/shelters?district=地区名
@app.route('/shelters', methods=['GET'])
def get_shelters():
    district = request.args.get('district', '').strip()
    area = request.args.get('area', '').strip()
    results = filter_shelters(district or None, request.args.getlist('filters'), area=area or None)

    if not results:
        # 見つからなければエラー JSON を返す
        return jsonify({'error': 'No shelters found'}), 404

    # 見つかったらリストを JSON で返す
    return jsonify(results)

# 気象警報・注意報API
@app.route('/api/weather_warnings')
def api_weather_warnings():
    """気象警報・注意報をJSON形式で返すAPI"""
    response = jsonify(get_weather_warnings())
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


@app.route('/api/home_instructions')
def api_home_instructions():
    """住民向けの指示・発信をエリア別に返す"""
    area = request.args.get('area', '').strip()
    try:
        normalized_area = '' if not area else normalize_home_area(area)
        payload = {
            'area': normalized_area,
            'instructions': get_home_instructions(area)
        }
        return jsonify(payload)
    except ValueError:
        return jsonify({'error': 'invalid_area'}), 400


@app.route('/api/reverse-geocode')
def api_reverse_geocode():
    """現在地の緯度・経度を住所へ変換する"""
    address = reverse_geocode_coordinates(
        request.args.get('latitude'),
        request.args.get('longitude'),
    )
    if address is None:
        return jsonify({'error': '住所を取得できませんでした。'}), 502
    return jsonify({'address': address})


if __name__ == '__main__':
    app.run(debug=True, port=5000)
