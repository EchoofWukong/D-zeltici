"""
TAŞAK - Oto Düzeltici (arayüzlü sürüm)
Kurulum:  pip install keyboard
Çalıştır: python tasak.py   (sadece Windows)

F8 = Oto-düzeltmeyi aç/kapat
F9 = LoL modunu aç/kapat
F7 = Son TDK düzeltmesini geri al (o kelimeye bir daha dokunmaz)
"""
import collections
import functools
import json
import os
import queue
import threading
import time
import tkinter as tk
import urllib.error
import urllib.parse
import urllib.request
from tkinter import filedialog, ttk, messagebox

import keyboard

# ----------------------------------------------------------------- AYARLAR
BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE, "tasak_ayarlar.json")

VARSAYILAN = {
    "autocorrect": True,
    "lol_mode": False,
    "auto_period": False,   # Enter'a basınca cümle sonuna nokta koy
    "liste": True,          # Kelime listesindeki en yakın kelimeyle düzelt
    "liste_yolu": "",       # boşsa tasak.py'nin yanındaki turkce_kelime_listesi.txt
    "tdk": False,           # Bilinmeyen kelimeleri TDK'ya sorup düzelt (internet, deneysel)
    "yoksay": [],           # F7 ile "dokunma" dediğin kelimeler
    "sozluk": {
        "cok": "çok", "isdi": "iyi", "bişe": "bir şey", "porgram": "program",
        "heme": "hemen", "keliemye": "kelimeye", "gecicek": "geçecek",
        "yapcam": "yapacağım", "yapamsı": "yapması", "başak": "başka",
        "bieşyle": "bir şeyle", "günvceleştşir": "güncelleştir",
        "düzeletemiyor": "düzeltemiyor", "knk": "kanka", "slm": "selam",
        "nbr": "naber",
    },
}

# Tahmin modu için küçük bir temel kelime listesi (sözlüğündeki doğru kelimeler de eklenir)
TEMEL_KELIMELER = {
    "merhaba", "selam", "naber", "nasılsın", "iyiyim", "teşekkürler", "program",
    "bilgisayar", "klavye", "kelime", "yazı", "oyun", "takım", "şampiyon", "hemen",
    "şimdi", "bugün", "yarın", "tamam", "evet", "hayır", "lütfen", "güzel", "başka",
    "çünkü", "ama", "fakat", "ancak", "herkes", "arkadaş", "kanka", "geliyorum",
    "gidiyorum", "yapıyorum", "düşünüyorum", "bekliyorum", "oynuyoruz", "kazandık",
    "kaybettik", "mesaj", "güncelle", "düzelt", "hatalı", "doğru", "yanlış",
}

NOKTALAMA = set(".,!?:;")
LOL_KELIME_ARASI = "    "   # LoL modunda kelimeler arası boşluk (harfler arası 2 boşluk)
TDK_ZAMAN_ASIMI = 0.7       # saniye; internet yavaşsa bu kadar bekleyip vazgeçer
TDK_ONBELLEK = os.path.join(BASE, "tasak_tdk_onbellek.json")
MODIFIERS = {"shift", "right shift", "ctrl", "right ctrl", "alt", "right alt",
             "alt gr", "caps lock", "windows", "left windows", "right windows",
             "num lock", "scroll lock"}


def ayar_yukle():
    cfg = json.loads(json.dumps(VARSAYILAN))
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg.update(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return cfg


def ayar_kaydet(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


# ------------------------------------------------------- TÜRKÇE YARDIMCILAR
def tr_lower(s):
    return s.replace("I", "ı").replace("İ", "i").lower()


def tr_upper(s):
    return s.replace("i", "İ").replace("ı", "I").upper()


def caps_acik():
    try:
        import ctypes
        return bool(ctypes.windll.user32.GetKeyState(0x14) & 1)
    except Exception:
        return False


def buyuklugu_koru(orijinal, hedef):
    """Cok -> Çok, COK -> ÇOK, cok -> çok"""
    if len(orijinal) > 1 and orijinal == tr_upper(orijinal):
        return tr_upper(hedef)
    if orijinal[0] != tr_lower(orijinal[0]):
        return tr_upper(hedef[0]) + hedef[1:]
    return hedef


def mesafe(a, b):
    """Damerau-Levenshtein uzaklığı (harf yer değiştirmesi 1 sayılır)."""
    d = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) + 1):
        d[i][0] = i
    for j in range(len(b) + 1):
        d[0][j] = j
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            m = 0 if a[i - 1] == b[j - 1] else 1
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + m)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[-1][-1]


def guvenli_oneri(yanlis, oneri):
    """TDK önerisi gerçekten bir yazım hatası düzeltmesi mi? Çekimli kelimeleri bozmasın diye sıkı."""
    if not oneri or oneri == yanlis or " " in oneri or oneri[0] != yanlis[0]:
        return False
    if abs(len(oneri) - len(yanlis)) > 2 or mesafe(yanlis, oneri) > 2:
        return False
    # "kelimeyi" -> "kelime", "yapıyorum" -> "yapıyor": ek almış doğru kelimeler, dokunma
    if len(yanlis) > len(oneri) and yanlis.startswith(oneri[:-1]):
        return False
    return True


def tdk_json(url):
    istek = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(istek, timeout=TDK_ZAMAN_ASIMI) as r:
        return json.loads(r.read().decode("utf-8"))


