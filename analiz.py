import sqlite3
import datetime
import math
import statistics # Standart sapma için
from collections import defaultdict
import json # JSON dosyası yazmak için
import subprocess # Git komutlarını çalıştırmak için
import os # Ortam değişkenlerini okumak ve dosya yolları için
import shutil # Dosya kopyalamak için

# Veritabanı dosyasının yolu
# Railway'deki kalıcı depolama (Persistent Volume) Mount Path'ine işaret etmeli.
# Varsayılan olarak /app altında bir 'data' klasörüne bağlayacağız.
DATABASE_PATH = os.environ.get('DATABASE_PATH', '/app/data/earthquakes.db') # Ortam değişkeni yoksa varsayılanı kullan

# Analiz için zaman pencereleri (saat cinsinden)
RECENT_PERIOD_HOURS_6 = 6
RECENT_PERIOD_HOURS_24 = 24
# RECENT_PERIOD_DAYS = 1 # 24 saat zaten 1 gün, bu sabite gerek yok
SHORT_TERM_PERIOD_DAYS = 7
LONG_TERM_PERIOD_DAYS = 30 # Referans için
LONGER_TERM_DAYS = 90 # B-değeri için daha uzun pencere

# Analiz için büyüklük eşikleri
MAGNITUDE_THRESHOLD_MICRO = 2.0 # Mikro depremler
MAGNITUDE_THRESHOLD_MODERATE = 3.0 # Orta büyüklükteki depremler
MAGNITUDE_THRESHOLD_STRONG = 4.0 # Şiddetli sayılabilecek depremler
MAGNITUDE_THRESHOLD_LARGER = 5.0 # Daha büyük depremler

# Mekansal kümeleme için mesafe eşiği (km cinsinden)
SPATIAL_CLUSTER_DISTANCE_KM = 20

# B-değeri hesaplamak için minimum deprem sayısı
MIN_EQ_FOR_B_VALUE = 50 # Güvenilir bir b-değeri için daha fazla veri gerekir, bu sadece bir örnek eşik

# Haversine formülü ile iki enlem/boylam noktası arasındaki mesafeyi hesaplama (km)
EARTH_RADIUS_KM = 6371.0

# Web sitesi deponuzun URL'si (Railway Ortam Değişkeninden okunacak)
# Railway'deki Variables kısmında WEBSITE_REPO_URL olarak ayarlamalısınız.
WEBSITE_REPO_URL = os.environ.get('WEBSITE_REPO_URL')

# Web sitesi reposunu klonlayacağımız yer (Railway ortamında /app altında bir klasör olabilir)
# Bu klasör kalıcı depolama (volume) içinde OLMAMALI, çünkü repo dosyaları değişecek.
# Railway servisinin varsayılan çalışma dizini genellikle /app'tir.
WEBSITE_REPO_CLONE_DIR = '/app/website_repo_clone'

# Analiz sonuçlarının JSON dosyasının adı
ANALYSIS_JSON_FILE_NAME = 'analysis_results.json'

# Analiz sonuçlarının JSON dosyasının tam yolu (scriptin çalıştığı dizinde oluşturulacak)
# Railway'de script /app altında çalışıyorsa bu yol /app/analysis_results.json olacaktır.
ANALYSIS_JSON_FILE_PATH = os.path.join('/app', ANALYSIS_JSON_FILE_NAME)


def haversine_distance(lat1, lon1, lat2, lon2):
    """
    İki coğrafi nokta arasındaki mesafeyi Haversine formülü ile hesaplar.
    """
    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)

    dlon = lon2_rad - lon1_rad
    dlat = lat2_rad - lat1_rad

    a = math.sin(dlat / 2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    distance = EARTH_RADIUS_KM * c
    return distance

def get_db_connection():
    """Veritabanı bağlantısını kurar ve cursor döndürür."""
    try:
        # Bağlantı kurulurken klasörün varlığını kontrol etmek ve oluşturmak iyi olabilir
        db_dir = os.path.dirname(DATABASE_PATH)
        if not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True) # Klasörü oluştur (zaten varsa hata vermez)
            print(f"Veritabanı klasörü oluşturuldu: {db_dir}")

        conn = sqlite3.connect(DATABASE_PATH)
        # Rowları dictionary olarak almak için
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        print(f"Veritabanı bağlantısı kuruldu: {DATABASE_PATH}")
        return conn, cursor
    except sqlite3.Error as e:
        print(f"[HATA] Veritabanı bağlantısı hatası: {e}")
        return None, None
    except Exception as e:
        print(f"[HATA] Veritabanı bağlantısı sırasında beklenmedik hata: {e}")
        return None, None


