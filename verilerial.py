import time
import requests

EARTHQUAKE_API = ""  # (burayı gerçek kaynakla değiştireceğiz)

MIN_MAGNITUDE = 4.0

def check_earthquakes():
    try:
        response = requests.get(EARTHQUAKE_API, timeout=10)
        data = response.json()

        for quake in data['depremler']:
            magnitude = float(quake['mag'])
            location = quake['lokasyon']
            time_occured = quake['zaman']

            if magnitude >= MIN_MAGNITUDE:
                print(f"[ALARM] {time_occured} tarihinde {location} bölgesinde {magnitude} büyüklüğünde deprem!")
                # ALARM SİSTEMİ BURAYA

    except Exception as e:
        print(f"[HATA] Veri çekilirken hata oluştu: {str(e)}")

if __name__ == "__main__":
    while True:
        check_earthquakes()
        print("10 dakika uyuyor...")
        time.sleep(600)
