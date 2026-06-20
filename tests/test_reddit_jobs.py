import re

import responses

from board_aggregator.scrapers.reddit_jobs import RedditJobsScraper

LISTING_URL_PATTERN = re.compile(r"https://www\.reddit\.com/r/.+/new\.json")
OAUTH_LISTING_URL_PATTERN = re.compile(r"https://oauth\.reddit\.com/r/.+/new")
TOKEN_URL = "https://www.reddit.com/api/v1/access_token"

LISTING_RESPONSE_PAGE_1 = {
    "data": {
        "after": "t3_page2cursor",
        "children": [
            {
                "data": {
                    "title": "[Hiring] Senior Python Dev at Acme Corp",
                    "selftext": "We're looking for a senior Python developer. Remote OK. $150K-$180K.",
                    "author": "acme_recruiter",
                    "subreddit": "forhire",
                    "permalink": "/r/forhire/comments/abc123/hiring_senior_python_dev/",
                    "created_utc": 1743897600.0,
                    "link_flair_text": "Hiring",
                }
            },
            {
                "data": {
                    "title": "Best laptop for remote work?",
                    "selftext": "Looking for recommendations on laptops.",
                    "author": "random_user",
                    "subreddit": "remotework",
                    "permalink": "/r/remotework/comments/def456/best_laptop/",
                    "created_utc": 1743897500.0,
                    "link_flair_text": None,
                }
            },
        ],
    }
}

LISTING_RESPONSE_PAGE_2 = {
    "data": {
        "after": None,
        "children": [
            {
                "data": {
                    "title": "We're hiring a DevOps engineer",
                    "selftext": "Our team at CloudCo needs a DevOps engineer. Apply at cloudco.io/careers.",
                    "author": "cloudco_hr",
                    "subreddit": "webdev",
                    "permalink": "/r/webdev/comments/ghi789/were_hiring_devops/",
                    "created_utc": 1743897400.0,
                    "link_flair_text": None,
                }
            },
        ],
    }
}


@responses.activate
def test_fetch_listings_paginates(monkeypatch):
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
    responses.add(responses.GET, LISTING_URL_PATTERN, json=LISTING_RESPONSE_PAGE_1, status=200)
    responses.add(responses.GET, LISTING_URL_PATTERN, json=LISTING_RESPONSE_PAGE_2, status=200)

    scraper = RedditJobsScraper()
    posts = scraper._fetch_listings()

    assert len(posts) == 3


@responses.activate
def test_scrape_filters_and_parses(monkeypatch):
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
    listing = {
        "data": {
            "after": None,
            "children": [
                # Tier 1 hiring post — should be kept
                {
                    "data": {
                        "title": "[Hiring] Backend Engineer | Acme Corp | Remote",
                        "selftext": "We need a backend engineer. Python, AWS. $140K-$170K. Apply at acme.io/careers",
                        "author": "acme_hr",
                        "subreddit": "forhire",
                        "permalink": "/r/forhire/comments/aaa/hiring_backend/",
                        "created_utc": 1743897600.0,
                        "link_flair_text": "Hiring",
                    }
                },
                # [For Hire] post — should be skipped
                {
                    "data": {
                        "title": "[For Hire] Experienced React dev available",
                        "selftext": "I'm available for contract work.",
                        "author": "freelancer_joe",
                        "subreddit": "forhire",
                        "permalink": "/r/forhire/comments/bbb/for_hire_react/",
                        "created_utc": 1743897500.0,
                        "link_flair_text": "For Hire",
                    }
                },
                # AutoModerator — should be skipped
                {
                    "data": {
                        "title": "Weekly discussion thread",
                        "selftext": "Post your questions here.",
                        "author": "AutoModerator",
                        "subreddit": "forhire",
                        "permalink": "/r/forhire/comments/ccc/weekly/",
                        "created_utc": 1743897400.0,
                        "link_flair_text": None,
                    }
                },
                # Tier 2 with hiring signal — should be kept
                {
                    "data": {
                        "title": "We're hiring a data scientist",
                        "selftext": "Join our ML team at DataCo. Remote friendly.",
                        "author": "dataco_eng",
                        "subreddit": "datascience",
                        "permalink": "/r/datascience/comments/ddd/hiring_ds/",
                        "created_utc": 1743897300.0,
                        "link_flair_text": None,
                    }
                },
                # Tier 2 without hiring signal — should be skipped
                {
                    "data": {
                        "title": "Best Python libraries for data viz?",
                        "selftext": "I'm comparing matplotlib vs plotly.",
                        "author": "student_anna",
                        "subreddit": "datascience",
                        "permalink": "/r/datascience/comments/eee/python_viz/",
                        "created_utc": 1743897200.0,
                        "link_flair_text": None,
                    }
                },
                # Deleted post — should be skipped
                {
                    "data": {
                        "title": "[Hiring] Something good",
                        "selftext": "[deleted]",
                        "author": None,
                        "subreddit": "forhire",
                        "permalink": "/r/forhire/comments/fff/deleted/",
                        "created_utc": 1743897100.0,
                        "link_flair_text": "Hiring",
                    }
                },
            ],
        }
    }

    responses.add(responses.GET, LISTING_URL_PATTERN, json=listing, status=200)

    scraper = RedditJobsScraper()
    jobs = scraper.scrape(["any"])

    assert len(jobs) == 2
    assert jobs[0].source == "reddit"
    assert jobs[0].title == "[Hiring] Backend Engineer | Acme Corp | Remote"
    assert jobs[0].company == "Acme Corp"
    assert jobs[0].job_url == "https://reddit.com/r/forhire/comments/aaa/hiring_backend/"
    assert jobs[0].is_remote is True
    assert jobs[0].salary_min == 140000
    assert jobs[0].salary_max == 170000

    assert jobs[1].company == "r/datascience"  # fallback — no pipe format in title