def tdk_oneri_listesi(veri):
    sonuc = []
    if isinstance(veri, list):
        for o in veri:
            if isinstance(o, str):
                sonuc.append(o)
            elif isinstance(o, dict):
                for k in ("madde", "soz", "kelime"):
                    if isinstance(o.get(k), str):
                        sonuc.append(o[k])
                        break
    return [tr_lower(s.strip()) for s in sonuc]


# ------------------------------------------------------ KELİME LİSTESİ MOTORU
SAPKA = str.maketrans("âîû", "aiu")


def norm(w):
    """Karşılaştırma için: küçük harf + şapkasız (rüzgâr -> ruzgar değil, rüzgar)."""
    return tr_lower(w).translate(SAPKA)


# Türkçe Q klavyede komşu tuşlar: bunlar arası hata "daha olası" sayılır (ucuz)
KLAVYE = ["qwertyuıopğü", "asdfghjklşi", "zxcvbnmöç"]
KOMSU = collections.defaultdict(set)
for _r, _sat in enumerate(KLAVYE):
    for _c, _h in enumerate(_sat):
        if _c > 0:
            KOMSU[_h].add(_sat[_c - 1])
        if _c < len(_sat) - 1:
            KOMSU[_h].add(_sat[_c + 1])
        if _r > 0:
            for _k in (_c, _c + 1):          # alt satır yarım tuş kayık: üstündeki iki tuş
                if _k < len(KLAVYE[_r - 1]):
                    KOMSU[_h].add(KLAVYE[_r - 1][_k])
                    KOMSU[KLAVYE[_r - 1][_k]].add(_h)


def agirlikli_mesafe(a, b, sinir):
    """Ağırlıklı Damerau-Levenshtein: ekleme/silme 1, komşu tuş hatası 0.6,
    diğer harf hatası 1, iki harfin yer değiştirmesi 0.6. Sınırı aşarsa erken bırakır."""
    n, m = len(a), len(b)
    if abs(n - m) > sinir:
        return sinir + 1
    onceki2 = None
    onceki = [float(j) for j in range(m + 1)]
    for i in range(1, n + 1):
        simdi = [float(i)] + [0.0] * m
        ai = a[i - 1]
        for j in range(1, m + 1):
            bj = b[j - 1]
            if ai == bj:
                v = onceki[j - 1]
            else:
                v = onceki[j - 1] + (0.6 if bj in KOMSU.get(ai, ()) else 1.0)
            v = min(v, onceki[j] + 1.0, simdi[j - 1] + 1.0)
            if onceki2 is not None and i > 1 and j > 1 and ai == b[j - 2] and a[i - 2] == bj:
                v = min(v, onceki2[j - 2] + 0.6)
            simdi[j] = v
        if min(simdi) > sinir:
            return sinir + 1
        onceki2, onceki = onceki, simdi
    return onceki[m]


# Türkçe ek parçaları (ünlü uyumu varyantlarıyla). Çekimli doğru kelimeleri tanımak için.
EKLER = tuple(set("""
lar ler ları leri ın in un ün nın nin nun nün a e ya ye na ne ı i u ü yı yi yu yü nı ni nu nü
da de ta te dan den tan ten nda nde ndan nden la le yla yle m im ım um üm n sı si su sü
ımız imiz umuz ümüz mız miz muz müz ınız iniz unuz ünüz nız niz nuz nüz
lık lik luk lük lı li lu lü sız siz suz süz cı ci cu cü çı çi çu çü ca ce ça çe ki
dır dir dur dür tır tir tur tür dı di du dü tı ti tu tü mış miş muş müş sa se ken ymış ymiş ydı ydi
yor ıyor iyor uyor üyor acak ecek yacak yecek acağ eceğ yacağ yeceğ ar er ır ir ur ür
maz mez ma me mak mek ıp ip up üp arak erek ınca ince unca ünce yınca yince
dık dik duk dük tık tik tuk tük ız iz uz üz k sın sin sun sün sınız siniz sunuz sünüz
lım lim lum lüm ış iş uş üş gın gin gun gün ıcı ici ucu ücü mi mı mu mü
""".split()))


SESLI = "aeıioöuü"


@functools.lru_cache(maxsize=None)
def ek_parcala(s, onceki_sesli, hak=4):
    """s, en fazla 4 ekin art arda gelmesiyle yazılabiliyor mu? Sesli harften sonra
    sesli harfle başlayan ek gelemez (araya y/n/s girer) kuralı uygulanır."""
    if not s:
        return True
    if hak == 0:
        return False
    for a in EKLER:
        if s.startswith(a) and not (onceki_sesli and a[0] in SESLI):
            if ek_parcala(s[len(a):], a[-1] in SESLI, hak - 1):
                return True
    return False


