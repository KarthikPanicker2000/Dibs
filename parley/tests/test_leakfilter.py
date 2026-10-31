from core.leakfilter import CANNED, filtered_message, leaks

PUBLIC = [9000, 7000, 6000]


def test_banned_phrases():
    assert leaks("I'd go up to whatever it takes", [], PUBLIC)
    assert leaks("That's my LIMIT, sorry", [], PUBLIC)
    assert leaks("She rated it highly", [], PUBLIC)


def test_numbers_near_secret_leak():
    assert leaks("We could do $12,600 for it", [12600], PUBLIC)
    assert leaks("how about 12.5k", [12600], PUBLIC)        # within 3%
    assert not leaks("how about 11k", [12600], PUBLIC)


def test_secret_close_to_public_value_is_not_a_leak():
    # 7,168 is within 3% of the public $7,000 market value, so the spec treats it as public
    assert not leaks("Fine, $7,100 then", [7168], PUBLIC)


def test_small_numbers_and_public_values_ok():
    assert not leaks("She'd give it a 9 out of 10 for sure", [9], PUBLIC)
    assert not leaks("The appraisal says $9,000", [9000], PUBLIC)   # secret == public market value
    assert not leaks("Mom wore it every day.", [12600, 7168.4], PUBLIC)


def test_filtered_message_retries_then_canned():
    drafts = ["Cara would go up to $7,650", "Fine, $7,600 then", "This ring means the world to her."]
    text, blocked = filtered_message(lambda i: drafts[i], [7650], PUBLIC)
    assert text == drafts[2] and blocked == 2
    text, blocked = filtered_message(lambda i: "my max is 7650", [7650], PUBLIC)
    assert text == CANNED and blocked == 3