def get_earthquakes_in_period(cursor, hours=None, days=None):
    """
    Veritabanından belirtilen zaman dilimindeki depremleri çeker.
    hours veya days parametrelerinden biri kullanılmalıdır.
    Döndürülen deprem objeleri dictionary benzeri (Row objeleri) olacaktır.
    """
    if cursor is None:
        print("[HATA] get_earthquakes_in_period: Veritabanı bağlantısı aktif değil.")
        return []

    now = datetime.datetime.now()
    if hours is not None:
        time_threshold = now - datetime.timedelta(hours=hours)
    elif days is not None:
        time_threshold = now - datetime.timedelta(days=days)
    else:
        print("[HATA] get_earthquakes_in_period: hours veya days belirtilmedi.")
        return []

    time_threshold_str = time_threshold.strftime('%Y-%m-%d %H:%M:%S')

    try:
        cursor.execute('''
            SELECT tarih, enlem, boylam, derinlik, tip, buyukluk
            FROM earthquakes
            WHERE tarih >= ?
            ORDER BY tarih ASC
        ''', (time_threshold_str,))
        # fetchall() artık Row objeleri listesi döndürecek
        return cursor.fetchall()
    except sqlite3.Error as e:
        print(f"[HATA] Veritabanından veri çekme hatası: {e}")
        return []
    except Exception as e:
        print(f"[HATA] get_earthquakes_in_period fonksiyonunda beklenmedik hata: {e}")
        return []


def analyze_seismic_rate(cursor):
    """
    Farklı zaman pencereleri için sismik aktivite hızını analiz eder
    ve uzun vadeli ortalama ile karşılaştırır. Sonuçları dictionary olarak döndürür.
    """
    print("\n--- Sismik Aktivite Hızı Analizi ---")
    results = {}

    # Farklı zaman pencereleri için depremleri çek
    eqs_6h = get_earthquakes_in_period(cursor, hours=RECENT_PERIOD_HOURS_6)
    eqs_24h = get_earthquakes_in_period(cursor, hours=RECENT_PERIOD_HOURS_24)
    eqs_7d = get_earthquakes_in_period(cursor, days=SHORT_TERM_PERIOD_DAYS)
    eqs_30d = get_earthquakes_in_period(cursor, days=LONG_TERM_PERIOD_DAYS)

    count_6h = len(eqs_6h)
    count_24h = len(eqs_24h)
    count_7d = len(eqs_7d)
    count_30d = len(eqs_30d)

    results['count_6h'] = count_6h
    results['count_24h'] = count_24h
    results['count_7d'] = count_7d
    results['count_30d'] = count_30d

    print(f"Son {RECENT_PERIOD_HOURS_6} saat içindeki deprem sayısı: {count_6h}")
    print(f"Son {RECENT_PERIOD_HOURS_24} saat ({RECENT_PERIOD_HOURS_24/24} gün) içindeki deprem sayısı: {count_24h}")
    print(f"Son {SHORT_TERM_PERIOD_DAYS} gün içindeki deprem sayısı: {count_7d}")
    print(f"Son {LONG_TERM_PERIOD_DAYS} gün içindeki toplam deprem sayısı: {count_30d}")

    # Uzun vadeli ortalama günlük deprem sayısı
    average_daily_long_term = count_30d / LONG_TERM_PERIOD_DAYS if LONG_TERM_PERIOD_DAYS > 0 else 0
    # Uzun vadeli ortalama saatlik deprem sayısı
    average_hourly_long_term = count_30d / (LONG_TERM_PERIOD_DAYS * 24) if LONG_TERM_PERIOD_DAYS > 0 else 0

    results['average_daily_long_term'] = average_daily_long_term
    results['average_hourly_long_term'] = average_hourly_long_term

    print(f"Son {LONG_TERM_PERIOD_DAYS} günün ortalama günlük deprem sayısı: {average_daily_long_term:.2f}")
    print(f"Son {LONG_TERM_PERIOD_DAYS} günün ortalama saatlik deprem sayısı: {average_hourly_long_term:.2f}")

    # Kısa vadeli aktiviteyi uzun vadeli ortalama ile karşılaştır
    print("\nHız Oranları (Uzun Vadeli Ortalamaya Göre):")
    rate_ratio_6h = None
    rate_ratio_24h = None

    if average_hourly_long_term > 0.01: # Ortalamanın çok düşük olmaması için kontrol
        rate_ratio_6h = count_6h / (average_hourly_long_term * RECENT_PERIOD_HOURS_6)
        print(f" - Son {RECENT_PERIOD_HOURS_6} saat aktivitesi, uzun vadeli ortalamanın {rate_ratio_6h:.2f} katı.")

    if average_daily_long_term > 0.01: # Günlük ortalamanın çok düşük olmaması için kontrol
        rate_ratio_24h = count_24h / average_daily_long_term
        print(f" - Son {RECENT_PERIOD_HOURS_24} saat aktivitesi, uzun vadeli günlük ortalamanın {rate_ratio_24h:.2f} katı.")

    if average_hourly_long_term <= 0.01 and average_daily_long_term <= 0.01:
         print("Uzun vadeli ortalama çok düşük, hız oranları anlamlı değil.")


    results['rate_ratio_6h'] = rate_ratio_6h
    results['rate_ratio_24h'] = rate_ratio_24h

    # Yorumlama (İstatistiksel Anomaliye Yaklaşım)
    comment = "Yeterli veri yok veya istatistiksel anomali analizi yapılamadı."
    if count_30d >= 30: # Standart sapma hesaplamak için yeterli veri olduğunu varsayalım
        daily_counts = defaultdict(int)
        for eq in eqs_30d:
            eq_date = datetime.datetime.strptime(eq['tarih'], '%Y-%m-%d %H:%M:%S').date()
            daily_counts[eq_date] += 1

        counts_list = list(daily_counts.values())

        if len(counts_list) > 1: # Standart sapma hesaplamak için en least 2 değer olmalı
            try:
                mean_daily = statistics.mean(counts_list)
                stdev_daily = statistics.stdev(counts_list)

                print(f"\nSon {LONG_TERM_PERIOD_DAYS} günün günlük deprem sayısı ortalaması: {mean_daily:.2f}, Standart Sapması: {stdev_daily:.2f}")

                if stdev_daily > 0.1: # Standart sapma sıfıra yakınsa anlamlı değil
                    z_score_24h = (count_24h - mean_daily) / stdev_daily
                    print(f"Son {RECENT_PERIOD_HOURS_24} saat sayısı, ortalamadan {z_score_24h:.2f} standart sapma uzakta.")

                    if z_score_24h > 2:
                        comment = "Son 24 saatteki sismik aktivite, istatistiksel olarak belirgin bir artış gösteriyor (Anomali!). Bu durum yakından izlenmelidir."
                    elif z_score_24h < -2:
                        comment = "Son 24 saatteki sismik aktivite, istatistiksel olarak belirgin bir düşüş gösteriyor."
                    else:
                        comment = "Son 24 saatteki sismik aktivite, istatistiksel olarak normal aralıkta görünüyor."
                else:
                    comment = "Günlük deprem sayısı varyasyonu çok düşük, istatistiksel anomali analizi yapılamadı."
            except statistics.StatisticsError as e:
                 print(f"[UYARI] İstatistik hesaplama hatası: {e}")
                 comment = "İstatistiksel anomali analizi sırasında hata oluştu."
            except Exception as e:
                 print(f"[UYARI] İstatistiksel anomali analizi sırasında beklenmedik hata: {e}")
                 comment = "İstatistiksel anomali analizi sırasında hata oluştu."

        else:
            comment = "Son 30 günde sadece 1 gün deprem oldu, istatistiksel anomali analizi yapılamadı."
    else:
        comment = f"Standart sapma hesaplamak için son {LONG_TERM_PERIOD_DAYS} günde yeterli veri yok (min 30 gün ve >1 gün aktivite önerilir)."

    results['comment'] = comment
    print(f"Yorum: {comment}")
    print("--- Analiz Sonu ---")
    return results