class KelimeListesi:
    """Bir kelime listesinden 'en yakın kelimeyi' bulur."""

    def __init__(self):
        self.hazir = False
        self.sayi = 0
        self._sifirla()

    def _sifirla(self):
        self.kelimeler = {}                      # şapkasız hal -> listedeki yazılış
        self.fiil_kokleri = set()                # yapmak -> yap
        self.ilk = collections.defaultdict(list)     # (ilk harf, uzunluk) -> kelimeler
        self.son2 = collections.defaultdict(list)    # (son 2 harf, uzunluk) -> kelimeler

    def yukle(self, yol):
        self.hazir = False
        self._sifirla()
        with open(yol, "r", encoding="utf-8-sig", errors="replace") as f:
            for satir in f:
                w = tr_lower(satir.strip())
                if not w or not w.isalpha():     # "abaka güreşi", "a / e" gibi satırları atla
                    continue
                self.kelimeler.setdefault(w.translate(SAPKA), w)
        for n in self.kelimeler:
            if len(n) >= 3:
                self.ilk[(n[0], len(n))].append(n)
                self.son2[(n[-2:], len(n))].append(n)
            if n.endswith(("mak", "mek")) and len(n) >= 5:
                self.fiil_kokleri.add(n[:-3])
        self.sayi = len(self.kelimeler)
        self.hazir = True

    def _kok_var(self, kok, ek):
        k, fk = self.kelimeler, self.fiil_kokleri
        if kok in k or kok in fk:
            return True
        yumusama = {"b": "p", "c": "ç", "d": "t", "ğ": "k"}      # kitab-ı -> kitap
        son = kok[-1]
        if son in yumusama and kok[:-1] + yumusama[son] in k:
            return True
        if ek.startswith(("ıyor", "iyor", "uyor", "üyor")) and (kok + "a" in fk or kok + "e" in fk):
            return True                                             # bekl-iyor -> bekle
        if ek.startswith("yor") and son in "iı" and kok[:-1] + ("e" if son == "i" else "a") in fk:
            return True                                             # di-yor -> de
        return False

    def gecerli(self, n):
        """Kelime listede mi, ya da 'listedeki kök + Türkçe ekler' olarak açıklanabiliyor mu?"""
        if n in self.kelimeler:
            return True
        for i in range(len(n) - 1, 1, -1):
            if ek_parcala(n[i:], n[i - 1] in SESLI) and self._kok_var(n[:i], n[i:]):
                return True
        return False

    def en_yakin(self, n, sinir):
        """(kelime, uzaklık) veya None. Aynı ilk harfli ya da aynı son 2 harfli adaylara bakar."""
        L = len(n)
        en_iyi, goruldu = None, set()
        for uz in range(L - 2, L + 3):
            for grup in (self.ilk.get((n[0], uz), ()), self.son2.get((n[-2:], uz), ())):
                for c in grup:
                    if c in goruldu:
                        continue
                    goruldu.add(c)
                    if L > len(c) and n.startswith(c):       # aday + ek gibi duruyor, dokunma
                        continue
                    d = agirlikli_mesafe(n, c, sinir)
                    if d <= sinir:
                        anahtar = (d, abs(len(c) - L), c)
                        if en_iyi is None or anahtar < en_iyi:
                            en_iyi = anahtar
        return (self.kelimeler[en_iyi[2]], en_iyi[0]) if en_iyi else None


# ------------------------------------------------------------------ MOTOR
# Windows düşük seviye klavye kancası (WH_KEYBOARD_LL). Programın kendi gönderdiği
# tuşlar "injected" bayrağıyla ayırt edilir; düzeltme sürerken basılan gerçek tuşlar
# sıraya alınır ve düzeltme bitince sırayla ekrana + hafızaya işlenir.
import ctypes
from ctypes import wintypes

if os.name != "nt":
    raise SystemExit("Bu sürüm sadece Windows için.")

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

WH_KEYBOARD_LL = 13
WM_KEYDOWN, WM_SYSKEYDOWN = 0x0100, 0x0104
LLKHF_EXTENDED, LLKHF_INJECTED = 0x01, 0x10
VK_BACK, VK_RETURN, VK_SPACE, VK_F7, VK_F8, VK_F9 = 0x08, 0x0D, 0x20, 0x76, 0x77, 0x78
MOD_VKS = {0x10, 0x11, 0x12, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5,
           0x14, 0x5B, 0x5C, 0x90, 0x91}


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD),
                ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.CallNextHookEx.restype = ctypes.c_ssize_t
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.c_void_p]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetKeyboardLayout.argtypes = [wintypes.DWORD]
user32.GetKeyboardLayout.restype = ctypes.c_void_p
user32.ToUnicodeEx.argtypes = [wintypes.UINT, wintypes.UINT, ctypes.c_void_p,
                               ctypes.c_wchar_p, ctypes.c_int, wintypes.UINT, ctypes.c_void_p]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.GetKeyState.restype = ctypes.c_short
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE


def tus_gonder(vk, asagi, genis=False):
    scan = user32.MapVirtualKeyW(vk, 0)
    bayrak = (0 if asagi else 2) | (1 if genis else 0)
    user32.keybd_event(vk, scan, bayrak, 0)


def karakter_bul(vk, scan, shift, caps):
    """Basılan tuşun mevcut klavye düzenindeki (Türkçe Q vb.) karakterini verir."""
    durum = (ctypes.c_ubyte * 256)()
    if shift:
        durum[0x10] = 0x80
    if caps:
        durum[0x14] = 0x01
    tampon = ctypes.create_unicode_buffer(8)
    hkl = user32.GetKeyboardLayout(user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None))
    n = user32.ToUnicodeEx(vk, scan, durum, tampon, 8, 0x4, hkl)
    return tampon.value[:1] if n == 1 else ""


