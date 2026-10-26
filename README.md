# ⌨️ TAŞAK - Oto Düzeltici[cite: 13]

Python ile geliştirilmiş, arka planda çalışan ve siz yazı yazarken klavye hatalarını anında düzelten, akıllı ve arayüzlü bir Windows klavye asistanıdır[cite: 13]. 

## 🌟 Özellikler

- **Akıllı Oto-Düzeltme:** Kelimeleri yazarken belirlediğiniz sözlüğe veya yerel Türkçe kelime listesine göre anında düzeltir[cite: 13].
- **TDK Entegrasyonu:** Sözlükte bulunmayan kelimeleri internet üzerinden anlık olarak TDK'ya sorar ve doğrusuyla değiştirir[cite: 13].
- **LoL Modu:** Bastığınız kelimeleri aralıklı ve büyük harfle yazar (Örn: `M  E  R  H  A  B  A`)[cite: 13].
- **Otomatik Noktalama:** Enter tuşuna bastığınızda cümle sonuna otomatik olarak nokta koyar[cite: 13].
- **Gelişmiş Arayüz (GUI):** Karanlık tema destekli; sözlük yönetimi, ayarlar, istatistikler ve canlı kayıt (log) sunan Tkinter tabanlı kontrol paneli[cite: 13].

## ⌨️ Kısayollar

Oyun oynarken veya yazışırken uygulamayı arayüze girmeden klavye üzerinden yönetebilirsiniz[cite: 13]:

- **`F8`** : Oto-düzeltmeyi Aç / Kapat[cite: 13]
- **`F9`** : LoL Modunu Aç / Kapat[cite: 13]
- **`F7`** : Son TDK veya Liste düzeltmesini geri al (Geri alınan kelime "yoksayılanlar" listesine eklenir ve bir daha dokunulmaz)[cite: 13]

## 🛠️ Sistem Gereksinimleri

- İşletim Sistemi: Sadece **Windows**[cite: 13]
- Python 3.x
- Harici Liste: Uygulamanın yanında `turkce_kelime_listesi.txt` bulunması tavsiye edilir[cite: 13].

## ⚙️ Kurulum ve Çalıştırma

Klavye dinleme özellikleri için gerekli olan `keyboard` kütüphanesini yükleyerek uygulamayı başlatabilirsiniz[cite: 13]:

```bash
pip install keyboard
python tasak.py
