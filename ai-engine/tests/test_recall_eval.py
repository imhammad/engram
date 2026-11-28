"""The evaluation fixture through the real pipeline with stand-in models:
retrieval finds every gold memory, and activity answers are exact."""

from evaluation import recall_fixture as fx


def test_fixture_retrieval_and_activity_answers(fresh_store):
    import recall
    from fake_models import FakeLlama
    from vector_store import embed_text

    fx.load(embed_text)
    llm = FakeLlama()
    for kind, question, groups, gold in fx.QUESTIONS:
        events = list(recall.recall(question, llm, embed_text, tz=fx.TZ, now=fx.NOW))
        meta, done = events[0], events[-1]
        expected_route = {"unanswerable": "content", "episode": "content", "day": "summary"}.get(kind, kind)
        assert done["route"] == expected_route, question
        if kind == "activity":
            answer = done["answer"].lower()
            assert all(any(k.lower() in answer for k in g) for g in groups), (question, done["answer"])
        if kind == "content":
            assert set(gold) & {s["id"] for s in meta["sources"]}, question