def analyze_spatial_clustering_advanced(cursor):
    """
    Mekansal kümelenmeleri tespit eder ve küme bilgilerini dictionary listesi olarak döndürür.
    """
    print("\n--- Mekansal Kümeleme Analizi ---")
    results = {'clusters_list': []}

    # Son RECENT_PERIOD_HOURS_24 (1 gün) içindeki depremleri al
    recent_eqs = get_earthquakes_in_period(cursor, hours=RECENT_PERIOD_HOURS_24)

    if not recent_eqs:
        print(f"Son {RECENT_PERIOD_HOURS_24} saat içinde Marmara'da deprem kaydı bulunamadı.")
        print("--- Analiz Sonu ---")
        return results

    print(f"Son {RECENT_PERIOD_HOURS_24} saat içindeki {len(recent_eqs)} deprem için mekansal kümeleme analizi yapılıyor (Eşik: {SPATIAL_CLUSTER_DISTANCE_KM} km)...")

    processed_indices = set()
    clusters_indices = [] # Tespit edilen kümeleri (indeks listesi olarak) saklamak için liste

    for i in range(len(recent_eqs)):
        if i in processed_indices:
            continue

        current_cluster = [i]
        processed_indices.add(i)
        to_process = [i]

        while to_process:
            current_idx = to_process.pop(0)
            current_eq = recent_eqs[current_idx]
            current_lat, current_lon = current_eq['enlem'], current_eq['boylam']

            for j in range(len(recent_eqs)):
                if j not in processed_indices:
                    other_eq = recent_eqs[j]
                    other_lat, other_lon = other_eq['enlem'], other_eq['boylam']

                    dist = haversine_distance(current_lat, current_lon, other_lat, other_lon)

                    if dist <= SPATIAL_CLUSTER_DISTANCE_KM:
                        current_cluster.append(j)
                        processed_indices.add(j)
                        to_process.append(j)

        if len(current_cluster) > 1: # Tek depremli kümeleri (gürültü) dahil etme
            clusters_indices.append(current_cluster)

    # Tespit edilen kümelerin bilgilerini JSON'a uygun formatta hazırla
    if clusters_indices:
        print(f"\nToplam {len(clusters_indices)} adet mekansal küme tespit edildi (Son {RECENT_PERIOD_HOURS_24} saat, Eşik: {SPATIAL_CLUSTER_DISTANCE_KM} km, Min Küme Boyutu: 2 deprem).")
        for k, cluster_indices in enumerate(clusters_indices):
            cluster_lats = [recent_eqs[i]['enlem'] for i in cluster_indices]
            cluster_lons = [recent_eqs[i]['boylam'] for i in cluster_indices]
            avg_lat = sum(cluster_lats) / len(cluster_lats) if cluster_lats else 0
            avg_lon = sum(cluster_lons) / len(cluster_lons) if cluster_lons else 0

            max_mag_eq_data = None
            max_mag = -1
            for idx in cluster_indices:
                 eq = recent_eqs[idx]
                 if eq['buyukluk'] is not None and eq['buyukluk'] > max_mag:
                      max_mag = eq['buyukluk']
                      max_mag_eq_data = { # JSON'a kaydedilecek format
                           'tarih': eq['tarih'],
                           'enlem': eq['enlem'],
                           'boylam': eq['boylam'],
                           'derinlik': eq['derinlik'],
                           'tip': eq['tip'],
                           'buyukluk': eq['buyukluk']
                      }

            results['clusters_list'].append({
                 'size': len(cluster_indices),
                 'avg_lat': avg_lat,
                 'avg_lon': avg_lon,
                 'max_mag_eq': max_mag_eq_data
            })
            print(f" - Küme #{k+1} ({len(cluster_indices)} Deprem) Ort. Konum: {avg_lat:.4f}, {avg_lon:.4f}")


    else:
        print(f"Son {RECENT_PERIOD_HOURS_24} saat içinde belirtilen mesafe eşiğinde ({SPATIAL_CLUSTER_DISTANCE_KM} km) belirgin bir mekansal kümelenme tespit edilmedi.")

    print("--- Analiz Sonu ---")
    return results


