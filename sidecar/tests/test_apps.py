from samsung_sidecar.apps import APP_IDS, app_for


def test_app_ids():
    assert app_for("https://www.youtube.com") == "111299001912"
    assert app_for("youtube.com/") == "111299001912"
    assert app_for("https://x.org") is None


def test_all_apps():
    assert app_for("https://www.netflix.com") == "3201907018807"
    assert app_for("https://www.primevideo.com") == "3201910019365"
    assert app_for("https://www.disneyplus.com") == "3201901017640"
    assert app_for("https://www.globoplay.globo.com/") == "3201908019041"
    assert app_for("globoplay.globo.com") == "3201908019041"
    assert len(APP_IDS) == 5
