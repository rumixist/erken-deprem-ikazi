import sqlite3
import datetime
import math
import statistics # Standart sapma için
from collections import defaultdict

# Veritabanı dosyası adı
DATABASE_NAME = 'earthquakes.db'

# Analiz için zaman pencereleri (saat cinsinden)
RECENT_PERIOD_HOURS_6 = 6
RECENT_PERIOD_HOURS_24 = 24
RECENT_PERIOD_DAYS = 1
SHORT_TERM_PERIOD_DAYS = 7
LONG_TERM_PERIOD_DAYS = 30 # Referans için

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

def get_earthquakes_in_period(cursor, hours=None, days=None):
    """
    Veritabanından belirtilen zaman dilimindeki depremleri çeker.
    hours veya days parametrelerinden biri kullanılmalıdır.
    """
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
        # Deprem verilerini (tarih, enlem, boylam, derinlik, tip, buyukluk) tuple listesi olarak döndürür
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
    ve uzun vadeli ortalama ile karşılaştırır.
    """
    print("\n--- Sismik Aktivite Hızı Analizi ---")

    # Farklı zaman pencereleri için depremleri çek
    recent_eqs_6h = get_earthquakes_in_period(cursor, hours=RECENT_PERIOD_HOURS_6)
    recent_eqs_24h = get_earthquakes_in_period(cursor, hours=RECENT_PERIOD_HOURS_24)
    short_term_eqs_7d = get_earthquakes_in_period(cursor, days=SHORT_TERM_PERIOD_DAYS)
    long_term_eqs_30d = get_earthquakes_in_period(cursor, days=LONG_TERM_PERIOD_DAYS)

    count_6h = len(recent_eqs_6h)
    count_24h = len(recent_eqs_24h)
    count_7d = len(short_term_eqs_7d)
    count_30d = len(long_term_eqs_30d)

    print(f"Son {RECENT_PERIOD_HOURS_6} saat içindeki deprem sayısı: {count_6h}")
    print(f"Son {RECENT_PERIOD_HOURS_24} saat ({RECENT_PERIOD_DAYS} gün) içindeki deprem sayısı: {count_24h}")
    print(f"Son {SHORT_TERM_PERIOD_DAYS} gün içindeki deprem sayısı: {count_7d}")
    print(f"Son {LONG_TERM_PERIOD_DAYS} gün içindeki toplam deprem sayısı: {count_30d}")

    # Uzun vadeli ortalama günlük deprem sayısı
    average_daily_long_term = count_30d / LONG_TERM_PERIOD_DAYS if LONG_TERM_PERIOD_DAYS > 0 else 0
    # Uzun vadeli ortalama saatlik deprem sayısı
    average_hourly_long_term = count_30d / (LONG_TERM_PERIOD_DAYS * 24) if LONG_TERM_PERIOD_DAYS > 0 else 0


    print(f"Son {LONG_TERM_PERIOD_DAYS} günün ortalama günlük deprem sayısı: {average_daily_long_term:.2f}")
    print(f"Son {LONG_TERM_PERIOD_DAYS} günün ortalama saatlik deprem sayısı: {average_hourly_long_term:.2f}")

    # Kısa vadeli aktiviteyi uzun vadeli ortalama ile karşılaştır
    print("\nHız Oranları (Uzun Vadeli Ortalamaya Göre):")
    if average_hourly_long_term > 0.1: # Ortalamanın çok düşük olmaması için kontrol
        rate_ratio_6h = count_6h / (average_hourly_long_term * RECENT_PERIOD_HOURS_6)
        print(f" - Son {RECENT_PERIOD_HOURS_6} saat aktivitesi, uzun vadeli ortalamanın {rate_ratio_6h:.2f} katı.")

        rate_ratio_24h = count_24h / (average_daily_long_term) if average_daily_long_term > 0.1 else float('inf') # Günlük ortalamaya göre
        print(f" - Son {RECENT_PERIOD_HOURS_24} saat aktivitesi, uzun vadeli günlük ortalamanın {rate_ratio_24h:.2f} katı.")
    else:
        print("Uzun vadeli ortalama çok düşük, hız oranları anlamlı değil.")


    # Yorumlama (Gelişmiş Kılavuz - İstatistiksel Anomaliye Yaklaşım)
    # Basit bir istatistiksel anomali tespiti (Poisson dağılımı varsayımıyla yapılabilir ama burada ortalama ve std sapma kullanacağız)
    # Daha doğru istatistiksel analizler için daha fazla veri ve uygun dağılım modeli gerekir.

    if count_30d >= 30: # Standart sapma hesaplamak için yeterli veri olduğunu varsayalım
        # Günlük deprem sayılarını hesapla (son 30 gün için)
        daily_counts = defaultdict(int)
        for eq in long_term_eqs_30d:
            # Tarih stringini datetime objesine çevir ve sadece tarihi al
            eq_date = datetime.datetime.strptime(eq[0], '%Y-%m-%d %H:%M:%S').date()
            daily_counts[eq_date] += 1

        # Günlük sayıların listesi
        counts_list = list(daily_counts.values())

        if len(counts_list) > 1: # Standart sapma hesaplamak için en az 2 değer olmalı
            mean_daily = statistics.mean(counts_list)
            stdev_daily = statistics.stdev(counts_list)

            print(f"\nSon {LONG_TERM_PERIOD_DAYS} günün günlük deprem sayısı ortalaması: {mean_daily:.2f}, Standart Sapması: {stdev_daily:.2f}")

            # Son 1 gün sayısının ortalamadan kaç standart sapma uzakta olduğunu kontrol et
            if stdev_daily > 0.1: # Standart sapma sıfıra yakınsa anlamlı değil
                z_score_24h = (count_24h - mean_daily) / stdev_daily
                print(f"Son {RECENT_PERIOD_HOURS_24} saat sayısı, ortalamadan {z_score_24h:.2f} standart sapma uzakta.")

                # Yorum (İstatistiksel Anomaliye Dayalı - Dikkatli Olun!)
                print("\nYorum (İstatistiksel Anomali Göstergesi):")
                if z_score_24h > 2: # Genellikle 2 veya 3 standart sapma anomali eşiği olarak kullanılır
                    print("- Son 24 saatteki sismik aktivite, istatistiksel olarak belirgin bir artış gösteriyor (Anomali!). Bu durum yakından izlenmelidir.")
                elif z_score_24h < -2:
                     print("- Son 24 saatteki sismik aktivite, istatistiksel olarak belirgin bir düşüş gösteriyor.")
                else:
                     print("- Son 24 saatteki sismik aktivite, istatistiksel olarak normal aralıkta görünüyor.")
            else:
                print("Günlük deprem sayısı varyasyonu çok düşük, istatistiksel anomali analizi yapılamadı.")
        else:
            print("Son 30 günde sadece 1 gün deprem oldu, istatistiksel anomali analizi yapılamadı.")
    else:
        print("Standart sapma hesaplamak için son 30 günde yeterli veri yok (min 30 gün ve >1 gün aktivite önerilir).")

    print("--- Analiz Sonu ---")


def analyze_spatial_clustering_advanced(cursor):
    """
    Mekansal kümelenmeleri daha detaylı tespit eder ve raporlar.
    Basit bir gruplama yaklaşımı kullanır.
    """
    print("\n--- Mekansal Kümeleme Analizi ---")

    # Son RECENT_PERIOD_HOURS_24 (1 gün) içindeki depremleri al
    recent_eqs = get_earthquakes_in_period(cursor, hours=RECENT_PERIOD_HOURS_24)

    if not recent_eqs:
        print(f"Son {RECENT_PERIOD_HOURS_24} saat içinde Marmara'da deprem kaydı bulunamadı.")
        print("--- Analiz Sonu ---")
        return

    print(f"Son {RECENT_PERIOD_HOURS_24} saat içindeki {len(recent_eqs)} deprem için mekansal kümeleme analizi yapılıyor (Eşik: {SPATIAL_CLUSTER_DISTANCE_KM} km)...")

    # Depremleri işlenmiş olarak işaretlemek için bir set
    processed_indices = set()
    clusters = [] # Tespit edilen kümeleri saklamak için liste

    # Her deprem için komşularını bul ve kümeler oluştur
    for i in range(len(recent_eqs)):
        if i in processed_indices:
            continue # Zaten bir kümenin parçası olarak işlenmiş

        # Yeni bir küme başlat
        current_cluster = [i] # Mevcut depremi kümeye ekle
        processed_indices.add(i)
        to_process = [i] # İşlenecek depremler listesi (genişleyen küme için)

        # Küme etrafındaki komşuları bulmak için genişle
        while to_process:
            current_idx = to_process.pop(0) # İşlenecek ilk depremi al
            current_eq = recent_eqs[current_idx]
            current_lat, current_lon = current_eq[1], current_eq[2]

            # Mevcut depremin etrafındaki komşuları ara
            for j in range(len(recent_eqs)):
                if j not in processed_indices: # Henüz işlenmemiş depremlere bak
                    other_eq = recent_eqs[j]
                    other_lat, other_lon = other_eq[1], other_eq[2]

                    dist = haversine_distance(current_lat, current_lon, other_lat, other_lon)

                    if dist <= SPATIAL_CLUSTER_DISTANCE_KM:
                        # Komşuyu kümeye ekle ve işlenmiş olarak işaretle
                        current_cluster.append(j)
                        processed_indices.add(j)
                        to_process.append(j) # Yeni komşuyu işlenecekler listesine ekle ki onun da komşuları bulunsun

        # Küme oluşturulduysa listeye ekle
        if len(current_cluster) > 1: # Tek depremli kümeleri (gürültü) dahil etme
            clusters.append(current_cluster)

    # Tespit edilen kümeleri raporla
    if clusters:
        print(f"\nToplam {len(clusters)} adet mekansal küme tespit edildi (Son {RECENT_PERIOD_HOURS_24} saat, Eşik: {SPATIAL_CLUSTER_DISTANCE_KM} km, Min Küme Boyutu: 2 deprem).")
        for k, cluster_indices in enumerate(clusters):
            print(f"\n--- Küme #{k+1} ({len(cluster_indices)} Deprem) ---")
            # Kümedeki depremlerin merkezini (ortalama enlem/boylam) ve en büyük depremi bul
            cluster_lats = [recent_eqs[i][1] for i in cluster_indices]
            cluster_lons = [recent_eqs[i][2] for i in cluster_indices]
            avg_lat = sum(cluster_lats) / len(cluster_lats)
            avg_lon = sum(cluster_lons) / len(cluster_lons)

            max_mag_eq = None
            for idx in cluster_indices:
                eq = recent_eqs[idx]
                if max_mag_eq is None or eq[5] > max_mag_eq[5]:
                    max_mag_eq = eq

            print(f" - Ortalama Konum: Enlem {avg_lat:.4f}, Boylam {avg_lon:.4f}")
            if max_mag_eq:
                 print(f" - Kümedeki En Büyük Deprem: Tarih: {max_mag_eq[0]}, Büyüklük: {max_mag_eq[5]:.1f}, Derinlik: {max_mag_eq[3]}km")

            # Kümedeki depremleri listele (isteğe bağlı, çok fazla olabilir)
            # print(" - Depremler:")
            # for idx in cluster_indices:
            #     eq = recent_eqs[idx]
            #     print(f"   - Tarih: {eq[0]}, Büyüklük: {eq[5]:.1f}, Konum: {eq[1]:.4f}, {eq[2]:.4f}")

    else:
        print(f"Son {RECENT_PERIOD_HOURS_24} saat içinde belirtilen mesafe eşiğinde ({SPATIAL_CLUSTER_DISTANCE_KM} km) belirgin bir mekansal kümelenme tespit edilmedi.")

    print("--- Analiz Sonu ---")


def analyze_magnitude_distribution(cursor):
    """
    Farklı zaman pencereleri için büyüklük dağılımını analiz eder.
    """
    print("\n--- Büyüklük Dağılımı Analizi ---")

    # Farklı zaman pencereleri için depremleri çek
    eqs_6h = get_earthquakes_in_period(cursor, hours=RECENT_PERIOD_HOURS_6)
    eqs_24h = get_earthquakes_in_period(cursor, hours=RECENT_PERIOD_HOURS_24)
    eqs_7d = get_earthquakes_in_period(cursor, days=SHORT_TERM_PERIOD_DAYS)
    eqs_30d = get_earthquakes_in_period(cursor, days=LONG_TERM_PERIOD_DAYS)


    # Belirli büyüklük eşiklerinin üzerindeki depremleri sayan yardımcı fonksiyon
    def count_by_magnitude(eq_list, threshold):
        return sum(1 for eq in eq_list if eq[5] is not None and eq[5] >= threshold) # buyukluk None olabilir kontrolü

    print(f"Son {RECENT_PERIOD_HOURS_6} saat içinde:")
    print(f" - Büyüklük >= {MAGNITUDE_THRESHOLD_MICRO:.1f} olan deprem sayısı: {count_by_magnitude(eqs_6h, MAGNITUDE_THRESHOLD_MICRO)}")
    print(f" - Büyüklük >= {MAGNITUDE_THRESHOLD_MODERATE:.1f} olan deprem sayısı: {count_by_magnitude(eqs_6h, MAGNITUDE_THRESHOLD_MODERATE)}")
    print(f" - Büyüklük >= {MAGNITUDE_THRESHOLD_STRONG:.1f} olan deprem sayısı: {count_by_magnitude(eqs_6h, MAGNITUDE_THRESHOLD_STRONG)}")
    print(f" - Büyüklük >= {MAGNITUDE_THRESHOLD_LARGER:.1f} olan deprem sayısı: {count_by_magnitude(eqs_6h, MAGNITUDE_THRESHOLD_LARGER)}")

    print(f"\nSon {RECENT_PERIOD_HOURS_24} saat ({RECENT_PERIOD_DAYS} gün) içinde:")
    print(f" - Büyüklük >= {MAGNITUDE_THRESHOLD_MICRO:.1f} olan deprem sayısı: {count_by_magnitude(eqs_24h, MAGNITUDE_THRESHOLD_MICRO)}")
    print(f" - Büyüklük >= {MAGNITUDE_THRESHOLD_MODERATE:.1f} olan deprem sayısı: {count_by_magnitude(eqs_24h, MAGNITUDE_THRESHOLD_MODERATE)}")
    print(f" - Büyüklük >= {MAGNITUDE_THRESHOLD_STRONG:.1f} olan deprem sayısı: {count_by_magnitude(eqs_24h, MAGNITUDE_THRESHOLD_STRONG)}")
    print(f" - Büyüklük >= {MAGNITUDE_THRESHOLD_LARGER:.1f} olan deprem sayısı: {count_by_magnitude(eqs_24h, MAGNITUDE_THRESHOLD_LARGER)}")


    print(f"\nSon {SHORT_TERM_PERIOD_DAYS} gün içinde:")
    print(f" - Büyüklük >= {MAGNITUDE_THRESHOLD_MODERATE:.1f} olan deprem sayısı: {count_by_magnitude(eqs_7d, MAGNITUDE_THRESHOLD_MODERATE)}")
    print(f" - Büyüklük >= {MAGNITUDE_THRESHOLD_STRONG:.1f} olan deprem sayısı: {count_by_magnitude(eqs_7d, MAGNITUDE_THRESHOLD_STRONG)}")
    print(f" - Büyüklük >= {MAGNITUDE_THRESHOLD_LARGER:.1f} olan deprem sayısı: {count_by_magnitude(eqs_7d, MAGNITUDE_THRESHOLD_LARGER)}")

    print(f"\nSon {LONG_TERM_PERIOD_DAYS} gün içinde:")
    print(f" - Büyüklük >= {MAGNITUDE_THRESHOLD_MODERATE:.1f} olan deprem sayısı: {count_by_magnitude(eqs_30d, MAGNITUDE_THRESHOLD_MODERATE)}")
    print(f" - Büyüklük >= {MAGNITUDE_THRESHOLD_STRONG:.1f} olan deprem sayısı: {count_by_magnitude(eqs_30d, MAGNITUDE_THRESHOLD_STRONG)}")
    print(f" - Büyüklük >= {MAGNITUDE_THRESHOLD_LARGER:.1f} olan deprem sayısı: {count_by_magnitude(eqs_30d, MAGNITUDE_THRESHOLD_LARGER)}")


    # Yorumlama (Basit Kılavuz - Bilimsel Tahmin Değildir!)
    print("\nYorum (Büyüklük Dağılımı Göstergesi):")
    if count_by_magnitude(eqs_6h, MAGNITUDE_THRESHOLD_STRONG) > 0 or count_by_magnitude(eqs_24h, MAGNITUDE_THRESHOLD_STRONG) > 0:
         print(f"- Son 24 saat içinde {MAGNITUDE_THRESHOLD_STRONG:.1f} ve üzeri büyüklükte deprem/depremler meydana geldi. Bu büyüklükteki aktivite dikkat çekicidir.")
    elif count_by_magnitude(eqs_6h, MAGNITUDE_THRESHOLD_MODERATE) > 0 or count_by_magnitude(eqs_24h, MAGNITUDE_THRESHOLD_MODERATE) > 0:
         print(f"- Son 24 saat içinde {MAGNITUDE_THRESHOLD_MODERATE:.1f} ve üzeri büyüklükte deprem/depremler meydana geldi. Orta düzey aktivite.")
    else:
         print(f"- Son 24 saat içinde {MAGNITUDE_THRESHOLD_MODERATE:.1f} üzeri büyüklükte deprem tespit edilmedi.")

    print("--- Analiz Sonu ---")


def calculate_b_value(earthquake_list):
    """
    Verilen deprem listesi için Gutenberg-Richter b-değerini hesaplar (Basit Maksimum Olabilirlik Yöntemi).
    Güvenilir hesaplama için yeterli sayıda deprem olmalıdır ve katalog tamamlılığı önemlidir.
    """
    # Sadece büyüklüğü olan depremleri al ve float'a çevir
    magnitudes = [eq[5] for eq in earthquake_list if eq[5] is not None]
    magnitudes = [float(m) for m in magnitudes if isinstance(m, (int, float, str)) and str(m).replace('.', '', 1).isdigit()] # String sayıları da float yap

    if not magnitudes or len(magnitudes) < MIN_EQ_FOR_B_VALUE:
        # print(f"B-değeri hesaplamak için yeterli deprem yok (min {MIN_EQ_FOR_B_VALUE} gerekli, {len(magnitudes)} bulundu).")
        return None, None # Yeterli veri yoksa None döndür

    # Katalog tamamlılığı büyüklüğü (Mc) - En küçük büyüklük + 0.05 (basit yaklaşım)
    # Daha doğru Mc hesaplama yöntemleri vardır.
    mc = min(magnitudes) + 0.05 if magnitudes else 0

    # Ortalama büyüklük
    average_magnitude = sum(magnitudes) / len(magnitudes)

    # B-değeri formülü (Maksimum Olabilirlik Tahmini)
    # b = log10(e) / (ortalama_buyukluk - Mc)
    # log10(e) yaklaşık 0.434
    if average_magnitude > mc:
        b_value = 0.434 / (average_magnitude - mc)
        return b_value, mc
    else:
        # print("B-değeri hesaplama hatası: Ortalama büyüklük Mc'den büyük olmalı.")
        return None, mc


def analyze_b_value_trend(cursor):
    """
    Farklı zaman pencereleri için b-değerini hesaplar ve karşılaştırır.
    """
    print("\n--- B-Değeri Analizi ---")

    # Farklı zaman pencereleri için depremleri çek
    eqs_7d = get_earthquakes_in_period(cursor, days=SHORT_TERM_PERIOD_DAYS)
    eqs_30d = get_earthquakes_in_period(cursor, days=LONG_TERM_PERIOD_DAYS)
    eqs_90d = get_earthquakes_in_period(cursor, days=90) # Daha uzun bir pencere de ekleyelim

    b_7d, mc_7d = calculate_b_value(eqs_7d)
    b_30d, mc_30d = calculate_b_value(eqs_30d)
    b_90d, mc_90d = calculate_b_value(eqs_90d)

    print(f"Son {SHORT_TERM_PERIOD_DAYS} gün için b-değeri: {b_7d:.2f} (Mc: {mc_7d:.2f}, Deprem Sayısı: {len(eqs_7d)})" if b_7d is not None else f"Son {SHORT_TERM_PERIOD_DAYS} gün için b-değeri hesaplanamadı (Yeterli veri yok).")
    print(f"Son {LONG_TERM_PERIOD_DAYS} gün için b-değeri: {b_30d:.2f} (Mc: {mc_30d:.2f}, Deprem Sayısı: {len(eqs_30d)})" if b_30d is not None else f"Son {LONG_TERM_PERIOD_DAYS} gün için b-değeri hesaplanamadı (Yeterli veri yok).")
    print(f"Son 90 gün için b-değeri: {b_90d:.2f} (Mc: {mc_90d:.2f}, Deprem Sayısı: {len(eqs_90d)})" if b_90d is not None else f"Son 90 gün için b-değeri hesaplanamadı (Yeterli veri yok).")

    # Yorumlama (Çok Dikkatli Olun! B-değeri yorumu karmaşıktır ve tek başına anlamı sınırlıdır.)
    print("\nYorum (B-Değeri Göstergesi - Çok Dikkatli Olun!):")
    if b_7d is not None and b_30d is not None and b_7d < b_30d * 0.9: # Son 7 gün b-değeri son 30 gün b-değerinden %10 düşükse
         print("- Son 7 günün b-değeri, son 30 günün b-değerine göre düşük görünüyor. Bu, bazı teorilere göre artan gerilimle ilişkilendirilebilir, ancak tek başına bir tahmin göstergesi değildir ve veri kalitesine duyarlıdır.")
    elif b_7d is not None and b_30d is not None and b_7d > b_30d * 1.1: # Son 7 gün b-değeri son 30 gün b-değerinden %10 yüksekse
         print("- Son 7 günün b-değeri, son 30 günün b-değerine göre yüksek görünüyor. Bu durum genellikle artçı şok dizileri veya düşük gerilimli bölgelerle ilişkilidir.")
    else:
         print("- B-değeri, farklı zaman pencerelerinde nispeten stabil görünüyor veya yeterli veri yok.")

    print("--- Analiz Sonu ---")


# --- Ana Analiz Bloğu ---
if __name__ == "__main__":
    print(f"Veritabanı ({DATABASE_NAME}) üzerinden Marmara Deprem Trafiği Analizi Başladı...")

    try:
        # Veritabanı bağlantısını aç
        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()

        # Analiz fonksiyonlarını çağır
        analyze_seismic_rate(cursor)
        analyze_spatial_clustering_advanced(cursor) # Gelişmiş kümeleme fonksiyonunu çağır
        analyze_magnitude_distribution(cursor)
        analyze_b_value_trend(cursor) # B-değeri analizini çağır

        print("\nMarmara Deprem Trafiği Analizi Tamamlandı.")

    except sqlite3.Error as e:
        print(f"[HATA] Veritabanına bağlanırken hata oluştu: {e}")
    except Exception as e:
        print(f"[HATA] Analiz sırasında beklenmedik bir hata oluştu: {e}")
    finally:
        # Veritabanı bağlantısını kapat
        if 'conn' in locals() and conn:
            conn.close()
            print("Veritabanı bağlantısı kapatıldı.")

