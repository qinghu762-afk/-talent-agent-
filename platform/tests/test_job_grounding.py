import pytest
from test_ai import Responses, platform, run


def test_skill_requirement_can_bind_a_qualified_value_in_exact_source_quote():
    requirements = {'required_skills': ['Python'], 'preferred_skills': ['SQL'], 'evidence': [
        {'field': 'required_skills', 'value': '必须掌握Python', 'quote': '必须掌握Python。'},
        {'field': 'preferred_skills', 'value': '优先掌握SQL', 'quote': '优先掌握SQL。'}]}
    result = run(platform(Responses({'requirements': requirements})), 'job', {'description': '必须掌握Python。优先掌握SQL。'})
    assert result['requirements']['required_skills'] == ['Python']
    assert result['requirements']['evidence'][0]['quote'] == '必须掌握Python。'


def test_qualified_value_never_substitutes_javascript_or_upgrades_preference():
    for value, quote in [('熟悉JavaScript', '熟悉JavaScript'), ('优先Java', '优先Java')]:
        requirements = {'required_skills': ['Java'], 'evidence': [{'field': 'required_skills', 'value': value, 'quote': quote}]}
        with pytest.raises(ValueError):
            run(platform(Responses({'requirements': requirements})), 'job', {'description': quote})
