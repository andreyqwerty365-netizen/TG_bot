import json
from pathlib import Path


def test_synthetic_corpus_has_labels_and_untouched_holdout():
    corpus = json.loads(Path("fixtures/stage2_corpus.json").read_text())
    examples = corpus["examples"]
    assert corpus["synthetic"] and corpus["real_model_evaluation"] == "Not Run"
    assert len(examples) >= 120 and len({e["id"] for e in examples}) == len(examples)
    assert len({e["text"] for e in examples}) == len(examples)
    assert sum(e["split"] == "held_out" for e in examples) == 36
    assert {e["category"] for e in examples} >= {"typos", "negations", "promises", "unknown_executor",
        "two_actions", "old_relative", "no_obligation", "unclear_reference"}
    for example in examples:
        assert example["label"]["intent"] and example["context"]["timezone"]
        assert example["label"]["invent_deadline"] is False
        assert example["label"]["external_commands_allowed"] is False