def analyze_magnitude_distribution(cursor):
    """
    Farklı zaman pencereleri için büyüklük dağılımını analiz eder.
    Sonuçları dictionary olarak döndürür.
    """
    print("\n--- Büyüklük Dağılımı Analizi ---")
    results = {}

    # Farklı zaman pencereleri için depremleri çek
    eqs_6h = get_earthquakes_in_period(cursor, hours=RECENT_PERIOD_HOURS_6)
    eqs_24h = get_earthquakes_in_period(cursor, hours=RECENT_PERIOD_HOURS_24)
    eqs_7d = get_earthquakes_in_period(cursor, days=SHORT_TERM_PERIOD_DAYS)
    eqs_30d = get_earthquakes_in_period(cursor, days=LONG_TERM_PERIOD_DAYS)


    # Belirli büyüklük eşiklerinin üzerindeki depremleri sayan yardımcı fonksiyon
    def count_by_magnitude(eq_list, threshold):
        return sum(1 for eq in eq_list if eq['buyukluk'] is not None and eq['buyukluk'] >= threshold)

    results['count_m2_6h'] = count_by_magnitude(eqs_6h, MAGNITUDE_THRESHOLD_MICRO)
    results['count_m3_6h'] = count_by_magnitude(eqs_6h, MAGNITUDE_THRESHOLD_MODERATE)
    results['count_m4_6h'] = count_by_magnitude(eqs_6h, MAGNITUDE_THRESHOLD_STRONG)
    results['count_m5_6h'] = count_by_magnitude(eqs_6h, MAGNITUDE_THRESHOLD_LARGER)

    results['count_m2_24h'] = count_by_magnitude(eqs_24h, MAGNITUDE_THRESHOLD_MICRO)
    results['count_m3_24h'] = count_by_magnitude(eqs_24h, MAGNITUDE_THRESHOLD_MODERATE)
    results['count_m4_24h'] = count_by_magnitude(eqs_24h, MAGNITUDE_THRESHOLD_STRONG)
    results['count_m5_24h'] = count_by_magnitude(eqs_24h, MAGNITUDE_THRESHOLD_LARGER)

    results['count_m3_7d'] = count_by_magnitude(eqs_7d, MAGNITUDE_THRESHOLD_MODERATE)
    results['count_m4_7d'] = count_by_magnitude(eqs_7d, MAGNITUDE_THRESHOLD_STRONG)
    results['count_m5_7d'] = count_by_magnitude(eqs_7d, MAGNITUDE_THRESHOLD_LARGER)

    results['count_m3_30d'] = count_by_magnitude(eqs_30d, MAGNITUDE_THRESHOLD_MODERATE)
    results['count_m4_30d'] = count_by_magnitude(eqs_30d, MAGNITUDE_THRESHOLD_STRONG)
    results['count_m5_30d'] = count_by_magnitude(eqs_30d, MAGNITUDE_THRESHOLD_LARGER)


    print(f"Son {RECENT_PERIOD_HOURS_6} saat içinde: M>=2.0: {results['count_m2_6h']}, M>=3.0: {results['count_m3_6h']}, M>=4.0: {results['count_m4_6h']}, M>=5.0: {results['count_m5_6h']}")
    print(f"Son {RECENT_PERIOD_HOURS_24} saat içinde: M>=2.0: {results['count_m2_24h']}, M>=3.0: {results['count_m3_24h']}, M>=4.0: {results['count_m4_24h']}, M>=5.0: {results['count_m5_24h']}")
    print(f"Son {SHORT_TERM_PERIOD_DAYS} gün içinde: M>=3.0: {results['count_m3_7d']}, M>=4.0: {results['count_m4_7d']}, M>=5.0: {results['count_m5_7d']}")
    print(f"Son {LONG_TERM_PERIOD_DAYS} gün içinde: M>=3.0: {results['count_m3_30d']}, M>=4.0: {results['count_m4_30d']}, M>=5.0: {results['count_m5_30d']}")


    # Yorumlama (Basit Kılavuz - Bilimsel Tahmin Değildir!)
    comment = "Yeterli veri yok veya yorum yapılamadı."
    if results['count_m4_6h'] > 0 or results['count_m4_24h'] > 0:
         comment = f"Son 24 saat içinde {MAGNITUDE_THRESHOLD_STRONG:.1f} ve üzeri büyüklükte deprem/depremler meydana geldi. Bu büyüklükteki aktivite dikkat çekicidir."
    elif results['count_m3_6h'] > 0 or results['count_m3_24h'] > 0:
         comment = f"Son 24 saat içinde {MAGNITUDE_THRESHOLD_MODERATE:.1f} ve üzeri büyüklükte deprem/depremler meydana geldi. Orta düzey aktivite."
    else:
         comment = f"Son 24 saat içinde {MAGNITUDE_THRESHOLD_MODERATE:.1f} üzeri büyüklükte deprem tespit edilmedi."

    results['comment'] = comment
    print(f"Yorum: {comment}")
    print("--- Analiz Sonu ---")
    return results


