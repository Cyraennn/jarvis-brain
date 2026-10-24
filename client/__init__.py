"""CYRAEN istemcisi (govde): sunucuya WebSocket ile baglanir, eylem isteklerini yurutur.

Cekirdek (`client/core.py`) tamamen geneldir - ses/masaustu/Qt bilmez. Masaustu PC icin
hazir handler'lar `client/desktop.py`'de; ileride robot istemcisi kendi handler'larini ayni
`register()` API'siyle ekler.

Calistirma (cyraen-brain klasorunden):  python -m client
"""
