from app.core.ask.bm25 import Bm25Index, tokenize


def _index() -> Bm25Index:
    return Bm25Index(
        [
            ("overview", "course overview teaching approach stages learning objectives"),
            ("elps", "ELPS approach experience language pictorial symbolic stages in mathematics"),
            ("other", "storytelling in the classroom with children and teaching routines"),
        ]
    )


def test_tokenize_lowercases_and_keeps_hindi_words():
    assert tokenize("ELPS का Approach, 2 steps!") == ["elps", "का", "approach", "steps"]


def test_tokenize_splits_hindi_words_at_the_danda():
    assert tokenize("बंडल बनाएँ। दहाई समझाएँ॥ क्या है?") == ["बंडल", "बनाएँ", "दहाई", "समझाएँ", "क्या", "है"]


def test_rare_query_term_outranks_generic_ones():
    hits = _index().rank(["elps", "approach", "stages", "teaching"], limit=3)

    assert hits[0].doc_id == "elps"


def test_documents_sharing_no_query_term_are_not_returned():
    hits = _index().rank(["elps"], limit=5)

    assert [h.doc_id for h in hits] == ["elps"]


def test_score_is_a_fraction_of_the_best_attainable_score():
    hits = _index().rank(["elps", "symbolic"], limit=1)

    assert 0.0 < hits[0].score <= 1.0


def test_unknown_terms_give_no_hits():
    assert _index().rank(["xyzzy"], limit=3) == []


def test_empty_index_and_empty_query_give_no_hits():
    assert Bm25Index([]).rank(["elps"], limit=3) == []
    assert _index().rank([], limit=3) == []


def test_limit_caps_the_results_best_first():
    hits = _index().rank(["approach", "stages"], limit=1)

    assert len(hits) == 1 and hits[0].doc_id in {"overview", "elps"}
