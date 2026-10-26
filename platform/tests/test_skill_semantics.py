from talent_platform.ai_domain import ground_profile, missing_core_fields


def test_generic_job_title_cannot_be_used_to_claim_a_verified_skill():
    source = '姓名：合成甲\n邮箱：synthetic@example.test\n学历：本科\n工作：工程师'
    raw = {'name': '合成甲', 'email': 'synthetic@example.test', 'skills': ['工程师'], 'education': ['本科'],
           'evidence': [
               {'field': 'name', 'value': '合成甲', 'quote': '姓名：合成甲'},
               {'field': 'email', 'value': 'synthetic@example.test', 'quote': '邮箱：synthetic@example.test'},
               {'field': 'skills', 'value': '工程师', 'quote': '工作：工程师'},
               {'field': 'education', 'value': '本科', 'quote': '学历：本科'}]}
    profile, issues = ground_profile(raw, source)
    assert profile['skills'] == [] and missing_core_fields(profile) == ['skills']
    assert 'invalid:skills_category' in issues
