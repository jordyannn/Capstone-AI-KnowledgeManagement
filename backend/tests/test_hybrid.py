from app.retrieval.hybrid import BM25Index, fuse, is_toc, stem, tokenize
from app.retrieval.search import Hit


def hit(doc, page=1, chunk=0, score=0.9, text="", title="Dok"):
    return Hit(score=score, title=title, source_url="", page_number=page, chunk_index=chunk,
               document_id=doc, allowed_roles="publik", text=text)


class FakeCollection:
    def __init__(self, rows):
        self.rows = rows  # (text, meta)

    def get(self, include):
        return {"documents": [r[0] for r in self.rows], "metadatas": [r[1] for r in self.rows]}


def meta(doc, title="Dok", category=None, page=1, chunk=0):
    return {"document_id": doc, "title": title, "category": category, "page_number": page, "chunk_index": chunk}


def test_stem_menyamakan_imbuhan():
    assert stem("mendaftar") == stem("pendaftaran") == "daftar"
    assert stem("prasyarat") == stem("persyaratan") == "syarat"
    assert stem("pembayaran") == stem("membayar") == "bayar"
    assert stem("praktek") == "praktek"  # "pra" hanya dibuang bila sisanya panjang
    assert stem("2026") == "2026"


def test_tokenize_buang_kata_fungsi():
    assert tokenize("Apa syarat untuk mendaftar sidang?") == ["syarat", "daftar", "sidang"]


def test_is_toc():
    assert is_toc("Pasal 12 Beban ....... 11 Pasal 13 ....... 12 Pasal 14 ........ 13")
    assert not is_toc("Mahasiswa wajib lulus 144 SKS. Lihat juga pasal 12.")


def test_bm25_mencocokkan_prasyarat_dengan_syarat_dan_lewati_daftar_isi_serta_pmb():
    col = FakeCollection([
        ("prasyarat sidang Tugas Akhir: lulus minimal 144 SKS", meta("ta", "Panduan TA", page=16)),
        ("Sidang ....... 3 Syarat ....... 4 Daftar ....... 5", meta("ta", "Panduan TA", page=2)),
        ("syarat pendaftaran mahasiswa baru jalur rapor", meta("pmb1", "PMB", category="pmb")),
        ("jadwal wisuda periode I", meta("kal", "Kalender")),
    ])
    index = BM25Index.from_collection(col)
    assert "pmb1" in index.excluded_documents
    hits = index.search("Apa syarat mendaftar sidang tugas akhir?", k=5)
    assert [(h.document_id, h.page_number) for h in hits] == [("ta", 16)]


def test_fuse_berselang_seling_tanpa_duplikat():
    v = [hit("a"), hit("b"), hit("c")]
    b = [hit("b", score=0.0), hit("d", score=0.0)]
    out = fuse(v, b, k=4)
    assert [h.document_id for h in out] == ["a", "b", "d", "c"]