@responses.activate
def test_scrape_returns_empty_on_403_and_fails_loud(monkeypatch, capsys):
    # No creds: anonymous path. Reddit now blocks it with a 403 HTML block page.
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
    responses.add(
        responses.GET,
        LISTING_URL_PATTERN,
        body="<html>blocked</html>",
        status=403,
        content_type="text/html",
    )

    scraper = RedditJobsScraper()
    jobs = scraper.scrape(["any"])

    # Returns gracefully (no crash, no fabrication) AND fails loud on stderr.
    assert jobs == []
    err = capsys.readouterr().err
    assert "403" in err
    assert "REDDIT_CLIENT_ID" in err
    assert "REDDIT_CLIENT_SECRET" in err


@responses.activate
def test_scrape_returns_empty_on_html_block_body(monkeypatch, capsys):
    # Some block pages come back as 200 with an HTML body instead of JSON.
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
    responses.add(
        responses.GET,
        LISTING_URL_PATTERN,
        body="<!DOCTYPE html><html>whoa there, pardner</html>",
        status=200,
        content_type="text/html",
    )

    scraper = RedditJobsScraper()
    jobs = scraper.scrape(["any"])

    assert jobs == []
    err = capsys.readouterr().err
    assert "JSON" in err


@responses.activate
def test_oauth_flow_fetches_and_parses(monkeypatch):
    # Both creds present -> client-credentials token flow + oauth.reddit.com listing.
    monkeypatch.setenv("REDDIT_CLIENT_ID", "test_client_id")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "test_client_secret")

    responses.add(
        responses.POST,
        TOKEN_URL,
        json={"access_token": "test_bearer_token", "token_type": "bearer", "expires_in": 3600},
        status=200,
    )
    listing = {
        "data": {
            "after": None,
            "children": [
                {
                    "data": {
                        "title": "[Hiring] Backend Engineer | Acme Corp | Remote",
                        "selftext": "We need a backend engineer. Python, AWS. $140K-$170K.",
                        "author": "acme_hr",
                        "subreddit": "forhire",
                        "permalink": "/r/forhire/comments/aaa/hiring_backend/",
                        "created_utc": 1743897600.0,
                        "link_flair_text": "Hiring",
                    }
                }
            ],
        }
    }
    responses.add(responses.GET, OAUTH_LISTING_URL_PATTERN, json=listing, status=200)

    scraper = RedditJobsScraper()
    jobs = scraper.scrape(["any"])

    assert len(jobs) == 1
    assert jobs[0].company == "Acme Corp"
    assert jobs[0].salary_min == 140000

    # Token endpoint hit with HTTP basic auth + grant_type, listing carried the bearer.
    token_call = responses.calls[0]
    assert token_call.request.url == TOKEN_URL
    assert "grant_type=client_credentials" in token_call.request.body
    assert "Authorization" in token_call.request.headers  # basic auth header
    listing_call = responses.calls[1]
    assert listing_call.request.headers["Authorization"] == "bearer test_bearer_token"
    assert "oauth.reddit.com" in listing_call.request.url


