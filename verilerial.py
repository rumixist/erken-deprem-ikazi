import sqlite3
import requests
from bs4 import BeautifulSoup
import time
import datetime

# Marmara Bölgesi Koordinatları
min_lat = 39.0
max_lat = 42.5
min_lon = 26.0
max_lon = 30.8

# Veritabanı bağlantısını aç (veritabanı yoksa oluşturur)
conn = sqlite3.connect('earthquakes.db')
cursor = conn.cursor()

# Deprem tablosu oluştur (ilk çalıştırmada)
cursor.execute('''
CREATE TABLE IF NOT EXISTS earthquakes (
    tarih TEXT,  -- 'timestamp' yerine 'tarih' kullanıldı
    enlem REAL,
    boylam REAL,
    derinlik REAL,
    tip TEXT,
    buyukluk REAL,
    UNIQUE(tarih)  -- 'timestamp' yerine 'tarih' ile UNIQUE kısıtlaması
)
''')

# Öncü Deprem Analizi için eşik değerleri
foreshock_threshold = 4.0  # Öncü depremler için büyüklük eşik değeri
foreshock_time_window = 10  # Öncü depremlerin zaman aralığı (dakika cinsinden)

def is_in_marmara(enlem, boylam):
    return min_lat <= enlem <= max_lat and min_lon <= boylam <= max_lon

def save_earthquake_to_db(tarih, enlem, boylam, derinlik, tip, buyukluk):
    try:
        cursor.execute('''
        INSERT OR IGNORE INTO earthquakes (tarih, enlem, boylam, derinlik, tip, buyukluk)
        VALUES (?, ?, ?, ?, ?, ?)
        ''', (tarih, enlem, boylam, derinlik, tip, buyukluk))
        conn.commit()
    except sqlite3.Error as e:
        print(f"[HATA] Veritabanı hatası: {e}")

def fetch_afad_earthquake_html():
    try:
        url = "https://deprem.afad.gov.tr/last-earthquakes.html"
        response = requests.get(url, timeout=10)
        response.raise_for_status()

        soup = BeautifulSoup(response.content, "html.parser")
        table = soup.find("table", {"class": "content-table"})

        if not table:
            print("[HATA] Tablo bulunamadı.")
            return

        rows = table.find_all("tr")[1:]  # Başlık satırını atla

        for row in rows:
            cols = row.find_all("td")
            if len(cols) >= 6:
                tarih = cols[0].text.strip()
                enlem = float(cols[1].text.strip())
                boylam = float(cols[2].text.strip())
                derinlik = float(cols[3].text.strip())
                tip = cols[4].text.strip()
                buyukluk = float(cols[5].text.strip())

                if is_in_marmara(enlem, boylam):
                    print(f"[Deprem] Tarih: {tarih}, Enlem: {enlem}, Boylam: {boylam}, Derinlik: {derinlik}km, Tip: {tip}, Büyüklük: {buyukluk}")

                    # Depremi veritabanına kaydet
                    save_earthquake_to_db(tarih, enlem, boylam, derinlik, tip, buyukluk)

                    # Öncü deprem analizi yap
                    check_for_foreshocks()

    except Exception as e:
        print(f"[HATA] Veri çekme hatası: {e}")

if __name__ == "__main__":
    while True:
        fetch_afad_earthquake_html()
        print("10 dakika bekleniyor...")
        time.sleep(600)

# Uygulama sonlandığında veritabanı bağlantısını kapat
conn.close()
