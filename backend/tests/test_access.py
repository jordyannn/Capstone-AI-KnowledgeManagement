import pytest

from app.retrieval.access import build_role_where, can_access, role_flags
from app.retrieval.search import search


@pytest.mark.parametrize(
    "role,allowed,expected",
    [
        (None, ["publik"], True),  # pengguna tanpa peran tetap boleh baca dokumen publik
        ("mahasiswa", ["publik"], True),
        ("mahasiswa", ["dosen"], False),
        ("dosen", ["dosen", "staf"], True),
        ("Dosen", ["dosen"], True),  # tidak peka huruf besar/kecil
        (None, ["dosen"], False),
        ("", ["dosen"], False),
        ("admin", ["dosen"], False),  # belum ada pengecualian admin: keputusan SCRUM-25
        ("mahasiswa", [], False),
    ],
)
def test_can_access(role, allowed, expected):
    assert can_access(role, allowed) is expected


def test_role_flags_one_boolean_per_role():
    assert role_flags(["publik", "Dosen"]) == {"role_publik": True, "role_dosen": True}
    assert role_flags([]) == {}


def test_where_without_role_is_public_only():
    assert build_role_where(None) == {"role_publik": True}
    assert build_role_where("publik") == {"role_publik": True}


def test_where_with_role_is_public_or_role():
    assert build_role_where("Mahasiswa") == {"$or": [{"role_publik": True}, {"role_mahasiswa": True}]}


class FakeEmbedder:
    def embed_query(self, text):
        return [1.0, 0.0]


class RecordingCollection:
    def __init__(self):
        self.kwargs = None

    def query(self, **kwargs):
        self.kwargs = kwargs
        return {
            "documents": [["isi chunk"]],
            "metadatas": [[{"title": "BPP", "source_url": "https://x.test/bpp", "page_number": 1, "chunk_index": 2}]],
            "distances": [[0.25]],
        }


def test_search_applies_role_filter_and_converts_distance_to_score():
    collection = RecordingCollection()
    [hit] = search("apa itu bpp", FakeEmbedder(), collection, k=3, role="dosen")
    assert collection.kwargs["where"] == build_role_where("dosen")
    assert collection.kwargs["n_results"] == 3
    assert hit.score == pytest.approx(0.75)
    assert (hit.title, hit.page_number, hit.chunk_index, hit.text) == ("BPP", 1, 2, "isi chunk")