@responses.activate
def test_oauth_token_failure_returns_empty(monkeypatch, capsys):
    # Creds present but the token endpoint rejects them: fail loud, return [].
    monkeypatch.setenv("REDDIT_CLIENT_ID", "bad_id")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "bad_secret")
    responses.add(responses.POST, TOKEN_URL, json={"error": "invalid_grant"}, status=401)

    scraper = RedditJobsScraper()
    jobs = scraper.scrape(["any"])

    assert jobs == []
    err = capsys.readouterr().err
    assert "OAuth token request returned 401" in err


@responses.activate
def test_fetch_listings_retries_on_429(monkeypatch):
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
    responses.add(responses.GET, LISTING_URL_PATTERN, json={"error": "rate limited"}, status=429)
    responses.add(
        responses.GET,
        LISTING_URL_PATTERN,
        json={
            "data": {
                "after": None,
                "children": [
                    {
                        "data": {
                            "title": "[Hiring] Test role",
                            "selftext": "A job post.",
                            "author": "poster",
                            "subreddit": "hiring",
                            "permalink": "/r/hiring/comments/xyz/test/",
                            "created_utc": 1743897600.0,
                            "link_flair_text": "Hiring",
                        }
                    }
                ],
            }
        },
        status=200,
    )

    scraper = RedditJobsScraper()
    posts = scraper._fetch_listings()

    assert len(posts) == 1
    assert len(responses.calls) == 2


@responses.activate
def test_scrape_survives_null_title_and_subreddit(monkeypatch):
    # Reddit can send explicit nulls for string fields (removed/edited posts).
    # .get(k, "") only defaults on a MISSING key, not a present-but-None value,
    # so a null title used to crash re.search() (line 180) and a null subreddit
    # used to crash .lower() (line 184). The never-crash contract requires these
    # malformed posts be skipped gracefully while valid posts still come through.
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
    listing = {
        "data": {
            "after": None,
            "children": [
                # Null title — would crash re.search() on the [for hire] check.
                {
                    "data": {
                        "title": None,
                        "selftext": "We're hiring engineers.",
                        "author": "poster",
                        "subreddit": "forhire",
                        "permalink": "/r/forhire/comments/n1/null_title/",
                        "created_utc": 1743897600.0,
                        "link_flair_text": "Hiring",
                    }
                },
                # Null subreddit — would crash .lower() on the tier check.
                {
                    "data": {
                        "title": "[Hiring] Backend Engineer | Acme Corp | Remote",
                        "selftext": "We need a backend engineer. Hiring now.",
                        "author": "poster",
                        "subreddit": None,
                        "permalink": "/r/unknown/comments/n2/null_sub/",
                        "created_utc": 1743897500.0,
                        "link_flair_text": "Hiring",
                    }
                },
                # A clean, valid Tier-1 post must still be parsed and returned.
                {
                    "data": {
                        "title": "[Hiring] Senior Dev | GoodCo | Remote",
                        "selftext": "Join us. $140K-$170K.",
                        "author": "goodco_hr",
                        "subreddit": "forhire",
                        "permalink": "/r/forhire/comments/n3/valid/",
                        "created_utc": 1743897400.0,
                        "link_flair_text": "Hiring",
                    }
                },
            ],
        }
    }
    responses.add(responses.GET, LISTING_URL_PATTERN, json=listing, status=200)

    scraper = RedditJobsScraper()
    jobs = scraper.scrape(["any"])  # must not raise

    # Null-title post is skipped (empty title -> try_create rejects it).
    # Null-subreddit post is treated as Tier-2 (not in _TIER_1_LOWER), passes
    # the hiring-signal filter, and is kept. Valid post is kept.
    titles = [j.title for j in jobs]
    assert "[Hiring] Backend Engineer | Acme Corp | Remote" in titles
    assert "[Hiring] Senior Dev | GoodCo | Remote" in titles
    assert all(t for t in titles)  # no empty titles leaked through


