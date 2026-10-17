"""Placeholder kelurahan list for Layer 1 population skeletons.

TODO(data): coordinates are approximate centroids and must be verified against
OpenStreetMap boundaries; replace with BPS population weights per kelurahan
(REFERENCE.md §8). Until then every kelurahan is weighted equally — these are
not statistics.
"""

# (kelurahan, kecamatan, lat, lng)
HOME_KELURAHAN = [
    ("Penjaringan", "Penjaringan", -6.1260, 106.7960),
    ("Pluit", "Penjaringan", -6.1160, 106.7900),
    ("Pademangan Barat", "Pademangan", -6.1330, 106.8330),
    ("Sunter Agung", "Tanjung Priok", -6.1440, 106.8560),
    ("Koja", "Koja", -6.1150, 106.9020),
    ("Cilincing", "Cilincing", -6.1180, 106.9450),
    ("Cengkareng Barat", "Cengkareng", -6.1450, 106.7300),
    ("Kebon Jeruk", "Kebon Jeruk", -6.1930, 106.7700),
    ("Duren Sawit", "Duren Sawit", -6.2320, 106.9140),
    ("Ciracas", "Ciracas", -6.3250, 106.8730),
    ("Pasar Minggu", "Pasar Minggu", -6.2840, 106.8420),
    ("Cempaka Putih Timur", "Cempaka Putih", -6.1780, 106.8730),
]

WORK_KELURAHAN = [
    ("Setiabudi", "Setiabudi", -6.2090, 106.8300),
    ("Karet Kuningan", "Setiabudi", -6.2190, 106.8290),
    ("Kuningan Timur", "Setiabudi", -6.2290, 106.8320),
    ("Gambir", "Gambir", -6.1750, 106.8230),
    ("Menteng", "Menteng", -6.1960, 106.8320),
    ("Kebon Melati", "Tanah Abang", -6.2000, 106.8150),
    ("Gelora", "Tanah Abang", -6.2180, 106.8020),
    ("Kelapa Gading Barat", "Kelapa Gading", -6.1600, 106.9000),
]
