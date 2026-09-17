# 防災アプリ

住民向けの避難所検索・気象情報表示と、管理者向けの避難所登録・発信ボードを提供する Flask アプリです。データは `bousai_app/data/` の JSON ファイルに保存します。

## 起動方法

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export FLASK_SECRET_KEY='development-secret'
export ADMIN_USERNAME='admin'
export ADMIN_PASSWORD='123'
python app.py
```

ブラウザで `http://127.0.0.1:5000/` を開きます。環境変数を省略した場合の認証情報は開発用に `admin` / `123` です。本番環境では必ず `FLASK_SECRET_KEY`、`ADMIN_USERNAME`、`ADMIN_PASSWORD` を設定してください。

## テスト

```bash
python -m unittest discover -s tests -v
```

気象庁APIやOpenStreetMap/Leafletの取得に失敗しても、気象取得エラー表示、地図の代替文、検索・フォームは利用できます。
