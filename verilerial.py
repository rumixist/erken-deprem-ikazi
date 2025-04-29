import sqlite3
import requests
from bs4 import BeautifulSoup
# import time # Artık time.sleep kullanmayacağımız için bu import'a gerek yok
import datetime
import os # Ortam değişkenlerini okumak için (opsiyonel ama iyi pratik)

# Marmara Bölgesi Koordinatları
min_lat = 39.0
max_lat = 42.5
min_lon = 26.0
max_lon = 30.8

# Veritabanı dosyasının yolu
# Railway'deki kalıcı depolama (Persistent Volume) Mount Path'ine işaret etmeli.
# Varsayılan olarak /app altında bir 'data' klasörüne bağlayacağız.
# DATABASE_PATH = '/app/data/earthquakes.db' # Sabit yol kullanmak yerine ortam değişkeni okumak daha esnek olabilir
DATABASE_PATH = os.environ.get('DATABASE_PATH', '/app/data/earthquakes.db') # Ortam değişkeni yoksa varsayılanı kullan

# Veritabanı bağlantısını aç (veritabanı yoksa oluşturur)
# Bağlantıyı ana blokta açıp, fonksiyonlara 'cursor' veya 'conn' objesini geçirmek
# veya her fonksiyonda açıp kapatmak gibi farklı yaklaşımlar olabilir.
# Basitlik için şimdilik global bağlantı objelerini kullanmaya devam edelim.
# Ancak Railway'de her çalıştırma yeni bir süreç başlatacağı için bu global objeler
# her çalıştırmada yeniden oluşturulacaktır, bu beklenen davranıştır.
conn = None
cursor = None

def get_db_connection():
    """Veritabanı bağlantısını kurar ve cursor döndürür."""
    global conn, cursor
    if conn is None:
        try:
            # Bağlantı kurulurken klasörün varlığını kontrol etmek ve oluşturmak iyi olabilir
            db_dir = os.path.dirname(DATABASE_PATH)
            if not os.path.exists(db_dir):
                os.makedirs(db_dir, exist_ok=True) # Klasörü oluştur (zaten varsa hata vermez)
                print(f"Veritabanı klasörü oluşturuldu: {db_dir}")

            conn = sqlite3.connect(DATABASE_PATH)
            cursor = conn.cursor()
            print(f"Veritabanı bağlantısı kuruldu: {DATABASE_PATH}")

            # Deprem tablosu oluştur (eğer yoksa)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS earthquakes (
                    tarih TEXT,
                    enlem REAL,
                    boylam REAL,
                    derinlik REAL,
                    tip TEXT,
                    buyukluk REAL,
                    UNIQUE(tarih) -- Tarih sütununu benzersiz yap
                )
            ''')
            conn.commit()
            print("Veritabanı tablosu kontrol edildi/oluşturuldu.")

        except sqlite3.Error as e:
            print(f"[HATA] Veritabanı bağlantısı veya tablo oluşturma hatası: {e}")
            # Hata durumunda bağlantıyı kapatıp None yapalım
            if conn:
                conn.close()
            conn = None
            cursor = None
            raise # Hatayı tekrar fırlat ki ana blok yakalayabilsin
        except Exception as e:
            print(f"[HATA] Veritabanı bağlantısı sırasında beklenmedik hata: {e}")
            if conn:
                conn.close()
            conn = None
            cursor = None
            raise # Hatayı tekrar fırlat


def close_db_connection():
    """Veritabanı bağlantısını kapatır."""
    global conn, cursor
    if conn:
        conn.close()
        print("Veritabanı bağlantısı kapatıldı.")
    conn = None
    cursor = None


def is_in_marmara(enlem, boylam):
    """Verilen enlem ve boylamın Marmara Bölgesi içinde olup olmadığını kontrol eder."""
    # is_in_marmara fonksiyonu zaten float değerlerle çalışıyor, ek kontrol gerekmez.
    return min_lat <= enlem <= max_lat and min_lon <= boylam <= max_lon

def save_earthquake_to_db(tarih, enlem, boylam, derinlik, tip, buyukluk):
    """Yeni deprem bilgisini veritabanına ekler."""
    # get_db_connection fonksiyonu çağrılmadan bu fonksiyon çağrılmamalı
    if cursor is None:
        print("[HATA] Veritabanı bağlantısı aktif değil. Kaydetme başarısız.")
        return

    try:
        # INSERT OR IGNORE: Eğer 'tarih' sütununda aynı değer varsa satırı eklemeyi yoksayar.
        cursor.execute('''
            INSERT OR IGNORE INTO earthquakes (tarih, enlem, boylam, derinlik, tip, buyukluk)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (tarih, enlem, boylam, derinlik, tip, buyukluk))
        # Kaç satır eklendiğini kontrol edebiliriz
        if cursor.rowcount > 0:
            conn.commit()
            # print(f"[DB] Eklendi: Tarih: {tarih}, Büyüklük: {buyukluk}") # Çok fazla çıktı olabilir, kaldırıldı
            return True # Ekleme başarılı
        else:
            # print(f"[DB] Mevcut: Tarih: {tarih} zaten veritabanında.") # Çok fazla çıktı olabilir, kaldırıldı
            return False # Zaten mevcut
    except sqlite3.Error as e:
        print(f"[HATA] Veritabanına kayıt hatası: {e}")
        # Hata durumunda rollback yapmak iyi bir pratiktir
        if conn:
            conn.rollback()
        return False # Ekleme başarısız
    except Exception as e:
         print(f"[HATA] save_earthquake_to_db sırasında beklenmedik hata: {e}")
         if conn:
             conn.rollback()
         return False