class Motor:
    def __init__(self, cfg):
        self.cfg = cfg
        self.buffer = ""
        self.son_karakter = ""
        self.injecting = False
        self.lock = threading.RLock()
        self.held = []               # düzeltme sırasında basılan gerçek tuşlar
        self.jobs = queue.Queue()
        self.ui = queue.Queue()      # arayüz iş parçacığına mesajlar
        self.duzeltilen = 0
        self.bilinen = []
        self._tid = None
        self.tdk_cache = self.tdk_yukle()
        self.tdk_kapali_bitis = 0
        self.son_tdk = None
        self._kaynak_tdk = False
        self.liste = KelimeListesi()
        self.liste_cache = {}
        self.bilinenleri_yenile()
        threading.Thread(target=self._worker, daemon=True).start()
        threading.Thread(target=self._kanca_dongusu, daemon=True).start()
        self.liste_yukle_baslat()

    # -- yardımcılar
    def log(self, msg):
        self.ui.put(("log", f"[{time.strftime('%H:%M:%S')}] {msg}"))

    def bilinenleri_yenile(self):
        kelimeler = set(TEMEL_KELIMELER)
        for v in self.cfg["sozluk"].values():
            kelimeler.update(tr_lower(v).split())
        self.bilinen = sorted(kelimeler)

    def mod_degistir(self, anahtar):
        self.cfg[anahtar] = not self.cfg[anahtar]
        ayar_kaydet(self.cfg)
        self.ui.put(("toggle", anahtar))
        self.log(f"{anahtar}: {'AÇIK' if self.cfg[anahtar] else 'KAPALI'}")

    def kapat(self):
        if self._tid:
            user32.PostThreadMessageW(self._tid, 0x0012, 0, 0)   # WM_QUIT

    def isi_planla(self, silinecek, metin, enter):
        self.injecting = True
        self.jobs.put((silinecek, metin, enter))

    def isi_planla_gec(self, fonksiyon):
        """İş, çalışma anında hesaplanır (TDK sorgusu gibi). Bu sırada basılan tuşlar sıraya alınır."""
        self.injecting = True
        self.jobs.put(fonksiyon)

    # -- kelime dönüşümü
    def duzelt(self, kelime):
        dusuk = tr_lower(kelime)
        hedef = self.cfg["sozluk"].get(dusuk)
        if hedef is None and self.cfg["tdk"] and dusuk not in self.cfg["yoksay"]:
            hedef = self.tdk_cache.get(dusuk) or None
            self._kaynak_tdk = hedef is not None
        if hedef is None and self.cfg["liste"] and dusuk not in self.cfg["yoksay"]:
            hedef = self.liste_cache.get(dusuk) or None      # daha önce bulunan liste düzeltmeleri
            self._kaynak_tdk = hedef is not None             # F7 ile geri alınabilir
        if hedef is None:
            return kelime
        return buyuklugu_koru(kelime, hedef)

    def donustur(self, kelime):
        """(yeni_kelime, degisti_mi)"""
        self._kaynak_tdk = False
        if kelime.isdigit():
            return kelime, False
        if self.cfg["lol_mode"]:
            return "  ".join(tr_upper(kelime)), True
        if self.cfg["autocorrect"]:
            yeni = self.duzelt(kelime)
            return yeni, yeni != kelime
        return kelime, False

    def bitir(self, ayirac):
        """Boşluk veya noktalama ile kelime bitti."""
        kelime, self.buffer = self.buffer, ""
        if not kelime:
            if ayirac != " ":
                self.son_karakter = ayirac
            return
        yeni, degisti = self.donustur(kelime)
        if degisti:
            son = LOL_KELIME_ARASI if (self.cfg["lol_mode"] and ayirac == " ") else ayirac
            self.isi_planla(len(kelime) + 1, yeni + son, False)
            self.duzeltilen += 1
            self.log(f"{kelime} → {yeni}")
            self.son_tdk = ({"orj": kelime, "yeni": yeni, "ayirac": ayirac, "kuyruk": ""}
                            if self._kaynak_tdk else None)
            kelime = yeni
        elif self.liste_gerekli(kelime):
            self.isi_planla_gec(lambda k=kelime, a=ayirac: self.liste_isi(k, a))
        elif self.tdk_gerekli(kelime):
            self.isi_planla_gec(lambda k=kelime, a=ayirac: self.tdk_isi(k, a))
        self.son_karakter = ayirac if ayirac != " " else kelime[-1]

    def enter(self):
        """True dönerse gerçek Enter engellenir; biz düzeltmeden sonra göndeririz."""
        kelime = self.buffer
        yeni, degisti = self.donustur(kelime) if kelime else (kelime, False)
        if kelime and not degisti and self.liste_gerekli(kelime):
            self.buffer = ""
            self.son_karakter = ""
            self.isi_planla_gec(lambda k=kelime: self.liste_enter_isi(k))
            return True
        if kelime and not degisti and self.tdk_gerekli(kelime):
            self.buffer = ""
            self.son_karakter = ""
            self.isi_planla_gec(lambda k=kelime: self.tdk_enter_isi(k))
            return True
        son = yeni[-1] if yeni else self.son_karakter
        nokta = (self.cfg["auto_period"] and not self.cfg["lol_mode"]
                 and son and son not in NOKTALAMA)
        self.buffer = ""
        self.son_karakter = ""
        if not degisti and not nokta:
            return False
        metin = (yeni if degisti else "") + ("." if nokta else "")
        self.isi_planla(len(kelime) if degisti else 0, metin, True)
        if degisti:
            self.duzeltilen += 1
            self.log(f"{kelime} → {yeni}")
        return True

    def isle(self, vk, ch, shift, ctrlalt):
        """Bir tuş basımını işler. True dönerse tuş ekrana gitmesin."""
        if vk == VK_F7:
            self.geri_al()
            return False
        if vk == VK_F9:
            self.mod_degistir("lol_mode")
            return False
        if vk == VK_F8:
            self.mod_degistir("autocorrect")
            return False
        if vk in MOD_VKS:
            return False
        if self.son_tdk is not None:     # F7 ile geri alabilmek için düzeltmeden sonra yazılanları izle
            d = self.son_tdk
            if vk == VK_BACK:
                if d["kuyruk"]:
                    d["kuyruk"] = d["kuyruk"][:-1]
                else:
                    self.son_tdk = None
            elif vk == VK_SPACE and not ctrlalt:
                d["kuyruk"] += " "
            elif ch and ch.isprintable() and not ctrlalt:
                d["kuyruk"] += ch
            else:
                self.son_tdk = None
        if vk == VK_RETURN:
            return self.enter()
        if ctrlalt:                      # Ctrl+V, Ctrl+A vb. kelimeyi bozar
            self.buffer = ""
            return False
        if vk == VK_SPACE:
            self.bitir(" ")
        elif vk == VK_BACK:
            self.buffer = self.buffer[:-1]
        elif ch and ch.isalnum():
            self.buffer += ch
            self.son_karakter = ch
        elif ch in (".", ","):
            self.bitir(ch)
        elif ch and ch.isprintable():
            self.buffer = ""
            self.son_karakter = ch
        else:                            # ok tuşları, tab, esc, home...
            self.buffer = ""
        return False

    # -- Kelime listesi ile düzeltme
    def liste_yukle_baslat(self):
        def is_():
            yol = self.cfg.get("liste_yolu") or os.path.join(BASE, "turkce_kelime_listesi.txt")
            if not os.path.exists(yol):
                self.ui.put(("liste", "Kelime listesi yok: turkce_kelime_listesi.txt'yi tasak.py'nin yanına koy"))
                return
            try:
                self.liste.yukle(yol)
                self.liste_cache.clear()
                mesaj = f"Kelime listesi: {self.liste.sayi:,} kelime yüklendi".replace(",", ".")
                self.ui.put(("liste", mesaj))
                self.log(mesaj)
            except Exception as ex:
                self.ui.put(("liste", f"Liste okunamadı: {ex}"))
        threading.Thread(target=is_, daemon=True).start()

    def liste_aktif(self):
        c = self.cfg
        return bool(c["liste"] and c["autocorrect"] and not c["lol_mode"] and self.liste.hazir)

    def liste_gerekli(self, kelime):
        """Bu kelime listede yok ve ek almış bir doğru kelime de değil mi? O zaman en yakını aranır."""
        if not self.liste_aktif():
            return False
        dusuk = tr_lower(kelime)
        if (len(dusuk) < 5 or not dusuk.isalpha() or kelime == tr_upper(kelime)
                or dusuk in self.cfg["yoksay"] or dusuk in self.cfg["sozluk"]
                or dusuk in self.liste_cache or dusuk in self.bilinen):
            return False
        return not self.liste.gecerli(norm(kelime))

    def liste_duzeltme(self, kelime):
        dusuk = tr_lower(kelime)
        if dusuk in self.liste_cache:
            sonuc = self.liste_cache[dusuk]
        else:
            L = len(dusuk)
            sinir = 1.0 if L <= 5 else (1.6 if L <= 7 else 2.0)
            if kelime[0] != tr_lower(kelime[0]):         # Baş harfi büyükse (özel isim olabilir) daha temkinli
                sinir = min(sinir, 1.0)
            bulunan = self.liste.en_yakin(norm(kelime), sinir)
            sonuc = bulunan[0] if bulunan else ""
            self.liste_cache[dusuk] = sonuc
        return buyuklugu_koru(kelime, sonuc) if sonuc else None

    def liste_isi(self, kelime, ayirac):
        yeni = self.liste_duzeltme(kelime)
        if not yeni:
            return (0, "", False)
        self.duzeltilen += 1
        self.log(f"Liste: {kelime} → {yeni}")
        self.son_tdk = {"orj": kelime, "yeni": yeni, "ayirac": ayirac, "kuyruk": ""}
        return (len(kelime) + 1, yeni + ayirac, False)

    def liste_enter_isi(self, kelime):
        yeni = self.liste_duzeltme(kelime)
        if yeni:
            self.duzeltilen += 1
            self.log(f"Liste: {kelime} → {yeni}")
        son = (yeni or kelime)[-1]
        nokta = self.cfg["auto_period"] and son not in NOKTALAMA
        return (len(kelime) if yeni else 0, (yeni or "") + ("." if nokta else ""), True)

    # -- TDK denetimi
    def tdk_yukle(self):
        try:
            with open(TDK_ONBELLEK, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def tdk_kaydet(self):
        try:
            with open(TDK_ONBELLEK, "w", encoding="utf-8") as f:
                json.dump(self.tdk_cache, f, ensure_ascii=False)
        except OSError:
            pass

    def tdk_gerekli(self, kelime):
        """Bu kelime için TDK'ya sorulmalı mı? (Önbellekte olanlara internet gerekmez.)"""
        c = self.cfg
        if not (c["tdk"] and c["autocorrect"]) or c["lol_mode"]:
            return False
        if time.time() < self.tdk_kapali_bitis or self.liste_aktif():
            return False
        dusuk = tr_lower(kelime)
        return (len(dusuk) >= 4 and dusuk.isalpha() and kelime != tr_upper(kelime)
                and dusuk not in self.tdk_cache and dusuk not in c["yoksay"]
                and dusuk not in c["sozluk"] and dusuk not in self.bilinen)

    def tdk_duzeltme(self, kelime):
        """TDK'ya sorar. Düzeltme varsa (büyük/küçük harfi korunmuş) verir, yoksa None."""
        dusuk = tr_lower(kelime)
        q = urllib.parse.quote(dusuk)
        try:
            veri = tdk_json(f"https://sozluk.gov.tr/gts?ara={q}")
        except Exception as ex:
            self.tdk_kapali_bitis = time.time() + 60
            self.log(f"TDK'ya ulaşılamadı, 60 sn ara verildi ({type(ex).__name__})")
            return None
        if isinstance(veri, list) and veri:              # kelime TDK'da var, dokunma
            self.tdk_cache[dusuk] = ""
            self.tdk_kaydet()
            return None
        try:
            oneriler = tdk_oneri_listesi(tdk_json(f"https://sozluk.gov.tr/oneri?soz={q}"))
        except (ValueError, urllib.error.HTTPError):    # öneri yok
            oneriler = []
        except Exception as ex:
            self.tdk_kapali_bitis = time.time() + 60
            self.log(f"TDK'ya ulaşılamadı, 60 sn ara verildi ({type(ex).__name__})")
            return None
        secilen = next((o for o in oneriler if guvenli_oneri(dusuk, o)), "")
        self.tdk_cache[dusuk] = secilen
        self.tdk_kaydet()
        return buyuklugu_koru(kelime, secilen) if secilen else None

    def tdk_isi(self, kelime, ayirac):
        yeni = self.tdk_duzeltme(kelime)
        if not yeni:
            return (0, "", False)
        self.duzeltilen += 1
        self.log(f"TDK: {kelime} → {yeni}")
        self.son_tdk = {"orj": kelime, "yeni": yeni, "ayirac": ayirac, "kuyruk": ""}
        return (len(kelime) + 1, yeni + ayirac, False)

    def tdk_enter_isi(self, kelime):
        yeni = self.tdk_duzeltme(kelime)
        if yeni:
            self.duzeltilen += 1
            self.log(f"TDK: {kelime} → {yeni}")
        son = (yeni or kelime)[-1]
        nokta = self.cfg["auto_period"] and son not in NOKTALAMA
        return (len(kelime) if yeni else 0, (yeni or "") + ("." if nokta else ""), True)

    def geri_al(self):
        """F7: Son TDK düzeltmesini geri alır ve o kelimeye bir daha dokunmaz."""
        d, self.son_tdk = self.son_tdk, None
        if not d:
            self.log("Geri alınacak TDK düzeltmesi yok.")
            return
        dusuk = tr_lower(d["orj"])
        if dusuk not in self.cfg["yoksay"]:
            self.cfg["yoksay"].append(dusuk)
            ayar_kaydet(self.cfg)
        self.tdk_cache[dusuk] = ""
        self.liste_cache[dusuk] = ""
        self.tdk_kaydet()
        sonrasi = d["ayirac"] + d["kuyruk"]
        self.isi_planla(len(d["yeni"] + sonrasi), d["orj"] + sonrasi, False)
        self.log(f"Geri alındı: {d['yeni']} → {d['orj']} (bir daha dokunulmayacak)")

    # -- Windows klavye kancası
    def _kanca(self, nCode, wParam, lParam):
        try:
            if nCode == 0:
                kb = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                if not (kb.flags & LLKHF_INJECTED):          # kendi tuşlarımızı hiç görmeyiz
                    asagi = wParam in (WM_KEYDOWN, WM_SYSKEYDOWN)
                    genis = bool(kb.flags & LLKHF_EXTENDED)
                    vk, scan = kb.vkCode, kb.scanCode
                    shift = bool(user32.GetAsyncKeyState(0x10) & 0x8000)
                    ctrlalt = bool((user32.GetAsyncKeyState(0x11) | user32.GetAsyncKeyState(0x12)) & 0x8000)
                    caps = bool(user32.GetKeyState(0x14) & 1)
                    ch = karakter_bul(vk, scan, shift, caps) if asagi else ""
                    with self.lock:
                        if self.injecting:                   # düzeltme sürüyor: tuşu sıraya al
                            self.held.append((asagi, vk, scan, genis, ch, shift, ctrlalt))
                            return 1
                        if asagi and self.isle(vk, ch, shift, ctrlalt):
                            return 1
        except Exception as ex:
            self.log(f"Hata: {ex}")
        return user32.CallNextHookEx(None, nCode, wParam, lParam)

    def _kanca_dongusu(self):
        self._tid = kernel32.GetCurrentThreadId()
        self._proc = HOOKPROC(self._kanca)                   # referansı tut
        self._hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._proc,
                                              kernel32.GetModuleHandleW(None), 0)
        if not self._hook:
            self.log("Klavye kancası kurulamadı!")
            return
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        user32.UnhookWindowsHookEx(self._hook)

    # -- yazma işçisi (kancanın içinde tuş göndermek kilitlenme yapar, o yüzden ayrı thread)
    def _is_yap(self, is_):
        if callable(is_):                # önceden hesaplanmamış iş (TDK sorgusu vb.)
            try:
                is_ = is_()
            except Exception as ex:
                self.log(f"Hata: {ex}")
                is_ = (0, "", False)
        silinecek, metin, enter = is_
        time.sleep(0.002)                # gerçek boşluk tuşu önce uygulamaya ulaşsın
        for _ in range(silinecek):
            tus_gonder(VK_BACK, True)
            tus_gonder(VK_BACK, False)
            time.sleep(0.001)
        if metin:
            keyboard.write(metin)
        if enter:
            tus_gonder(VK_RETURN, True)
            tus_gonder(VK_RETURN, False)

    def _tekrar_oynat(self, olay):
        asagi, vk, scan, genis, ch, shift, ctrlalt = olay
        if asagi and self.isle(vk, ch, shift, ctrlalt):
            return                       # Enter: düzeltme işiyle birlikte gönderilecek
        tus_gonder(vk, asagi, genis)

    def _worker(self):
        while True:
            self._is_yap(self.jobs.get())
            # Düzeltme sırasında basılan tuşları sırayla ekrana ve hafızaya işle
            while True:
                is_ = olay = None
                with self.lock:
                    if not self.jobs.empty():
                        is_ = self.jobs.get_nowait()
                    elif self.held:
                        olay = self.held.pop(0)
                    else:
                        self.injecting = False
                        break
                if is_:
                    self._is_yap(is_)
                else:
                    self._tekrar_oynat(olay)