@responses.activate
def test_scrape_logs_aggregate_url_skip(monkeypatch, capsys):
    # I2: a post that passes every editorial filter but has no permalink yields an
    # empty job_url -> try_create returns None. The per-post skip stays graceful,
    # but the scrape must emit ONE aggregate line so a mass URL-field failure isn't
    # mistaken for "no matches." Only try_create skips count, not filter-skips.
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
    listing = {
        "data": {
            "after": None,
            "children": [
                # Tier-1, valid title/author, but NO permalink -> empty job_url -> skipped.
                {
                    "data": {
                        "title": "[Hiring] Backend Engineer | Acme Corp | Remote",
                        "selftext": "We need a backend engineer.",
                        "author": "acme_hr",
                        "subreddit": "forhire",
                        "permalink": "",
                        "created_utc": 1743897600.0,
                        "link_flair_text": "Hiring",
                    }
                },
                # A clean Tier-1 post that survives.
                {
                    "data": {
                        "title": "[Hiring] Senior Dev | GoodCo | Remote",
                        "selftext": "Join us.",
                        "author": "goodco_hr",
                        "subreddit": "forhire",
                        "permalink": "/r/forhire/comments/ok/valid/",
                        "created_utc": 1743897500.0,
                        "link_flair_text": "Hiring",
                    }
                },
                # A filter-skip (AutoModerator) — must NOT inflate the URL-skip count.
                {
                    "data": {
                        "title": "Weekly thread",
                        "selftext": "Discuss.",
                        "author": "AutoModerator",
                        "subreddit": "forhire",
                        "permalink": "/r/forhire/comments/wk/weekly/",
                        "created_utc": 1743897400.0,
                        "link_flair_text": None,
                    }
                },
            ],
        }
    }
    responses.add(responses.GET, LISTING_URL_PATTERN, json=listing, status=200)

    scraper = RedditJobsScraper()
    jobs = scraper.scrape(["any"])

    # Only the valid post survives; the no-URL post is dropped.
    assert [j.title for j in jobs] == ["[Hiring] Senior Dev | GoodCo | Remote"]
    # 1 URL skip out of 2 try_create candidates (the AutoModerator post never
    # reached try_create, so it's excluded from both counts).
    err = capsys.readouterr().err
    assert "[reddit] skipped 1/2 postings: invalid/empty job_url" in err


@responses.activate
def test_scrape_no_skip_line_when_all_urls_valid(monkeypatch, capsys):
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
    listing = {
        "data": {
            "after": None,
            "children": [
                {
                    "data": {
                        "title": "[Hiring] Senior Dev | GoodCo | Remote",
                        "selftext": "Join us.",
                        "author": "goodco_hr",
                        "subreddit": "forhire",
                        "permalink": "/r/forhire/comments/ok/valid/",
                        "created_utc": 1743897500.0,
                        "link_flair_text": "Hiring",
                    }
                },
            ],
        }
    }
    responses.add(responses.GET, LISTING_URL_PATTERN, json=listing, status=200)

    scraper = RedditJobsScraper()
    jobs = scraper.scrape(["any"])

    assert len(jobs) == 1
    # Nothing skipped at the try_create stage -> no aggregate line.
    assert "skipped" not in capsys.readouterr().err


def test_parse_post_null_fields_returns_none_not_crash():
    # Direct unit-level guard: an all-null post must return None, never raise.
    scraper = RedditJobsScraper()
    result = scraper._parse_post(
        {"title": None, "subreddit": None, "selftext": None, "author": None}
    )
    assert result is None


def test_extract_company_pipe_format():
    scraper = RedditJobsScraper()
    # Bracket prefix detected in parts[0], returns parts[1]
    assert scraper._extract_company("[Hiring] Acme Corp | Backend Dev | Remote", "forhire") == "Backend Dev"


def test_extract_company_bracket_format():
    scraper = RedditJobsScraper()
    assert scraper._extract_company("Looking for devs [TechStartup]", "webdev") == "TechStartup"


def test_extract_company_bold_format():
    scraper = RedditJobsScraper()
    assert scraper._extract_company("**MegaCorp** is hiring engineers", "hiring") == "MegaCorp"


def test_extract_company_at_format():
    scraper = RedditJobsScraper()
    assert scraper._extract_company("Senior engineer at CloudBase", "remotejobs") == "CloudBase"


def test_extract_company_fallback():
    scraper = RedditJobsScraper()
    assert scraper._extract_company("Need help with my project", "webdev") == "r/webdev"