def fetch_and_save_earthquakes():
    """
    AFAD web sitesinden son deprem verilerini çeker, Marmara Bölgesi'ndekileri filtreler
    ve veritabanına kaydeder. Bu fonksiyon bir kere çalışacak şekilde tasarlanmıştır.
    """
    print(f"--- {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} --- Veri Çekme Başladı ---")

    # Veritabanı bağlantısını kur
    try:
        get_db_connection()
    except Exception:
        print("Veritabanı bağlantısı kurulamadığı için veri çekme iptal edildi.")
        return # Bağlantı hatası olursa fonksiyondan çık

    added_count = 0 # Bu çalıştırmada eklenen deprem sayısı
    processed_count = 0 # İşlenen toplam deprem sayısı

    try:
        url = "https://deprem.afad.gov.tr/last-earthquakes.html"
        # Timeout süresi (sunucu yanıt vermezse ne kadar bekleneceği)
        response = requests.get(url, timeout=20)
        # HTTP hata kodları için kontrol (örn. 404 Not Found, 500 Internal Server Error)
        response.raise_for_status()
        # print(f"Web sayfasından veri başarıyla alındı (Status Code: {response.status_code}).") # Çok fazla çıktı olabilir

        soup = BeautifulSoup(response.content, "html.parser")
        table = soup.find("table", {"class": "content-table"})

        if not table:
            print("[HATA] Web sayfasında deprem tablosu (class='content-table') bulunamadı.")
            return # Fonksiyondan çık

        # Tablodaki tüm satırları al (başlık satırı hariç)
        rows = table.find_all("tr")[1:]

        if not rows:
            print("[BİLGİ] Deprem tablosunda veri satırı bulunamadı.")
            return # Fonksiyondan çık

        print(f"{len(rows)} adet deprem kaydı bulundu. Marmara Bölgesi için kontrol ediliyor...")

        for i, row in enumerate(rows): # Satır numarasını da takip etmek için enumerate kullanıldı
            cols = row.find_all("td")
            # Yeterli sütun olup olmadığını kontrol et (en az 6 sütun bekleniyor)
            if len(cols) >= 6:
                processed_count += 1
                try:
                    tarih = cols[0].text.strip()
                    # Verileri çekerken doğrudan float'a dönüştürmeyi dene
                    enlem_str = cols[1].text.strip()
                    boylam_str = cols[2].text.strip()
                    derinlik_str = cols[3].text.strip()
                    tip = cols[4].text.strip()
                    buyukluk_str = cols[5].text.strip()
                    # Lokasyon sütunu (cols[6]) opsiyonel olarak alınabilir

                    # Veri dönüşümlerini yap
                    enlem = float(enlem_str)
                    boylam = float(boylam_str)
                    # Derinlik '-' ise 0.0 olarak ata, değilse float'a çevir
                    derinlik = float(derinlik_str) if derinlik_str and derinlik_str != '-' else 0.0
                    # Büyüklük '-' ise 0.0 olarak ata, değilse float'a çevir
                    buyukluk = float(buyukluk_str) if buyukluk_str and buyukluk_str != '-' else 0.0


                    # Deprem Marmara Bölgesi'nde mi kontrol et
                    if is_in_marmara(enlem, boylam):
                        # Depremi veritabanına eklemeyi dene
                        if save_earthquake_to_db(tarih, enlem, boylam, derinlik, tip, buyukluk):
                            added_count += 1
                            # print(f"[Marmara Depremi Eklendi] Tarih: {tarih}, Büyüklük: {buyukluk:.1f}") # Çok fazla çıktı olabilir
                        # else:
                            # print(f"[Marmara Depremi Mevcut] Tarih: {tarih}") # Çok fazla çıktı olabilir


                except ValueError as ve:
                    # Hangi sütunda hata olduğunu belirtmek daha faydalı olabilir
                    print(f"[HATA] Satır {i+1} işlenirken değer dönüşüm hatası: {ve} - Sütun Değerleri: {[c.text.strip() for c in cols[:6]]}")
                except Exception as e:
                    print(f"[HATA] Satır {i+1} işlenirken beklenmedik hata: {e} - Satır: {[c.text.strip() for c in cols[:6]]}")
            else:
                # print(f"[UYARI] Satır {i+1} beklenenden az sütun ({len(cols)}) içeriyor, atlandı: {[c.text.strip() for c in cols]}") # Çok fazla çıktı olabilir
                pass # Uyarıları azaltmak için atlanan satırları yazdırma

        print(f"--- Veri Çekme Tamamlandı ---")
        print(f"İşlenen toplam deprem kaydı: {processed_count}")
        print(f"Bu çalıştırmada veritabanına {added_count} yeni Marmara depremi eklendi.")


    except requests.exceptions.Timeout:
        print(f"[HATA] AFAD sunucusuna bağlanırken zaman aşımı oldu ({url}).")
    except requests.exceptions.HTTPError as http_err:
        print(f"[HATA] HTTP hatası oluştu: {http_err} (Status Code: {http_err.response.status_code})")
    except requests.exceptions.ConnectionError as conn_err:
        print(f"[HATA] Ağ bağlantı hatası: {conn_err}. İnternet bağlantınızı kontrol edin.")
    except requests.exceptions.RequestException as req_err:
        print(f"[HATA] Veri çekme sırasında genel bir ağ hatası oluştu: {req_err}")
    except Exception as e:
        # BeautifulSoup veya diğer beklenmedik hatalar için
        print(f"[HATA] Veri işleme sırasında beklenmedik bir hata oluştu: {e}")
    finally:
        # İşlem bitince veritabanı bağlantısını kapat
        close_db_connection()


# --- Ana Kod Bloğu ---
if __name__ == "__main__":
    # Bu blok Railway'de Cron Job çalıştığında bir kere çalışacak
    fetch_and_save_earthquakes()

    # Script bittiğinde otomatik olarak kapanır, conn.close() finally bloğunda çağrılıyor.