# ---------------------------------------------------------------- ARAYÜZ
BG, CARD, GOLD, TEAL, TEXT, MUTED = "#010a13", "#0a1428", "#c8aa6e", "#0ac8b9", "#f0e6d2", "#7b8794"


class Toggle(tk.Frame):
    def __init__(self, parent, baslik, alt, tus, deger, komut):
        super().__init__(parent, bg=CARD, padx=14, pady=10, highlightthickness=1,
                         highlightbackground="#1e2d44")
        self.komut, self.deger = komut, deger
        sol = tk.Frame(self, bg=CARD)
        sol.pack(side="left", fill="x", expand=True)
        tk.Label(sol, text=baslik, bg=CARD, fg=TEXT, font=("Segoe UI", 11, "bold"),
                 anchor="w").pack(fill="x")
        tk.Label(sol, text=alt + (f"   [{tus}]" if tus else ""), bg=CARD, fg=MUTED,
                 font=("Segoe UI", 9), anchor="w").pack(fill="x")
        self.pill = tk.Label(self, width=8, font=("Segoe UI", 10, "bold"), cursor="hand2", pady=4)
        self.pill.pack(side="right")
        self.pill.bind("<Button-1>", lambda _e: self.tikla())
        self.goster()

    def goster(self):
        self.pill.config(text="AÇIK" if self.deger else "KAPALI",
                         bg=TEAL if self.deger else "#1e2d44",
                         fg=BG if self.deger else MUTED)

    def ayarla(self, deger):
        self.deger = deger
        self.goster()

    def tikla(self):
        self.deger = not self.deger
        self.goster()
        self.komut(self.deger)


