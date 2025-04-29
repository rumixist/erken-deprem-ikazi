from flask import Flask, jsonify
import requests
from bs4 import BeautifulSoup
import psycopg2
import os
from datetime import datetime

app = Flask(__name__)

# Marmara Bölgesi Koordinatları
min_lat = 39.0
max_lat = 42.5
min_lon = 26.0
max_lon = 30.8

def is_in_marmara(lat, lon):
    return min_lat <= lat <= max_lat and min_lon <= lon <= max_lon

def get_db_connection():
    conn = psycopg2.connect(os.environ['DATABASE_URL'], sslmode='require')
    return conn

def create_table():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS earthquakes (
            tarih TEXT PRIMARY KEY,
            enlem REAL,
            boylam REAL,
            derinlik TEXT,
            tip TEXT,
            buyukluk REAL
        );
    ''')
    conn.commit()
    cur.close()
    conn.close()

def save_earthquake(tarih, enlem, boylam, derinlik, tip, buyukluk):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('''
            INSERT INTO earthquakes (tarih, enlem, boylam, derinlik, tip, buyukluk)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (tarih) DO NOTHING;
        ''', (tarih, enlem, boylam, derinlik, tip, buyukluk))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[HATA] DB Kaydı: {e}")

def fetch_afad():
    try:
        url = "https://deprem.afad.gov.tr/last-earthquakes.html"
        r = requests.get(url, timeout=10)
        r.raise_for_status()

        soup = BeautifulSoup(r.content, "html.parser")
        table = soup.find("table", {"class": "content-table"})

        if not table:
            return "[HATA] Tablo bulunamadı."

        rows = table.find_all("tr")[1:]

        count = 0
        for row in rows:
            cols = row.find_all("td")
            if len(cols) >= 6:
                tarih = cols[0].text.strip()
                enlem = float(cols[1].text.strip())
                boylam = float(cols[2].text.strip())
                derinlik = cols[3].text.strip()
                tip = cols[4].text.strip()
                buyukluk = float(cols[5].text.strip())

                if is_in_marmara(enlem, boylam):
                    save_earthquake(tarih, enlem, boylam, derinlik, tip, buyukluk)
                    count += 1

        return f"{count} deprem kaydedildi."

    except Exception as e:
        return f"[HATA] Veri çekilemedi: {e}"

@app.route("/")
def home():
    return "Deprem Takip API Çalışıyor."

@app.route("/update")
def update():
    create_table()
    result = fetch_afad()
    return jsonify({"sonuc": result, "zaman": datetime.utcnow().isoformat()})

if __name__ == "__main__":
    app.run()
