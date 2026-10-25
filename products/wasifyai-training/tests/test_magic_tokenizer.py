"""Magic words against the model's own tokenizer: a word it already knows is refused in words, and
the suggestions leave such words out."""

from training_rig import BASE, new_dataset
from wasifyai_training import magic

KNOWN = {"sunrise": (["sunrise"], ["sunrise"]), "brainy": (["brain", "y"], ["brain"])}


class Tokenizing:
    """What the engine's tokenizer says: a few real words are known, anything else is made up."""

    def __init__(self) -> None:
        self.asked: list[list[str]] = []

    async def tokenize(self, words):
        self.asked.append(list(words))
        return {
            w: dict(zip(("pieces", "known"), KNOWN.get(w, ([w[:2], w[2:]], [])), strict=True))
            for w in words
        }


def test_a_word_that_is_one_piece_or_holds_a_known_word_is_judged_in_words():
    assert "one word" in (magic.judge("sunrise", ["sunrise"], ["sunrise"]) or "")
    assert "brain" in (magic.judge("brainy", ["brain", "y"], ["brain"]) or "")
    assert magic.judge("marlo", ["mar", "lo"], []) is None


def test_a_made_up_word_is_taken_and_a_word_the_model_knows_is_refused(rig):
    engine = Tokenizing()
    rig.app_state.training.tokenize = engine.tokenize
    ds = new_dataset(rig)
    ok = rig.patch(f"{BASE}/datasets/{ds['id']}", json={"trigger_word": "marlo"})
    assert ok.status_code == 200 and ok.json()["trigger_word"] == "marlo"
    bad = rig.patch(f"{BASE}/datasets/{ds['id']}", json={"trigger_word": "sunrise"})
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "bad_word"
    assert "one word" in bad.json()["detail"]["message"]
    still = rig.get(f"{BASE}/datasets/{ds['id']}").json()
    assert still["trigger_word"] == "marlo"  # the refused word was not kept


def test_the_suggestions_are_the_first_three_the_tokenizer_likes(rig):
    engine = Tokenizing()
    rig.app_state.training.tokenize = engine.tokenize
    ds = new_dataset(rig, name="Sunrise")  # the person's own name is a candidate, and a known word
    words = rig.get(f"{BASE}/datasets/{ds['id']}").json()["suggestions"]
    assert len(words) == 3 and "sunrise" not in words
    assert engine.asked and len(engine.asked[0]) > 3  # a pool was looked at, not three


def test_without_a_tokenizer_the_sound_rules_still_give_three_words(rig):
    ds = new_dataset(rig)
    assert len(rig.get(f"{BASE}/datasets/{ds['id']}").json()["suggestions"]) == 3