class Uygulama:
    def __init__(self, root):
        self.root = root
        self.cfg = ayar_yukle()
        root.title("TAŞAK • Oto Düzeltici")
        root.geometry("640x840")
        root.configure(bg=BG)
        self.stil()

        tk.Label(root, text="TAŞAK", bg=BG, fg=GOLD, font=("Georgia", 26, "bold")).pack(pady=(16, 0))
        tk.Label(root, text="yazım hatalarına elveda • LoL modu dahil", bg=BG, fg=MUTED,
                 font=("Segoe UI", 10)).pack(pady=(0, 10))

        kutu = tk.Frame(root, bg=BG)
        kutu.pack(fill="x", padx=18)
        self.toggles = {}
        for anahtar, baslik, alt, tus in [
            ("autocorrect", "Oto-düzeltme", "Boşluğa basınca kelimeyi sözlüğe göre düzeltir", "F8"),
            ("lol_mode", "LoL modu", "M  E  R  H  A  B  A  şeklinde büyük harf yazar", "F9"),
            ("auto_period", "Enter'da nokta", "Cümle sonuna nokta yoksa ekler", ""),
            ("liste", "Kelime listesi ile düzelt", "Listede olmayan kelimeyi en yakın kelimeyle değiştirir • F7 geri al", "F7"),
            ("tdk", "TDK denetimi (internet)", "Bilinmeyen kelimeyi TDK'ya sorar • yanlışsa geri al", "F7"),
        ]:
            t = Toggle(kutu, baslik, alt, tus, self.cfg[anahtar],
                       lambda v, a=anahtar: self.ayar_degisti(a, v))
            t.pack(fill="x", pady=3)
            self.toggles[anahtar] = t

        self.istatistik = tk.Label(root, text="Düzeltilen kelime: 0", bg=BG, fg=GOLD,
                                   font=("Segoe UI", 10, "bold"))
        self.istatistik.pack(pady=(6, 2))
        satir = tk.Frame(root, bg=BG)
        satir.pack(fill="x", padx=18, pady=(0, 6))
        self.liste_etiket = tk.Label(satir, text="Kelime listesi: yükleniyor...", bg=BG, fg=MUTED,
                                     font=("Segoe UI", 9), anchor="w")
        self.liste_etiket.pack(side="left", fill="x", expand=True)
        ttk.Button(satir, text="Liste seç…", command=self.liste_sec).pack(side="right")

        nb = ttk.Notebook(root)
        nb.pack(fill="both", expand=True, padx=18, pady=(0, 16))
        self.sozluk_sekmesi(nb)
        self.deneme_sekmesi(nb)
        self.kayit_sekmesi(nb)

        self.motor = Motor(self.cfg)
        self.motor.log("Motor başladı. Klavye dinleniyor.")
        root.protocol("WM_DELETE_WINDOW", self.kapat)
        self.pompa()

    # -- görünüm
    def stil(self):
        s = ttk.Style()
        s.theme_use("clam")
        s.configure("TNotebook", background=BG, borderwidth=0)
        s.configure("TNotebook.Tab", background=CARD, foreground=MUTED, padding=(16, 6))
        s.map("TNotebook.Tab", background=[("selected", "#12213d")], foreground=[("selected", GOLD)])
        s.configure("Treeview", background=CARD, fieldbackground=CARD, foreground=TEXT,
                    rowheight=26, borderwidth=0)
        s.configure("Treeview.Heading", background="#12213d", foreground=GOLD, relief="flat")
        s.map("Treeview", background=[("selected", "#1e3a5f")])
        s.configure("TButton", background=GOLD, foreground=BG, padding=6, borderwidth=0)
        s.map("TButton", background=[("active", "#e0c48a")])

    def sozluk_sekmesi(self, nb):
        f = tk.Frame(nb, bg=CARD)
        nb.add(f, text="  Sözlük  ")
        ust = tk.Frame(f, bg=CARD)
        ust.pack(fill="x", padx=10, pady=10)
        self.e_yanlis = tk.Entry(ust, bg="#12213d", fg=TEXT, insertbackground=TEXT, relief="flat")
        self.e_dogru = tk.Entry(ust, bg="#12213d", fg=TEXT, insertbackground=TEXT, relief="flat")
        self.e_yanlis.pack(side="left", fill="x", expand=True, ipady=5, padx=(0, 4))
        tk.Label(ust, text="→", bg=CARD, fg=GOLD).pack(side="left")
        self.e_dogru.pack(side="left", fill="x", expand=True, ipady=5, padx=4)
        self.e_dogru.bind("<Return>", lambda _e: self.ekle())
        ttk.Button(ust, text="Ekle", command=self.ekle).pack(side="left", padx=4)

        self.agac = ttk.Treeview(f, columns=("y", "d"), show="headings", selectmode="extended")
        self.agac.heading("y", text="Yanlış yazım")
        self.agac.heading("d", text="Doğrusu")
        self.agac.pack(fill="both", expand=True, padx=10)
        alt = tk.Frame(f, bg=CARD)
        alt.pack(fill="x", padx=10, pady=8)
        ttk.Button(alt, text="Seçileni sil", command=self.sil).pack(side="left")
        tk.Label(alt, text="Büyük/küçük harf otomatik korunur (Cok → Çok)", bg=CARD, fg=MUTED,
                 font=("Segoe UI", 9)).pack(side="left", padx=10)
        self.agac_doldur()

    def deneme_sekmesi(self, nb):
        f = tk.Frame(nb, bg=CARD)
        nb.add(f, text="  Deneme  ")
        tk.Label(f, text="Buraya yazarak dene (heme, cok, knk, porgram...)", bg=CARD, fg=MUTED,
                 font=("Segoe UI", 9)).pack(anchor="w", padx=10, pady=8)
        self.deneme = tk.Text(f, bg="#12213d", fg=TEXT, insertbackground=TEXT, relief="flat",
                              font=("Consolas", 13), wrap="word")
        self.deneme.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def kayit_sekmesi(self, nb):
        f = tk.Frame(nb, bg=CARD)
        nb.add(f, text="  Kayıt  ")
        self.kayit = tk.Text(f, bg=CARD, fg=TEAL, relief="flat", font=("Consolas", 10),
                             state="disabled")
        self.kayit.pack(fill="both", expand=True, padx=10, pady=10)

    # -- olaylar
    def liste_sec(self):
        yol = filedialog.askopenfilename(title="Kelime listesi seç (her satırda bir kelime)",
                                         filetypes=[("Metin dosyası", "*.txt"), ("Hepsi", "*.*")])
        if yol:
            self.cfg["liste_yolu"] = yol
            ayar_kaydet(self.cfg)
            self.liste_etiket.config(text="Kelime listesi: yükleniyor...")
            self.motor.liste_yukle_baslat()

    def ayar_degisti(self, anahtar, deger):
        self.cfg[anahtar] = deger
        ayar_kaydet(self.cfg)
        self.motor.log(f"{anahtar}: {'AÇIK' if deger else 'KAPALI'}")

    def agac_doldur(self):
        self.agac.delete(*self.agac.get_children())
        for k, v in sorted(self.cfg["sozluk"].items()):
            self.agac.insert("", "end", values=(k, v))

    def ekle(self):
        y, d = tr_lower(self.e_yanlis.get().strip()), self.e_dogru.get().strip()
        if not y or not d or " " in y:
            messagebox.showwarning("Eksik", "Yanlış kelime boşluksuz tek kelime olmalı, doğrusu boş olmamalı.")
            return
        self.cfg["sozluk"][y] = d
        ayar_kaydet(self.cfg)
        self.motor.bilinenleri_yenile()
        self.agac_doldur()
        self.e_yanlis.delete(0, "end")
        self.e_dogru.delete(0, "end")
        self.e_yanlis.focus()

    def sil(self):
        for item in self.agac.selection():
            self.cfg["sozluk"].pop(self.agac.item(item, "values")[0], None)
        ayar_kaydet(self.cfg)
        self.motor.bilinenleri_yenile()
        self.agac_doldur()

    def pompa(self):
        """Motor thread'inden gelen mesajları arayüzde işler."""
        try:
            while True:
                tur, veri = self.motor.ui.get_nowait()
                if tur == "log":
                    self.kayit.config(state="normal")
                    self.kayit.insert("end", veri + "\n")
                    self.kayit.see("end")
                    self.kayit.config(state="disabled")
                elif tur == "liste":
                    self.liste_etiket.config(text=veri)
                elif tur == "toggle":
                    self.toggles[veri].ayarla(self.cfg[veri])
        except queue.Empty:
            pass
        self.istatistik.config(text=f"Düzeltilen kelime: {self.motor.duzeltilen}")
        self.root.after(100, self.pompa)

    def kapat(self):
        self.motor.kapat()
        self.root.destroy()


if __name__ == "__main__":
    kok = tk.Tk()
    Uygulama(kok)
    kok.mainloop()