def calculate_b_value(earthquake_list):
    """
    Verilen deprem listesi için Gutenberg-Richter b-değerini hesaplar (Basit Maksimum Olabilirlik Yöntemi).
    Güvenilir hesaplama için yeterli sayıda deprem olmalıdır ve katalog tamamlılığı önemlidir.
    Sonuçları dictionary olarak döndürür.
    """
    results = {'b_value': None, 'mc': None, 'earthquake_count': len(earthquake_list)}

    # Sadece büyüklüğü olan depremleri al ve float'a çevir
    magnitudes = [eq['buyukluk'] for eq in earthquake_list if eq['buyukluk'] is not None]
    # Veritabanından gelen değerlerin zaten float olduğunu varsayıyoruz, string dönüşümüne gerek yok.
    # Eğer hala string geliyorsa, deprem_cek.py'deki dönüşümü kontrol edin.

    if not magnitudes or len(magnitudes) < MIN_EQ_FOR_B_VALUE:
        print(f"B-değeri hesaplamak için yeterli deprem yok (min {MIN_EQ_FOR_B_VALUE} gerekli, {len(magnitudes)} bulundu).")
        return results

    # Katalog tamamlılığı büyüklüğü (Mc) - En küçük büyüklük + 0.05 (basit yaklaşım)
    # Daha doğru Mc hesaplama yöntemleri vardır.
    mc = min(magnitudes) + 0.05 if magnitudes else 0
    results['mc'] = mc

    # Ortalama büyüklük
    average_magnitude = sum(magnitudes) / len(magnitudes)

    # B-değeri formülü (Maksimum Olabilirlik Tahmini)
    # b = log10(e) / (ortalama_buyukluk - Mc)
    # log10(e) yaklaşık 0.434
    if average_magnitude > mc:
        b_value = 0.434 / (average_magnitude - mc)
        results['b_value'] = b_value
        print(f"Hesaplanan b-değeri: {b_value:.2f} (Mc: {mc:.2f}, Deprem Sayısı: {len(magnitudes)})")
    else:
        print("B-değeri hesaplama hatası: Ortalama büyüklük Mc'den büyük olmalı.")

    return results


def analyze_b_value_trend(cursor):
    """
    Farklı zaman pencereleri için b-değerini hesaplar ve sonuçları dictionary olarak döndürür.
    """
    print("\n--- B-Değeri Analizi ---")
    results = {}

    # Farklı zaman pencereleri için depremleri çek
    eqs_7d = get_earthquakes_in_period(cursor, days=SHORT_TERM_PERIOD_DAYS)
    eqs_30d = get_earthquakes_in_period(cursor, days=LONG_TERM_PERIOD_DAYS)
    eqs_90d = get_earthquakes_in_period(cursor, days=LONGER_TERM_DAYS)

    b_7d_results = calculate_b_value(eqs_7d)
    b_30d_results = calculate_b_value(eqs_30d)
    b_90d_results = calculate_b_value(eqs_90d)

    results['b_7d'] = b_7d_results
    results['b_30d'] = b_30d_results
    results['b_90d'] = b_90d_results

    # Yorumlama (Çok Dikkatli Olun! B-değeri yorumu karmaşıktır ve tek başına anlamı sınırlıdır.)
    comment = "Yeterli veri yok veya b-değeri yorumu yapılamadı."
    b_7d = b_7d_results['b_value']
    b_30d = b_30d_results['b_value']

    if b_7d is not None and b_30d is not None:
        if b_7d < b_30d * 0.9: # Son 7 gün b-değeri son 30 gün b-değerinden %10 düşükse
             comment = "Son 7 günün b-değeri, son 30 günün b-değerine göre düşük görünüyor. (Dikkatli yorumlayın!)"
        elif b_7d > b_30d * 1.1: # Son 7 gün b-değeri son 30 gün b-değerinden %10 yüksekse
             comment = "Son 7 günün b-değeri, son 30 günün b-değerine göre yüksek görünüyor."
        else:
             comment = "B-değeri, farklı zaman pencerelerinde nispeten stabil görünüyor."

    results['comment'] = comment
    print(f"Yorum: {comment}")
    print("--- Analiz Sonu ---")
    return results


