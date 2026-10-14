import pytest

@pytest.mark.parametrize('name',['personal_crm','personal_crm_test','personal_crm_test_web','other_test_load'])
def test_load_rehearsal_cannot_seed_normal_or_browser_database(name):
    from personal_crm.load_rehearsal import guard
    with pytest.raises(ValueError):guard('postgresql+psycopg://synthetic@127.0.0.1/'+name)

def test_only_dedicated_load_database_is_allowed():
    from personal_crm.load_rehearsal import guard
    guard('postgresql+psycopg://synthetic@127.0.0.1/personal_crm_test_load_pilot')
