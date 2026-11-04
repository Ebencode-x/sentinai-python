import pytest

from sentinai.config import EVENTS_PATH, ConfigError, build_config

KEY = "snl_test_0123456789"
BASE = "https://sentinai.example.com"
FULL_ENV = {
    "SENTINAI_INGEST_URL": "https://env.example.com",
    "SENTINAI_INGEST_KEY": "snl_test_fromenv",
    "SENTINAI_ENVIRONMENT": "Production",
    "SENTINAI_RELEASE": "abc123",
}


def make(url=BASE, key=KEY, **kwargs):
    return build_config(url, key, env={}, **kwargs)


@pytest.mark.parametrize("url", [BASE, BASE + "/", BASE + EVENTS_PATH, BASE + EVENTS_PATH + "/"])
def test_url_always_ends_with_the_events_path_once(url):
    assert make(url).url == BASE + EVENTS_PATH


@pytest.mark.parametrize("url", ["http://127.0.0.1:8000", "http://localhost:8000"])
def test_plain_http_is_accepted_for_localhost_only(url):
    assert make(url).url == url + EVENTS_PATH


@pytest.mark.parametrize(
    "url",
    [
        "",
        "https://",
        "http://sentinai.example.com",
        "ftp://sentinai.example.com",
        "https://user:secret@sentinai.example.com",
        BASE + "/?token=1",
        BASE + "/#section",
    ],
)
def test_bad_urls_are_refused(url):
    with pytest.raises(ConfigError):
        make(url)


@pytest.mark.parametrize("key", ["", "abc", "snl_", "sk_live_notours"])
def test_bad_keys_are_refused(key):
    with pytest.raises(ConfigError):
        make(key=key)


def test_error_message_never_contains_the_key():
    with pytest.raises(ConfigError) as info:
        make(key="sk_live_notours")
    assert "sk_live_notours" not in str(info.value)


def test_environment_variables_are_used_when_arguments_are_missing():
    config = build_config(env=FULL_ENV)
    assert config.url == "https://env.example.com" + EVENTS_PATH
    assert config.key == "snl_test_fromenv"
    assert config.environment == "production"
    assert config.release == "abc123"


def test_arguments_win_over_environment_variables():
    config = build_config(BASE, KEY, "staging", "r1", env=FULL_ENV)
    assert config.url == BASE + EVENTS_PATH
    assert config.key == KEY
    assert config.environment == "staging"
    assert config.release == "r1"


@pytest.mark.parametrize("name", ["Not Valid!", "a" * 33, "-start"])
def test_invalid_environment_name_is_dropped_not_raised(name):
    assert make(environment=name).environment is None


def test_release_is_cut_to_64_characters_and_empty_becomes_none():
    assert make(release="x" * 100).release == "x" * 64
    assert make(release="  ").release is None


def test_repr_hides_the_key():
    assert KEY not in repr(make())
