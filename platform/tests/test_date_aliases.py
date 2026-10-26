from talent_platform.ai_domain import experience_months, ground_profile, verified_values


def test_verified_date_aliases_normalize_without_losing_original_evidence():
    record = {'title': 'Python工程师', 'company': '合成科技', 'start_date': '2024-07', 'end_date': '2025-07'}
    quote = '2024-07 至 2025-07，合成科技，Python工程师。'
    profile, _ = ground_profile({'experiences': [record], 'evidence': [{'field': 'experiences', 'value': record, 'quote': quote}]}, quote)
    assert profile['experience_months'] == 12
    assert profile['experiences'][0]['start'] == '2024-07'
    assert profile['evidence'][0]['value'] == record
    assert verified_values(profile, 'experiences') == profile['experiences']


def test_previously_cached_date_aliases_still_count_without_reextracting():
    months, unknown = experience_months([{'start_date': '2020-01', 'end_date': '2025-01'}, {'start': None, 'end': None}])
    assert months == 60 and unknown