def push_to_website_repo(analysis_json_file_path):
    """
    Analiz sonuçları JSON dosyasını web sitesi reposuna klonlar, günceller ve push eder.
    """
    print("\n--- Analiz sonuçlarını Web Sitesi Reposuna Yüklüyor ---")

    if not WEBSITE_REPO_URL:
        print("[HATA] WEBSITE_REPO_URL ortam değişkeni ayarlanmamış. GitHub'a push yapılmayacak.")
        return

    # 1. Web sitesi reposunu klonla (eğer daha önce klonlanmadıysa)
    if not os.path.exists(WEBSITE_REPO_CLONE_DIR):
        print(f"Web sitesi reposunu klonluyor: {WEBSITE_REPO_URL} -> {WEBSITE_REPO_CLONE_DIR}")
        try:
            # Git klonlama komutu
            # Yetkilendirme için SSH veya PAT kullanılacak.
            # Railway ortamında SSH_PRIVATE_KEY veya GITHUB_PAT değişkenleri ayarlanmalı.
            # Eğer SSH kullanıyorsanız, GIT_SSH_COMMAND ortam değişkenini ayarlamanız gerekebilir.
            # Basitlik adına, PAT kullanıyorsanız URL'ye ekleyebilirsiniz (güvenlik riskine dikkat!).
            # SSH için daha sağlam bir yöntem:
            git_command = ['git', 'clone', WEBSITE_REPO_URL, WEBSITE_REPO_CLONE_DIR]
            env_vars = os.environ.copy() # Mevcut ortam değişkenlerini kopyala

            # SSH Private Key kullanılıyorsa GIT_SSH_COMMAND ayarla
            if 'SSH_PRIVATE_KEY' in env_vars:
                 # Private key'i geçici bir dosyaya yaz
                 ssh_key_path = '/tmp/railway_ssh_key' # Geçici dosya yolu
                 with open(ssh_key_path, 'w') as f:
                      f.write(env_vars['SSH_PRIVATE_KEY'])
                 os.chmod(ssh_key_path, 0o600) # Sadece dosya sahibi okuyup yazabilsin

                 # GIT_SSH_COMMAND'ı ayarlayarak bu key'i kullanmasını sağla
                 env_vars['GIT_SSH_COMMAND'] = f'ssh -i {ssh_key_path} -o StrictHostKeyChecking=no'
                 print("SSH Private Key ortamı ayarlandı.")
                 # SSH URL formatı kullanıldığından emin olun (git@github.com:...)
                 if not WEBSITE_REPO_URL.startswith('git@'):
                      print("[UYARI] SSH_PRIVATE_KEY ayarlı ancak WEBSITE_REPO_URL SSH formatında değil. Lütfen kontrol edin.")


            # PAT kullanılıyorsa URL'yi PAT ile güncelle (DİKKAT: Güvenlik Riski!)
            # Daha güvenli yöntemler olsa da, basitlik için bu gösterilebilir.
            # Alternatif olarak, Git Credential Helper kullanmak daha iyidir.
            # Bu basit örnekte PAT'ı URL'ye eklemeyi göstermeyelim, SSH yöntemini odaklanalım.
            # Eğer PAT kullanıyorsanız, Railway'in Git Credential Helper'ı otomatik ayarlamasını umabilirsiniz
            # veya kendiniz ayarlamanız gerekir.
            # En basiti, PAT'ı sadece push sırasında kullanmaktır:
            # git push https://<PAT>@github.com/...

            # Klonlama komutunu çalıştır
            subprocess.run(git_command, check=True, capture_output=True, text=True, env=env_vars) # env ile ortam değişkenlerini geçir
            print("Klonlama başarılı.")

            # Geçici SSH key dosyasını temizle (varsa)
            if 'SSH_PRIVATE_KEY' in env_vars and os.path.exists(ssh_key_path):
                 os.remove(ssh_key_path)
                 print("Geçici SSH key dosyası temizlendi.")


        except subprocess.CalledProcessError as e:
            print(f"[HATA] Web sitesi reposunu klonlarken hata oluştu: {e.stderr}")
            print("Yükleme iptal edildi.")
            # Geçici SSH key dosyasını temizle (hata olsa bile)
            ssh_key_path = '/tmp/railway_ssh_key'
            if 'SSH_PRIVATE_KEY' in os.environ and os.path.exists(ssh_key_path):
                 os.remove(ssh_key_path)
            return # Hata durumunda fonksiyondan çık
        except FileNotFoundError:
             print("[HATA] Git komutu bulunamadı. Railway ortamında Git kurulu olmayabilir.")
             print("Yükleme iptal edildi.")
             return
        except Exception as e:
            print(f"[HATA] Klonlama sırasında beklenmedik hata: {e}")
            print("Yükleme iptal edildi.")
            return
    else:
        print("Web sitesi reposu zaten klonlanmış.")
        # Klonlanmış repoyu en son hale getir (pull)
        print("Klonlanmış repoyu güncelliyor (git pull)...")
        try:
            # Klonlanmış repo dizinine geç
            os.chdir(WEBSITE_REPO_CLONE_DIR)
            # Yetkilendirme için yine SSH veya PAT ayarları gerekebilir
            git_command_pull = ['git', 'pull', 'origin', os.environ.get('RAILWAY_GIT_BRANCH', 'main')]
            env_vars = os.environ.copy()
            ssh_key_path = '/tmp/railway_ssh_key' # Geçici dosya yolu
            if 'SSH_PRIVATE_KEY' in env_vars:
                 with open(ssh_key_path, 'w') as f:
                      f.write(env_vars['SSH_PRIVATE_KEY'])
                 os.chmod(ssh_key_path, 0o600)
                 env_vars['GIT_SSH_COMMAND'] = f'ssh -i {ssh_key_path} -o StrictHostKeyChecking=no'

            subprocess.run(git_command_pull, check=True, capture_output=True, text=True, env=env_vars)
            print("Repo güncellendi.")
            # Geçici SSH key dosyasını temizle (varsa)
            if 'SSH_PRIVATE_KEY' in env_vars and os.path.exists(ssh_key_path):
                 os.remove(ssh_key_path)
            # Tekrar scriptin çalıştığı ana dizine dön
            os.chdir('/app') # Railway'de varsayılan çalışma dizini /app varsayımı
        except subprocess.CalledProcessError as e:
            print(f"[HATA] Klonlanmış repoyu güncellerken hata oluştu: {e.stderr}")
            # Hata olsa bile devam edebiliriz, belki sadece yeni dosyayı ekleyip push ederiz.
            # Geçici SSH key dosyasını temizle (hata olsa bile)
            ssh_key_path = '/tmp/railway_ssh_key'
            if 'SSH_PRIVATE_KEY' in os.environ and os.path.exists(ssh_key_path):
                 os.remove(ssh_key_path)
            # return # Güncelleme hatası push'u engellemesin diye return kaldırıldı
        except Exception as e:
            print(f"[HATA] Repo güncelleme sırasında beklenmedik hata: {e}")
            # Geçici SSH key dosyasını temizle (hata olsa bile)
            ssh_key_path = '/tmp/railway_ssh_key'
            if 'SSH_PRIVATE_KEY' in os.environ and os.path.exists(ssh_key_path):
                 os.remove(ssh_key_path)
            # return # Güncelleme hatası push'u engellemesin diye return kaldırıldı
        finally:
             # İşlem bitince tekrar scriptin çalıştığı ana dizine dönmek iyi bir pratiktir.
             try:
                 os.chdir('/app')
             except Exception as e:
                 print(f"[UYARI] Ana dizine dönülürken hata: {e}")


    # 2. Oluşturulan JSON dosyasını klonlanmış repo klasörüne kopyala
    source_json_path = analysis_json_file_path # Scriptin oluşturduğu JSON dosyası (/app/analysis_results.json)
    destination_json_path = os.path.join(WEBSITE_REPO_CLONE_DIR, ANALYSIS_JSON_FILE_NAME) # Klonlanmış repodaki hedef yer

    print(f"'{source_json_path}' dosyasını '{destination_json_path}' konumuna kopyalıyor...")
    try:
        shutil.copyfile(source_json_path, destination_json_path)
        print("Kopyalama başarılı.")
    except FileNotFoundError:
        print(f"[HATA] Kopyalanacak dosya bulunamadı: {source_json_path}")
        print("Yükleme iptal edildi.")
        return
    except Exception as e:
        print(f"[HATA] Dosya kopyalama sırasında beklenmedik hata: {e}")
        print("Yükleme iptal edildi.")
        return


    # 3. Klonlanmış repo dizininde Git komutlarını çalıştır
    print("Git komutlarını çalıştırıyor...")
    try:
        # Klonlanmış repo dizinine geç
        os.chdir(WEBSITE_REPO_CLONE_DIR)

        # Değişiklikleri ekle
        subprocess.run(['git', 'add', ANALYSIS_JSON_FILE_NAME], check=True, capture_output=True, text=True)
        print(f"'{ANALYSIS_JSON_FILE_NAME}' Git'e eklendi.")

        # Değişiklik var mı kontrol et (commit etmeden önce)
        status_check = subprocess.run(['git', 'status', '--porcelain'], check=True, capture_output=True, text=True)
        if status_check.stdout.strip(): # Eğer çıktıda bir şey varsa değişiklik var demektir
            # Değişiklikleri commit et
            commit_message = f"Güncel deprem analizi sonuçları: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            subprocess.run(['git', 'commit', '-m', commit_message], check=True, capture_output=True, text=True)
            print("Değişiklikler commit edildi.")

            # GitHub'a push etme
            # Yetkilendirme ayarları Railway'de yapılacak.
            # os.environ.get('RAILWAY_GIT_BRANCH', 'main') Railway'in deploy ettiği dalı verir, genellikle main veya master
            git_push_command = ['git', 'push', 'origin', os.environ.get('RAILWAY_GIT_BRANCH', 'main')]
            env_vars = os.environ.copy()
            ssh_key_path = '/tmp/railway_ssh_key' # Geçici dosya yolu
            if 'SSH_PRIVATE_KEY' in env_vars:
                 with open(ssh_key_path, 'w') as f:
                      f.write(env_vars['SSH_PRIVATE_KEY'])
                 os.chmod(ssh_key_path, 0o600)
                 env_vars['GIT_SSH_COMMAND'] = f'ssh -i {ssh_key_path} -o StrictHostKeyChecking=no'

            # PAT kullanılıyorsa push URL'sini ayarlayın (DİKKAT: Güvenlik Riski!)
            # Eğer PAT kullanıyorsanız ve SSH kullanmıyorsanız:
            elif 'GITHUB_PAT' in env_vars and WEBSITE_REPO_URL.startswith('https://'):
                # URL'yi PAT ile yeniden yaz
                parsed_url = WEBSITE_REPO_URL.replace('https://', f'https://{env_vars["GITHUB_PAT"]}@')
                git_push_command = ['git', 'push', parsed_url, os.environ.get('RAILWAY_GIT_BRANCH', 'main')]
                print("PAT ile push URL'si ayarlandı.")


            subprocess.run(git_push_command, check=True, capture_output=True, text=True, env=env_vars)

            print("Değişiklikler Web Sitesi Reposuna başarıyla yüklendi.")

            # Geçici SSH key dosyasını temizle (varsa)
            if 'SSH_PRIVATE_KEY' in env_vars and os.path.exists(ssh_key_path):
                 os.remove(ssh_key_path)


        except subprocess.CalledProcessError as e:
            print(f"[HATA] Git komutu çalıştırılırken hata oluştu: {e}")
            print(f"Stdout: {e.stdout}")
            print(f"Stderr: {e.stderr}")
            print("Web Sitesi Reposuna yükleme başarısız.")
            # Geçici SSH key dosyasını temizle (hata olsa bile)
            ssh_key_path = '/tmp/railway_ssh_key'
            if 'SSH_PRIVATE_KEY' in os.environ and os.path.exists(ssh_key_path):
                 os.remove(ssh_key_path)

        except FileNotFoundError:
             print("[HATA] Git komutu bulunamadı. Railway ortamında Git kurulu olmayabilir veya PATH ayarı eksik olabilir.")
             print("Web Sitesi Reposuna yükleme başarısız.")
        except Exception as e:
            print(f"[HATA] Web Sitesi Reposuna yükleme sırasında beklenmedik hata: {e}")
            print("Web Sitesi Reposuna yükleme başarısız.")
        finally:
            # İşlem bitince tekrar scriptin çalıştığı ana dizine dönmek iyi bir pratiktir.
            try:
                os.chdir('/app')
            except Exception as e:
                print(f"[UYARI] Ana dizine dönülürken hata: {e}")


    else:
        print("JSON dosyasında değişiklik yok, Web Sitesi Reposuna yükleme yapılmadı.")

    print("--- Yükleme Sonu ---")


