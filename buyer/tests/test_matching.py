from buyer.matching import find_matches
from buyer.tests.sample_data import LISTINGS, NEEDS
from buyer.text_utils import format_tl, tokenize, tr_lower


def ids(listings):
    return {l.listing_id for l in listings}


def test_tr_lower_turkish_i():
    assert tr_lower("İSTANBUL ILIK") == "istanbul ılık"


def test_tokenize_lowercases_and_stems():
    assert tokenize("Kot Pantolonu!") == ["kot", "panto"]


def test_format_tl():
    assert format_tl(900.0) == "900 TL"
    assert format_tl(1250.5) == "1.250,50 TL"


def test_find_matches_groups_by_seller():
    result = find_matches(NEEDS, LISTINGS)
    assert ids(result["s1"]) == {"L1", "L2", "L3"}
    assert "L4" in ids(result["s2"])
    assert "s5" not in result and "s4" not in result


def test_find_matches_has_no_duplicates():
    result = find_matches(["kot pantolon", "pantolon", "kot"], LISTINGS)
    for group in result.values():
        listing_ids = [l.listing_id for l in group]
        assert len(listing_ids) == len(set(listing_ids))


def test_unknown_need_returns_nothing():
    assert find_matches(["uzay gemisi"], LISTINGS) == {}


def test_empty_listings():
    assert find_matches(NEEDS, []) == {}
