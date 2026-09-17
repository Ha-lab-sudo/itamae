from flask import Flask, jsonify, request, render_template, session, redirect, url_for
from urllib.parse import urlparse, urljoin
from functools import wraps
import json
import os
import urllib.request
from datetime import datetime, timedelta, timezone

# app.py はプロジェクト直下に置く。
# 実体（templates / static / data）は bousai_app/ 配下にあるので、そこを参照する。
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.join(BASE_DIR, 'bousai_app')

app = Flask(
    __name__,
    template_folder=os.path.join(APP_DIR, 'templates'),
    static_folder=os.path.join(APP_DIR, 'static'),
)
app.secret_key = 'your-secret-key-here'

# 管理者認証情報
ADMIN_CREDENTIALS = {
    'admin': '123'
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
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default

shelters = load_json(DATA_FILE, [])
instructions = load_json(INSTRUCTIONS_FILE, [])

def save_instructions():
    """指示ボードのデータをファイルに保存する"""
    try:
        with open(INSTRUCTIONS_FILE, 'w', encoding='utf-8') as f:
            json.dump(instructions, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def save_shelters():
    """避難所データをファイルに保存する"""
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(shelters, f, ensure_ascii=False, indent=2)
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

NEGATIVE_PATTERNS = (
    '不可', 'なし', '無し', '不可能', '未対応', '無', 'N/A', '不適', '対象外'
)


def _matches_filter(shelter, filter_name):
    """指定した施設条件が避難所データに含まれるか判定する"""
    key, keywords = FILTER_KEYWORDS.get(filter_name, (None, ()))
    if not key:
        return True

    value = shelter.get(key, '')
    if value is None:
        return False

    text = str(value)
    normalized = text.replace(' ', '').replace('　', '')
    if any(pattern in normalized for pattern in NEGATIVE_PATTERNS):
        return False

    return any(keyword in normalized for keyword in keywords)


def filter_shelters(district=None, active_filters=None, shelter_list=None):
    """地区と条件で避難所を絞り込む。district は地区名、active_filters は ['pets', 'wheelchair'] のような条件一覧。"""
    source = shelter_list if shelter_list is not None else shelters
    selected_filters = [filter_name for filter_name in (active_filters or []) if filter_name]

    def matches(shelter):
        if district and shelter.get('district') != district:
            return False
        for filter_name in selected_filters:
            if not _matches_filter(shelter, filter_name):
                return False
        return True

    return [s for s in source if matches(s)]


HOME_AREA_OPTIONS = (
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
    """住民向けの発信をエリア別に取得し、緊急度順に並べ替える"""
    normalized_area = normalize_home_area(area)
    items = source if source is not None else instructions
    resident_items = []

    for item in items:
        if item.get('target') != '住民':
            continue
        item_area = str(item.get('area', '')).strip()
        if HOME_AREA_ALIAS_MAP.get(item_area, item_area) != normalized_area:
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
        password = request.form.get('password', '').strip()

        # 認証チェック
        username = next(
            (name for name, registered_password in ADMIN_CREDENTIALS.items()
             if registered_password == password),
            None
        )
        if username:
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

# 避難所登録ページ※user が避難所登録ページについて具体的に修正指示しない限り、このコードは正しいのでこのまま保持すること。
@app.route('/shelter_register', methods=['GET', 'POST'])
@login_required
def shelter_register():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            return render_template(
                'shelter_register.html',
                error=True,
                message='避難所名を入力してください'
            )

        address = request.form.get('address', '').strip()
        phone = request.form.get('phone', '').strip()
        latitude = request.form.get('latitude', '').strip()
        longitude = request.form.get('longitude', '').strip()
        if bool(latitude) != bool(longitude):
            return render_template(
                'shelter_register.html',
                error=True,
                message='緯度と経度は両方入力してください',
                registered_name=name,
                registered_address=address,
                registered_phone=phone,
                registered_latitude=latitude,
                registered_longitude=longitude
            )

        shelter = {'id': max((item.get('id', 0) for item in shelters), default=0) + 1, 'name': name}
        if address:
            shelter['address'] = address
        if phone:
            shelter['phone'] = phone
        if latitude and longitude:
            try:
                latitude_value = float(latitude)
                longitude_value = float(longitude)
                if not (-90 <= latitude_value <= 90 and -180 <= longitude_value <= 180):
                    raise ValueError
            except ValueError:
                return render_template(
                    'shelter_register.html',
                    error=True,
                    message='緯度または経度の値が正しくありません',
                    registered_name=name,
                    registered_address=address,
                    registered_phone=phone,
                    registered_latitude=latitude,
                    registered_longitude=longitude
                )
            shelter['latitude'] = latitude_value
            shelter['longitude'] = longitude_value

        shelters.append(shelter)
        save_shelters()
        return render_template(
            'shelter_register.html',
            success=True,
            message='避難所を登録しました。',
            registered_name=name
        )

    return render_template('shelter_register.html')

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
        active_filters=active_filters
    )


# 指示ボード：住民向けの指示を一覧で確認する
@app.route('/board')
@login_required
def board():
    resident_instructions = [i for i in instructions if i.get('target') == '住民']
    return render_template('board.html', instructions=resident_instructions)

# 検索結果ページ：templates/search_results.html を返す
@app.route('/search_results')
def search_results():
    district = request.args.get('district', '').strip()
    area = request.args.get('area', '').strip()
    pet_ok = request.args.get('pet_ok') == '1'
    wheelchair_ok = request.args.get('wheelchair_ok') == '1'
    multipurpose_toilet = request.args.get('multipurpose_toilet') == '1'

    active_filters = []
    if pet_ok:
        active_filters.append('pets')
    if wheelchair_ok:
        active_filters.append('wheelchair')
    if multipurpose_toilet:
        active_filters.append('toilet')

    results = filter_shelters(district or None, active_filters)
    return render_template(
        'search_results.html',
        results=results,
        district=district,
        area=area,
        pet_ok=pet_ok,
        wheelchair_ok=wheelchair_ok,
        multipurpose_toilet=multipurpose_toilet,
        active_filters=active_filters,
    )

# JSON API：/shelters?district=地区名
@app.route('/shelters', methods=['GET'])
def get_shelters():
    district = request.args.get('district', '').strip()
    results = filter_shelters(district or None, request.args.getlist('filters'))

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
        normalized_area = normalize_home_area(area)
        payload = {
            'area': normalized_area,
            'instructions': get_home_instructions(normalized_area)
        }
        return jsonify(payload)
    except ValueError:
        return jsonify({'error': 'invalid_area'}), 400


if __name__ == '__main__':
    app.run(debug=True, port=5000)