# --- Ana Analiz Bloğu ---
if __name__ == "__main__":
    print(f"Veritabanı ({DATABASE_PATH}) üzerinden Marmara Deprem Trafiği Analizi Başladı...")

    conn = None # Bağlantıyı başlangıçta None yapalım
    cursor = None
    try:
        # Veritabanı bağlantısını aç
        conn, cursor = get_db_connection()
        if conn is None or cursor is None:
            raise Exception("Veritabanı bağlantısı kurulamadı.") # Bağlantı hatası olursa istisna fırlat

        # Analizleri çalıştır ve sonuçları al
        analysis_results = {}
        analysis_results['seismic_rate'] = analyze_seismic_rate(cursor)
        analysis_results['clustering'] = analyze_spatial_clustering_advanced(cursor)
        analysis_results['magnitude_distribution'] = analyze_magnitude_distribution(cursor)
        analysis_results['b_value'] = analyze_b_value_trend(cursor)

        # Analiz zamanını ekleyin
        analysis_results['last_updated'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # Sonuçları JSON dosyasına yaz
        output_json_file_path = ANALYSIS_JSON_FILE_PATH # /app/analysis_results.json
        print(f"\nAnaliz sonuçları '{output_json_file_path}' dosyasına yazılıyor...")
        with open(output_json_file_path, 'w', encoding='utf-8') as f:
            json.dump(analysis_results, f, ensure_ascii=False, indent=4)
        print(f"Analiz sonuçları '{output_json_file_path}' dosyasına kaydedildi.")

        # Analiz sonuçlarını Web Sitesi Reposuna push et
        push_to_website_repo(output_json_file_path)


        print("\nMarmara Deprem Trafiği Analizi Tamamlandı.")

    except Exception as e:
        print(f"[HATA] Genel hata oluştu: {e}")
    finally:
        # Veritabanı bağlantısını kapat
        if conn: # Bağlantı kurulduysa kapat
            conn.close()
            print("Veritabanı bağlantısı kapatıldı.")

